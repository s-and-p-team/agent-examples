"""Referral intake — the whole prior-authorization determination, end to end.

A clinic sends a referral note in free text. This module turns it into a
determination:

1.  **extract** the structured facts from the note with the model;
2.  **identify** the member by MRN in the Patient Records service;
3.  **file** the referral in the Authorization Store (a different service,
    backed by a different database);
4.  **verify** the requesting provider against an external directory — the same
    lookup is made over plain HTTP and over HTTPS;
5.  **review**, asking the Eligibility and Clinical agents *concurrently*;
6.  **decide**, with the model weighing both verdicts;
7.  **record** the decision in the Authorization Store, and separately in the
    Audit Trail service, which writes it to a file and to Redis.

Steps 5's two reviews run at the same time on purpose: the two agents are
independent and a real system would not serialise them.
"""

import asyncio
import json
import logging
import os
import re
import uuid

import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

RECORDS_MCP_URL = os.getenv("RECORDS_MCP_URL", "http://priorauth-records-tool:8000/mcp")
AUTHSTORE_MCP_URL = os.getenv("AUTHSTORE_MCP_URL", "http://priorauth-authstore-tool:8000/mcp")
AUDIT_MCP_URL = os.getenv("AUDIT_MCP_URL", "http://priorauth-audit-tool:8000/mcp")
ELIGIBILITY_URL = os.getenv("ELIGIBILITY_URL", "http://priorauth-eligibility:8080/")
CLINICAL_URL = os.getenv("CLINICAL_URL", "http://priorauth-clinical:8080/")

# Provider directory verification. The SAME lookup is issued twice, once in the
# clear and once over TLS, because a real deployment usually has both kinds of
# outbound call and they behave differently on the wire.
DIRECTORY_HTTP_URL = os.getenv("DIRECTORY_HTTP_URL", "http://httpbingo.org/anything/npi")
DIRECTORY_HTTPS_URL = os.getenv("DIRECTORY_HTTPS_URL", "https://httpbingo.org/anything/npi")

LLM_API_BASE = os.getenv("LLM_API_BASE", "http://host.containers.internal:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "60"))
PEER_TIMEOUT = float(os.getenv("PEER_TIMEOUT", "600"))
DIRECTORY_TIMEOUT = float(os.getenv("DIRECTORY_TIMEOUT", "20"))

EXTRACT_SYSTEM = (
    "You extract structured data from clinical referral notes. Reply with a "
    "single JSON object and nothing else. Use exactly these keys: "
    "patient_name, mrn, date_of_birth, policy_number, diagnosis_name, "
    "requested_procedure, drug_name, requesting_provider_npi. "
    "Use an empty string for anything the note does not state. "
    "date_of_birth must be YYYY-MM-DD."
)

DECIDE_SYSTEM = (
    "You are a prior-authorization officer. You are given an eligibility verdict "
    "and a clinical verdict. Reply with a single line of the form "
    "'OUTCOME: <approved|denied|pended> — <one sentence of reasoning>'. "
    "Approve only if coverage is confirmed and the request is clinically "
    "supported; deny if either is clearly negative; otherwise pend."
)


# --- plumbing ---------------------------------------------------------------


async def call_mcp_tool(url: str, tool: str, arguments: dict) -> str:
    """One MCP session per call: connect, initialize, invoke, close."""
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


async def chat(system: str, user: str, max_tokens: int = 400) -> str:
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
    """Walk an A2A JSON-RPC response for the first text part.

    The response shape differs between task artifacts and status messages, and
    between protocol revisions, so this looks for the shape rather than
    assuming one. Returns "" when the response carries no text at all.
    """
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


async def verify_provider(npi: str) -> dict:
    """Look the requesting provider up in the external directory, twice: once
    over plain HTTP and once over HTTPS. Directory outages must not fail a
    determination, so both calls are best-effort."""

    async def once(url: str) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=DIRECTORY_TIMEOUT) as client:
                resp = await client.get(f"{url}/{npi or 'unknown'}")
            return resp.status_code
        except Exception as exc:  # noqa: BLE001 — directory is advisory
            logger.warning("provider directory lookup failed for %s: %s", url, exc)
            return None

    http_status, https_status = await asyncio.gather(once(DIRECTORY_HTTP_URL), once(DIRECTORY_HTTPS_URL))
    return {"http_status": http_status, "https_status": https_status}


def _parse_extraction(raw: str) -> dict:
    """The model is asked for bare JSON; models sometimes wrap it in prose or a
    code fence. Recover the object rather than failing the referral."""
    candidate = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        logger.warning("could not parse extraction as JSON: %r", raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --- the determination ------------------------------------------------------


async def handle_referral(note: str) -> str:
    """Run one referral all the way to a recorded determination."""

    # 1. extract
    extraction_raw = await chat(EXTRACT_SYSTEM, f"Referral note:\n{note}")
    facts = _parse_extraction(extraction_raw)
    mrn = str(facts.get("mrn", "")).strip()
    patient_name = str(facts.get("patient_name", "")).strip()
    logger.info("extracted mrn=%s name=%s", mrn, patient_name)

    # 2. identify — the member record is authoritative for the policy number
    member_json = await call_mcp_tool(RECORDS_MCP_URL, "get_member", {"mrn": mrn})
    member = json.loads(member_json).get("member", {}) if member_json else {}
    policy_number = member.get("policy_number") or str(facts.get("policy_number", ""))
    patient_name = member.get("full_name") or patient_name
    date_of_birth = str(member.get("date_of_birth") or facts.get("date_of_birth", ""))

    requested_procedure = str(facts.get("requested_procedure", ""))
    diagnosis_name = str(facts.get("diagnosis_name", ""))
    drug_name = str(facts.get("drug_name", ""))
    npi = str(facts.get("requesting_provider_npi", ""))

    # 3. file the referral
    saved = await call_mcp_tool(
        AUTHSTORE_MCP_URL,
        "save_referral",
        {
            "patient_name": patient_name,
            "mrn": mrn,
            "date_of_birth": date_of_birth,
            "policy_number": policy_number,
            "diagnosis_name": diagnosis_name,
            "icd10_code": str(facts.get("icd10_code", "")),
            "requested_procedure": requested_procedure,
            "procedure_code": "",
            "requesting_provider_npi": npi,
            "clinical_note": note,
        },
    )
    referral_id = json.loads(saved).get("referral_id", "PA-UNKNOWN") if saved else "PA-UNKNOWN"
    logger.info("filed referral %s", referral_id)

    # 4. verify the provider against the external directory
    directory = await verify_provider(npi)
    logger.info("provider directory: %s", directory)

    # 5. review — both agents at once
    eligibility_task = ask_agent(
        ELIGIBILITY_URL,
        {
            "referral_id": referral_id,
            "mrn": mrn,
            "patient_name": patient_name,
            "policy_number": policy_number,
            "procedure_code": "",
            "requested_procedure": requested_procedure,
        },
    )
    clinical_task = ask_agent(
        CLINICAL_URL,
        {
            "referral_id": referral_id,
            "mrn": mrn,
            "diagnosis_name": diagnosis_name,
            "requested_procedure": requested_procedure,
            "drug_name": drug_name,
        },
    )
    eligibility_verdict, clinical_verdict = await asyncio.gather(eligibility_task, clinical_task)
    logger.info("verdicts collected for %s", referral_id)

    # 6. decide
    decision_line = await chat(
        DECIDE_SYSTEM,
        (
            f"Eligibility verdict: {eligibility_verdict}\n"
            f"Clinical verdict: {clinical_verdict}\n"
            f"Requested procedure: {requested_procedure}"
        ),
        max_tokens=160,
    )
    outcome = "pended"
    for candidate in ("approved", "denied", "pended"):
        if candidate in decision_line.lower():
            outcome = candidate
            break

    # 7. record — once in the authorization store, once in the audit trail
    await call_mcp_tool(
        AUTHSTORE_MCP_URL,
        "save_decision",
        {
            "referral_id": referral_id,
            "mrn": mrn,
            "outcome": outcome,
            "eligibility_verdict": eligibility_verdict,
            "clinical_verdict": clinical_verdict,
            "rationale": decision_line,
        },
    )
    await call_mcp_tool(
        AUDIT_MCP_URL,
        "record_determination",
        {
            "referral_id": referral_id,
            "patient_name": patient_name,
            "mrn": mrn,
            "policy_number": policy_number,
            "outcome": outcome,
            "rationale": decision_line,
        },
    )

    return json.dumps(
        {
            "referral_id": referral_id,
            "patient_name": patient_name,
            "mrn": mrn,
            "policy_number": policy_number,
            "requested_procedure": requested_procedure,
            "outcome": outcome,
            "eligibility_verdict": eligibility_verdict,
            "clinical_verdict": clinical_verdict,
            "rationale": decision_line,
            "provider_directory": directory,
        },
        indent=2,
    )
