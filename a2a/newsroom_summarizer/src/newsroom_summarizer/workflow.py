"""Summary desk — condense the article, then hand the summary onward.

Three steps, always in the same order:

1. summarize the article with the model, guided by the editor's angle;
2. file the summary in the story archive;
3. delegate the headline to the Headline Desk, passing only the summary.

Step 3 is what makes the newsroom a chain rather than a star: the editor never
talks to the titler, so the delegation path is editor -> summarizer -> titler,
and the headline is derived from a text that is itself derived.
"""

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
TITLER_URL = os.getenv("TITLER_URL", "http://newsroom-titler:8080/")
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))
PEER_TIMEOUT = float(os.getenv("PEER_TIMEOUT", "600"))

SYSTEM_PROMPT = (
    "You are a newspaper summary writer. Given an article and the editor's "
    "angle, reply with a summary of exactly three sentences that serves that "
    "angle, and nothing else."
)


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


async def summarize(request_text: str) -> str:
    """`request_text` is the JSON the editor sends: story_id, angle, article."""
    try:
        request = json.loads(request_text)
    except (ValueError, TypeError):
        return json.dumps({"error": "the summary request was not valid JSON"})

    story_id = request.get("story_id", "")
    angle = request.get("angle", "")
    article = request.get("article", "")
    logger.info("summarizing story %s (%d characters)", story_id, len(article))

    summary = await chat(
        SYSTEM_PROMPT,
        f"Editor's angle: {angle}\n\nArticle:\n{article}",
    )

    await call_mcp_tool(
        ARCHIVE_MCP_URL,
        "save_artifact",
        {"story_id": story_id, "kind": "summary", "text": summary, "author": "newsroom-summarizer"},
    )

    titled_raw = await ask_agent(TITLER_URL, {"story_id": story_id, "summary": summary})
    headline = ""
    try:
        headline = json.loads(titled_raw).get("title", "")
    except (ValueError, TypeError):
        logger.warning("could not parse the titler reply: %r", titled_raw[:200])

    logger.info("story %s summarized and titled: %s", story_id, headline or "(no title)")
    return json.dumps({"story_id": story_id, "summary": summary, "title": headline})
