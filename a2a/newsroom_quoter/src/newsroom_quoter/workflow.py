"""Quote desk — pull one verbatim sentence out of the article.

The quoter is the newsroom's checkable transformation: its output must be a
literal substring of its input. The model picks the sentence, the code
verifies the pick, and the result says whether verification passed — so anyone
reading the lineage can confirm by eye that this payload descends from the
article, no model trust required. If the model paraphrases, the first sentence
of the article is used instead, and `verbatim` is still honest.
"""

import json
import logging
import os
import re

import httpx
import httpx2

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

logger = logging.getLogger(__name__)

ARCHIVE_MCP_URL = os.getenv("ARCHIVE_MCP_URL", "http://newsroom-archive-tool:8000/mcp")
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))

SYSTEM_PROMPT = (
    "You are a newspaper quote picker. Given an article and the editor's "
    "angle, reply with the single most quotable sentence, copied from the "
    "article EXACTLY, character for character. No quotation marks around it, "
    "no commentary, nothing else."
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


async def chat(system: str, user: str, max_tokens: int = 200) -> str:
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


def _first_sentence(article: str) -> str:
    match = re.search(r"[^.!?]*[.!?]", article.strip())
    return match.group(0).strip() if match else article.strip()[:200]


async def pick_quote(request_text: str) -> str:
    """`request_text` is the JSON the editor sends: story_id, angle, article."""
    try:
        request = json.loads(request_text)
    except (ValueError, TypeError):
        return json.dumps({"error": "the quote request was not valid JSON"})

    story_id = request.get("story_id", "")
    angle = request.get("angle", "")
    article = request.get("article", "")
    logger.info("picking a quote for story %s", story_id)

    candidate = await chat(
        SYSTEM_PROMPT,
        f"Editor's angle: {angle}\n\nArticle:\n{article}",
    )
    candidate = candidate.strip().strip('"').strip()

    verbatim = bool(candidate) and candidate in article
    quote = candidate if verbatim else _first_sentence(article)
    if not verbatim:
        logger.warning("model quote was not verbatim, falling back to the first sentence")

    await call_mcp_tool(
        ARCHIVE_MCP_URL,
        "save_artifact",
        {"story_id": story_id, "kind": "quote", "text": quote, "author": "newsroom-quoter"},
    )
    logger.info("story %s quote picked (verbatim=%s)", story_id, verbatim)
    return json.dumps({"story_id": story_id, "quote": quote, "verbatim": verbatim})
