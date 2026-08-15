"""Authorization Store MCP tool — the WRITE-ONLY side of the prior-authorization demo.

Persists incoming referrals and the decisions made about them into the
`authorizations` Postgres database. Nothing here reads back: reads are served by
a separate server (`priorauth_records_tool`) against a separate database, so the
system never has one component that both reads and writes patient data.

The rows written here carry personal data by design — the referral row stores
the patient's name, MRN, date of birth and policy number alongside the clinical
detail, because that is what a real prior-authorization record contains.
"""

import json
import logging
import os
import sys
import uuid

import psycopg
from fastmcp import FastMCP
from psycopg.rows import dict_row

mcp = FastMCP("AuthorizationStore")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "AUTHSTORE_DATABASE_URL",
    "postgresql://authorizations:authorizations@priorauth-auth-db:5432/authorizations",
)


def _execute(sql: str, params: tuple) -> dict | None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone() if cur.description else None
        conn.commit()
    return dict(row) if row else None


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def save_referral(
    patient_name: str,
    mrn: str,
    date_of_birth: str,
    policy_number: str,
    diagnosis_name: str,
    icd10_code: str,
    requested_procedure: str,
    procedure_code: str,
    requesting_provider_npi: str,
    clinical_note: str,
) -> str:
    """Persist an incoming prior-authorization referral.

    Returns the generated referral id, which every later step quotes.
    """
    referral_id = f"PA-{uuid.uuid4().hex[:10].upper()}"
    _execute(
        """
        INSERT INTO referrals (referral_id, patient_name, mrn, date_of_birth,
                               policy_number, diagnosis_name, icd10_code,
                               requested_procedure, procedure_code,
                               requesting_provider_npi, clinical_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            referral_id,
            patient_name,
            mrn,
            date_of_birth or None,
            policy_number,
            diagnosis_name,
            icd10_code,
            requested_procedure,
            procedure_code,
            requesting_provider_npi,
            clinical_note,
        ),
    )
    logger.info("save_referral %s mrn=%s procedure=%s", referral_id, mrn, procedure_code)
    return json.dumps({"saved": True, "referral_id": referral_id})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def save_decision(
    referral_id: str,
    mrn: str,
    outcome: str,
    eligibility_verdict: str,
    clinical_verdict: str,
    rationale: str,
) -> str:
    """Persist the final determination for a referral.

    `outcome` is one of approved / denied / pended.
    """
    _execute(
        """
        INSERT INTO decisions (referral_id, mrn, outcome, eligibility_verdict,
                               clinical_verdict, rationale)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (referral_id, mrn, outcome, eligibility_verdict, clinical_verdict, rationale),
    )
    logger.info("save_decision %s outcome=%s", referral_id, outcome)
    return json.dumps({"saved": True, "referral_id": referral_id, "outcome": outcome})


def run() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info(
        "AuthorizationStore MCP server on %s:%d (db=%s)",
        host,
        port,
        DATABASE_URL.split("@")[-1],
    )
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    run()
