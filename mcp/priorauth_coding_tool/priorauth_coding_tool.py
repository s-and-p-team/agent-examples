"""Medical Coding MCP tool — the reference-data side of the prior-authorization demo.

Pure lookup: no database, no network, no personal data in and none out. It maps
free-text diagnoses and procedures onto ICD-10 and CPT codes, reports whether a
procedure normally requires prior authorization, and returns a drug's class and
typical dosing range.

A real coding service is exactly this — a maintained reference table — so the
table is baked into the image rather than faked. It is a small excerpt of the
real code sets, sufficient for the demo's clinical scenarios.
"""

import json
import logging
import os
import sys

from fastmcp import FastMCP

mcp = FastMCP("MedicalCoding")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- reference tables -------------------------------------------------------
# Excerpts of the published code sets. Keys are lowercased for matching.

ICD10 = {
    "rheumatoid arthritis": ("M06.9", "Rheumatoid arthritis, unspecified"),
    "hypertension": ("I10", "Essential (primary) hypertension"),
    "heart failure": ("I50.22", "Chronic systolic (congestive) heart failure"),
    "chronic kidney disease": ("N18.3", "Chronic kidney disease, stage 3 (moderate)"),
    "migraine": ("G43.019", "Migraine without aura, intractable"),
    "meniscus tear": ("S83.241A", "Other tear of medial meniscus, current injury, right knee"),
    "breast cancer": ("C50.411", "Malignant neoplasm of upper-outer quadrant of right breast"),
    "type 1 diabetes": ("E10.9", "Type 1 diabetes mellitus without complications"),
    "psoriasis": ("L40.0", "Psoriasis vulgaris"),
    "crohn disease": ("K50.90", "Crohn's disease, unspecified, without complications"),
}

CPT = {
    "mri knee": ("73721", "MRI, lower extremity joint, without contrast", True),
    "mri brain": ("70553", "MRI, brain, without and with contrast", True),
    "knee arthroscopy": ("29881", "Arthroscopy, knee, surgical, with meniscectomy", True),
    "echocardiogram": ("93306", "Transthoracic echocardiography, complete", False),
    "transesophageal echo": ("93312", "Transesophageal echocardiography", True),
    "infusion therapy": ("96413", "Chemotherapy administration, intravenous infusion", True),
    "biologic injection": ("96372", "Therapeutic injection, subcutaneous or intramuscular", False),
    "colonoscopy": ("45378", "Colonoscopy, flexible, diagnostic", False),
    "ct angiography": ("0554T", "CT angiography, investigational bundle", True),
}

DRUGS = {
    "methotrexate": ("antimetabolite / DMARD", "7.5-25 mg weekly", True),
    "adalimumab": ("TNF inhibitor / biologic", "40 mg every 2 weeks", True),
    "infliximab": ("TNF inhibitor / biologic", "3-5 mg/kg at weeks 0, 2, 6 then every 8 weeks", True),
    "lisinopril": ("ACE inhibitor", "5-40 mg once daily", False),
    "furosemide": ("loop diuretic", "20-80 mg once or twice daily", False),
    "carvedilol": ("beta blocker", "3.125-25 mg twice daily", False),
    "sumatriptan": ("triptan", "25-100 mg as needed", False),
    "anastrozole": ("aromatase inhibitor", "1 mg once daily", True),
    "insulin glargine": ("long-acting insulin", "individualised, units at bedtime", False),
    "ibuprofen": ("NSAID", "200-800 mg three times daily", False),
}


def _match(table: dict, term: str):
    """Exact key match, then substring either way — a real coding service does
    fuzzier matching, but the failure has to be visible, not silently wrong."""
    key = (term or "").strip().lower()
    if not key:
        return None
    if key in table:
        return table[key]
    for candidate, value in table.items():
        if candidate in key or key in candidate:
            return value
    return None


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def lookup_diagnosis_code(diagnosis: str) -> str:
    """Map a free-text diagnosis onto its ICD-10 code and official description."""
    hit = _match(ICD10, diagnosis)
    logger.info("lookup_diagnosis_code %r -> %s", diagnosis, hit[0] if hit else "no match")
    if not hit:
        return json.dumps({"found": False, "query": diagnosis})
    return json.dumps({"found": True, "query": diagnosis, "icd10_code": hit[0], "description": hit[1]})


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def lookup_procedure_code(procedure: str) -> str:
    """Map a free-text procedure onto its CPT code, and report whether that
    procedure normally requires prior authorization."""
    hit = _match(CPT, procedure)
    logger.info("lookup_procedure_code %r -> %s", procedure, hit[0] if hit else "no match")
    if not hit:
        return json.dumps({"found": False, "query": procedure})
    return json.dumps(
        {
            "found": True,
            "query": procedure,
            "procedure_code": hit[0],
            "description": hit[1],
            "prior_auth_typically_required": hit[2],
        }
    )


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def lookup_drug(drug_name: str) -> str:
    """Return a drug's therapeutic class, typical dosing range, and whether it
    is normally subject to prior authorization."""
    hit = _match(DRUGS, drug_name)
    logger.info("lookup_drug %r -> %s", drug_name, "hit" if hit else "no match")
    if not hit:
        return json.dumps({"found": False, "query": drug_name})
    return json.dumps(
        {
            "found": True,
            "query": drug_name,
            "drug_class": hit[0],
            "typical_dose": hit[1],
            "prior_auth_typically_required": hit[2],
        }
    )


def run() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info("MedicalCoding MCP server on %s:%d", host, port)
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    run()
