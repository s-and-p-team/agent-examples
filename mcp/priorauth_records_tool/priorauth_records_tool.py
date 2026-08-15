"""Patient Records MCP tool — the READ-ONLY side of the prior-authorization demo.

Serves member demographics, coverage policies and clinical history out of the
`records` Postgres database. Every tool here is a read; nothing in this server
writes. The write side is a separate server (`priorauth_authstore_tool`) backed
by a separate database, so a reader and a writer are never the same component.

All data is SYNTHETIC. It is shaped to look like real patient data — names,
MRNs, dates of birth, addresses, phone numbers, insurance policy numbers,
diagnoses, drugs and lab results — because the point of the demo is to move
realistic personal data through a realistic system.
"""

import json
import logging
import os
import sys

import psycopg
from fastmcp import FastMCP
from psycopg.rows import dict_row

mcp = FastMCP("PatientRecords")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "RECORDS_DATABASE_URL",
    "postgresql://records:records@priorauth-records-db:5432/records",
)


def _query(sql: str, params: tuple) -> list[dict]:
    """One short-lived connection per call. A pool would be better in
    production; this keeps the demo's failure modes obvious."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def get_member(mrn: str) -> str:
    """Look up a member by Medical Record Number.

    Returns demographics and the active insurance policy: full name, date of
    birth, address, phone, email, policy number and coverage tier.
    """
    rows = _query(
        """
        SELECT mrn, full_name, date_of_birth, gender, address, phone, email,
               policy_number, coverage_tier, plan_name
          FROM members
         WHERE mrn = %s
        """,
        (mrn,),
    )
    if not rows:
        return json.dumps({"found": False, "mrn": mrn})
    member = rows[0]
    member["date_of_birth"] = str(member["date_of_birth"])
    logger.info("get_member mrn=%s -> found", mrn)
    return json.dumps({"found": True, "member": member}, default=str)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def get_policy(policy_number: str) -> str:
    """Look up an insurance policy's coverage rules.

    Returns the plan name, coverage tier, annual deductible, whether prior
    authorization is required, and the list of excluded procedure codes.
    """
    rows = _query(
        """
        SELECT policy_number, plan_name, coverage_tier, annual_deductible_usd,
               prior_auth_required, excluded_procedure_codes, effective_from, effective_to
          FROM policies
         WHERE policy_number = %s
        """,
        (policy_number,),
    )
    if not rows:
        return json.dumps({"found": False, "policy_number": policy_number})
    policy = rows[0]
    logger.info("get_policy policy=%s -> found", policy_number)
    return json.dumps({"found": True, "policy": policy}, default=str)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def get_clinical_history(mrn: str) -> str:
    """Return the member's recent clinical history.

    Encounters (date, department, diagnosis and ICD-10 code), current
    medications with doses, and recent lab results with values and units.
    """
    encounters = _query(
        """
        SELECT encounter_date, department, hospital_name, diagnosis_name,
               icd10_code, attending_provider_npi
          FROM encounters
         WHERE mrn = %s
         ORDER BY encounter_date DESC
         LIMIT 10
        """,
        (mrn,),
    )
    medications = _query(
        """
        SELECT drug_name, dose, frequency, started_on, prescription_number
          FROM medications
         WHERE mrn = %s AND active
        """,
        (mrn,),
    )
    labs = _query(
        """
        SELECT test_name, result_value, unit, collected_on, interpretation
          FROM lab_results
         WHERE mrn = %s
         ORDER BY collected_on DESC
         LIMIT 10
        """,
        (mrn,),
    )
    logger.info(
        "get_clinical_history mrn=%s -> %d encounters, %d meds, %d labs",
        mrn,
        len(encounters),
        len(medications),
        len(labs),
    )
    return json.dumps(
        {
            "mrn": mrn,
            "encounters": encounters,
            "medications": medications,
            "lab_results": labs,
        },
        default=str,
    )


def run() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info(
        "PatientRecords MCP server on %s:%d (db=%s)",
        host,
        port,
        DATABASE_URL.split("@")[-1],
    )
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    run()
