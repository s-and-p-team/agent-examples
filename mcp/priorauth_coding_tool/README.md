# Medical Coding

A MCP tool in the **prior authorization** example. The scenario, the full topology
and the build/deploy instructions live in the example's main README:
[Prior Authorization](../../a2a/priorauth_intake/README.md).

Reference lookups over an excerpt of the published code sets. No database, no network, and no patient identifier ever reaches it.

| tool | returns |
|---|---|
| `lookup_diagnosis_code(diagnosis)` | ICD-10 code and official description |
| `lookup_procedure_code(procedure)` | CPT code, description, whether prior auth is typical |
| `lookup_drug(drug_name)` | therapeutic class, typical dose, whether prior auth is typical |

All patient data in this example is synthetic.
