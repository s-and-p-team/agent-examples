"""Clinical review — is the requested procedure clinically justified?

One pass, four steps, always in the same order:

1. read the member's clinical history from the Patient Records MCP server;
2. look the requested procedure up in the Medical Coding MCP server;
3. look the relevant drug up in the same coding server;
4. ask the model for a recommendation.

Two different MCP servers are consulted, one holding patient data and one
holding reference data. Keeping them apart is the point: the coding server never
sees a patient identifier.
"""

import json
import logging
import os

import httpx
import httpx2

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

logger = logging.getLogger(__name__)

RECORDS_MCP_URL = os.getenv("RECORDS_MCP_URL", "http://priorauth-records-tool:8000/mcp")
CODING_MCP_URL = os.getenv("CODING_MCP_URL", "http://priorauth-coding-tool:8000/mcp")
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))

SYSTEM_PROMPT = (
    "You are a clinical reviewer for prior authorization. Given a patient's "
    "history and the coding reference for a requested procedure, say whether the "
    "request is clinically justified. Answer in at most three sentences, and "
    "begin with exactly one of: SUPPORTED, NOT SUPPORTED, MORE INFORMATION NEEDED."
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


async def chat(system: str, user: str, max_tokens: int = 220) -> str:
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
    """`request_text` is the JSON the intake agent sends: mrn, diagnosis_name,
    requested_procedure, drug_name."""
    try:
        request = json.loads(request_text)
    except (ValueError, TypeError):
        return "MORE INFORMATION NEEDED — the clinical request was not valid JSON."

    mrn = request.get("mrn", "")
    requested_procedure = request.get("requested_procedure", "")
    drug_name = request.get("drug_name", "")
    diagnosis_name = request.get("diagnosis_name", "")

    logger.info("clinical review: mrn=%s procedure=%s drug=%s", mrn, requested_procedure, drug_name)

    history_json = await call_mcp_tool(RECORDS_MCP_URL, "get_clinical_history", {"mrn": mrn})
    procedure_json = await call_mcp_tool(CODING_MCP_URL, "lookup_procedure_code", {"procedure": requested_procedure})
    drug_json = await call_mcp_tool(CODING_MCP_URL, "lookup_drug", {"drug_name": drug_name or "none"})

    verdict = await chat(
        SYSTEM_PROMPT,
        (
            f"Working diagnosis: {diagnosis_name}\n"
            f"Requested procedure: {requested_procedure}\n"
            f"Coding reference for the procedure: {procedure_json}\n"
            f"Coding reference for the drug: {drug_json}\n"
            f"Patient clinical history: {history_json}\n\n"
            "Is this request clinically justified by the history?"
        ),
    )
    logger.info("clinical verdict: %s", verdict.splitlines()[0] if verdict else "(empty)")
    return verdict
