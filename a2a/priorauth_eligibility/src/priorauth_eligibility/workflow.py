"""Eligibility review — does this member's plan cover the requested procedure?

One pass, three steps, always in the same order:

1. read the member's policy from the Patient Records MCP server;
2. ask the model to weigh the policy against the request;
3. return a verdict line the intake agent can quote.

The order is fixed on purpose. A reviewer that sometimes skips the policy read
would be a worse example, and an unpredictable one.
"""

import json
import logging
import os

import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

RECORDS_MCP_URL = os.getenv("RECORDS_MCP_URL", "http://priorauth-records-tool:8000/mcp")
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))

SYSTEM_PROMPT = (
    "You are a health-plan eligibility reviewer. Given a member's policy and a "
    "requested procedure, decide whether the plan covers it. Answer in at most "
    "three sentences, and begin with exactly one of: COVERED, NOT COVERED, "
    "NEEDS REVIEW."
)


async def call_mcp_tool(url: str, tool: str, arguments: dict) -> str:
    """One MCP session per call: connect, initialize, invoke, close.

    A long-lived session would be more efficient. Per-call sessions are what
    most agent frameworks actually do, and they keep each tool invocation a
    self-contained unit of work.
    """
    async with (
        streamablehttp_client(url=url, timeout=MCP_TIMEOUT, sse_read_timeout=MCP_TIMEOUT) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                return text
        return ""


async def chat(system: str, user: str, max_tokens: int = 220) -> str:
    """One chat completion against the OpenAI-compatible endpoint."""
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


async def review(request_text: str) -> str:
    """`request_text` is the JSON the intake agent sends: policy_number,
    procedure_code, requested_procedure, mrn, patient_name."""
    try:
        request = json.loads(request_text)
    except (ValueError, TypeError):
        return "NEEDS REVIEW — the eligibility request was not valid JSON."

    policy_number = request.get("policy_number", "")
    procedure_code = request.get("procedure_code", "")
    requested_procedure = request.get("requested_procedure", "")

    logger.info(
        "eligibility review: policy=%s procedure=%s (%s)",
        policy_number,
        procedure_code,
        requested_procedure,
    )

    policy_json = await call_mcp_tool(RECORDS_MCP_URL, "get_policy", {"policy_number": policy_number})

    verdict = await chat(
        SYSTEM_PROMPT,
        (
            f"Requested procedure: {requested_procedure} (CPT {procedure_code}).\n"
            f"Member policy record: {policy_json}\n\n"
            "Does the plan cover this procedure? Consider the excluded procedure "
            "codes and whether prior authorization is required."
        ),
    )
    logger.info("eligibility verdict: %s", verdict.splitlines()[0] if verdict else "(empty)")
    return verdict
