"""Headline desk — turn a summary into a headline.

The titler never sees the article. It works from the summarizer's summary
alone, so its output is a second-order derivation: article -> summary ->
headline. That is the point of this agent — the lineage graph should show the
headline descending from the summary, not from the source text.
"""

import json
import logging
import os

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
    "You are a newspaper headline writer. Given a story summary, reply with "
    "one headline of at most ten words, in headline case, and nothing else. "
    "No quotation marks, no trailing period."
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


async def chat(system: str, user: str, max_tokens: int = 60) -> str:
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


async def title(request_text: str) -> str:
    """`request_text` is the JSON the summarizer sends: story_id, summary."""
    try:
        request = json.loads(request_text)
    except (ValueError, TypeError):
        return json.dumps({"error": "the titling request was not valid JSON"})

    story_id = request.get("story_id", "")
    summary = request.get("summary", "")
    logger.info("titling story %s from a %d-character summary", story_id, len(summary))

    headline = await chat(SYSTEM_PROMPT, f"Story summary:\n{summary}")
    headline = headline.strip().strip('"').strip()

    await call_mcp_tool(
        ARCHIVE_MCP_URL,
        "save_artifact",
        {"story_id": story_id, "kind": "title", "text": headline, "author": "newsroom-titler"},
    )
    logger.info("story %s titled: %s", story_id, headline)
    return json.dumps({"story_id": story_id, "title": headline})
