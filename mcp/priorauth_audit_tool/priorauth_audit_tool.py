"""Audit Trail MCP tool — the archival side of the prior-authorization demo.

Every determination is written twice, to two stores that are deliberately not
databases-of-record:

* an append-only **JSON Lines file** on a shared volume, which is what a
  compliance team actually asks for; and
* a **Redis** key, which is what the operations dashboard reads.

The audit record carries the patient's name, MRN and policy number alongside the
outcome, because an audit trail that cannot identify the subject of the decision
is not an audit trail.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import redis
from fastmcp import FastMCP

mcp = FastMCP("AuditTrail")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

AUDIT_DIR = os.getenv("AUDIT_DIR", "/audit")
AUDIT_FILE = os.path.join(AUDIT_DIR, "determinations.jsonl")
REDIS_URL = os.getenv("REDIS_URL", "redis://priorauth-audit-redis:6379")
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "86400"))


def _redis():
    return redis.Redis.from_url(REDIS_URL, socket_connect_timeout=5)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def record_determination(
    referral_id: str,
    patient_name: str,
    mrn: str,
    policy_number: str,
    outcome: str,
    rationale: str,
) -> str:
    """Append a determination to the audit trail.

    Writes the same record to the shared audit file and to Redis, and reports
    what each store accepted.
    """
    record = {
        "referral_id": referral_id,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "patient_name": patient_name,
        "mrn": mrn,
        "policy_number": policy_number,
        "outcome": outcome,
        "rationale": rationale,
    }
    line = json.dumps(record, sort_keys=True)

    Path(AUDIT_DIR).mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    key = f"determination:{referral_id}"
    client = _redis()
    client.set(key, line, ex=REDIS_TTL_SECONDS)

    logger.info("record_determination %s outcome=%s -> file+redis", referral_id, outcome)
    return json.dumps(
        {
            "recorded": True,
            "referral_id": referral_id,
            "file": AUDIT_FILE,
            "redis_key": key,
            "bytes": len(line),
        }
    )


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def count_determinations() -> str:
    """How many determinations the audit file currently holds. Used by
    operators to sanity-check that the trail is being written."""
    path = Path(AUDIT_FILE)
    count = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    return json.dumps({"file": AUDIT_FILE, "records": count})


def run() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info("AuditTrail MCP server on %s:%d (file=%s redis=%s)", host, port, AUDIT_FILE, REDIS_URL)
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    run()
