"""Editor's desk — one article in, one front-page brief out.

A wire service sends a raw article. This module runs it through the newsroom:

1.  **angle** — decide the editorial angle with the model, one sentence;
2.  **assign** — send the article and the angle to the Summary Desk and the
    Quote Desk *concurrently*. The Summary Desk delegates the headline onward
    to the Headline Desk on its own, so the editor never talks to the titler;
3.  **keywords** — extract keywords with the model *from the summary that came
    back*, not from the article: a derivation of a derivation;
4.  **compose** — have the model write the front-page brief out of the title,
    the summary, the quote and the keywords — every upstream artifact flows
    into this one payload;
5.  **file** — save the keywords and the brief in the story archive;
6.  **syndicate** — announce the story to the external wire, over plain HTTP
    and over HTTPS, because a real deployment has both kinds of outbound call
    and they behave differently on the wire.

Step 2's two desks run at the same time on purpose: they are independent, and
both of their subtrees write to the same archive tool while both are open.

The point of the newsroom is that every payload is TEXT DERIVED FROM TEXT: the
lineage graph of one turn shows the article become a summary, the summary a
headline and keywords, the article a verbatim quote, and all of them the brief.
"""

import asyncio
import json
import logging
import os
import uuid

import httpx
import httpx2

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

logger = logging.getLogger(__name__)

ARCHIVE_MCP_URL = os.getenv("ARCHIVE_MCP_URL", "http://newsroom-archive-tool:8000/mcp")
SUMMARIZER_URL = os.getenv("SUMMARIZER_URL", "http://newsroom-summarizer:8080/")
QUOTER_URL = os.getenv("QUOTER_URL", "http://newsroom-quoter:8080/")

# Syndication announcement. The SAME ping is issued twice, once in the clear
# and once over TLS, because a real deployment usually has both kinds of
# outbound call and they behave differently on the wire.
SYNDICATION_HTTP_URL = os.getenv("SYNDICATION_HTTP_URL", "http://httpbingo.org/anything/syndicate")
SYNDICATION_HTTPS_URL = os.getenv("SYNDICATION_HTTPS_URL", "https://httpbingo.org/anything/syndicate")

LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))
PEER_TIMEOUT = float(os.getenv("PEER_TIMEOUT", "600"))
SYNDICATION_TIMEOUT = float(os.getenv("SYNDICATION_TIMEOUT", "20"))

ANGLE_SYSTEM = (
    "You are a newspaper assignment editor. Given an article, reply with one "
    "sentence stating the editorial angle the coverage should take, and "
    "nothing else."
)

KEYWORDS_SYSTEM = (
    "You extract index keywords from a story summary. Reply with exactly five "
    "keywords, lowercase, comma-separated, and nothing else."
)

BRIEF_SYSTEM = (
    "You are a front-page editor. You are given a headline, a summary, a "
    "pull-quote and keywords. Compose a front-page brief of at most 120 "
    "words: the headline on the first line, then one paragraph that works in "
    "the pull-quote verbatim. Reply with the brief and nothing else."
)


# --- plumbing ---------------------------------------------------------------


async def call_mcp_tool(url: str, tool: str, arguments: dict) -> str:
    """One MCP session per call: connect, initialize, invoke, close."""
    async with (
        create_mcp_http_client(timeout=httpx2.Timeout(MCP_TIMEOUT)) as http_client,
        streamable_http_client(url, http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                return text
        return ""


async def chat(system: str, user: str, max_tokens: int = 300) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _first_text_part(payload) -> str:
    """Walk an A2A JSON-RPC response for the first text part."""
    found: list[str] = []

    def walk(node):
        if found:
            return
        if isinstance(node, dict):
            text = node.get("text")
            if isinstance(text, str) and text.strip():
                found.append(text)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found[0] if found else ""


async def ask_agent(url: str, request: dict) -> str:
    """Send one A2A `message/send` and return the peer's text reply."""
    body = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "parts": [{"kind": "text", "text": json.dumps(request)}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=PEER_TIMEOUT) as client:
        resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    return _first_text_part(resp.json())


async def syndicate(story_id: str) -> dict:
    """Announce the story to the external wire, twice: once over plain HTTP
    and once over HTTPS. Wire outages must not fail an edition, so both calls
    are best-effort."""

    async def once(url: str) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=SYNDICATION_TIMEOUT) as client:
                resp = await client.get(f"{url}/{story_id or 'unknown'}")
            return resp.status_code
        except Exception as exc:  # noqa: BLE001 — the wire is advisory
            logger.warning("syndication ping failed for %s: %s", url, exc)
            return None

    http_status, https_status = await asyncio.gather(once(SYNDICATION_HTTP_URL), once(SYNDICATION_HTTPS_URL))
    return {"http_status": http_status, "https_status": https_status}


def _parse_reply(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("could not parse a desk reply as JSON: %r", raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --- the edition ------------------------------------------------------------


async def run_story(article: str) -> str:
    """Run one article all the way to a filed front-page brief."""
    story_id = f"NEWS-{uuid.uuid4().hex[:8]}"

    # 1. angle
    angle = await chat(ANGLE_SYSTEM, f"Article:\n{article}", max_tokens=80)
    logger.info("story %s angle: %s", story_id, angle)

    # 2. assign — both desks at once
    summary_task = ask_agent(
        SUMMARIZER_URL,
        {"story_id": story_id, "angle": angle, "article": article},
    )
    quote_task = ask_agent(
        QUOTER_URL,
        {"story_id": story_id, "angle": angle, "article": article},
    )
    summary_raw, quote_raw = await asyncio.gather(summary_task, quote_task)
    summary_reply = _parse_reply(summary_raw)
    quote_reply = _parse_reply(quote_raw)
    summary = summary_reply.get("summary", "")
    headline = summary_reply.get("title", "")
    quote = quote_reply.get("quote", "")
    quote_verbatim = bool(quote_reply.get("verbatim", False))
    logger.info("story %s desks returned (title=%r, verbatim=%s)", story_id, headline, quote_verbatim)

    # 3. keywords — from the summary, not the article
    keywords = await chat(KEYWORDS_SYSTEM, f"Story summary:\n{summary}", max_tokens=60)

    # 4. compose the brief out of everything the newsroom produced
    brief = await chat(
        BRIEF_SYSTEM,
        (f"Headline: {headline}\nSummary: {summary}\nPull-quote: {quote}\nKeywords: {keywords}"),
        max_tokens=260,
    )

    # 5. file the editor's own artifacts
    await call_mcp_tool(
        ARCHIVE_MCP_URL,
        "save_artifact",
        {"story_id": story_id, "kind": "keywords", "text": keywords, "author": "newsroom-editor"},
    )
    await call_mcp_tool(
        ARCHIVE_MCP_URL,
        "save_artifact",
        {"story_id": story_id, "kind": "brief", "text": brief, "author": "newsroom-editor"},
    )

    # 6. announce the edition
    wire = await syndicate(story_id)
    logger.info("story %s syndicated: %s", story_id, wire)

    return json.dumps(
        {
            "story_id": story_id,
            "angle": angle,
            "title": headline,
            "summary": summary,
            "quote": quote,
            "quote_verbatim": quote_verbatim,
            "keywords": keywords,
            "brief": brief,
            "syndication": wire,
        },
        indent=2,
    )
