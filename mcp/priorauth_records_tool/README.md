# Patient Records

A MCP tool in the **prior authorization** example. The scenario, the full topology
and the build/deploy instructions live in the example's main README:
[Prior Authorization](../../a2a/priorauth_intake/README.md).

Read-only access to the records database.

| tool | returns |
|---|---|
| `get_member(mrn)` | demographics and the active policy |
| `get_policy(policy_number)` | coverage tier, deductible, exclusions, whether prior auth is required |
| `get_clinical_history(mrn)` | recent encounters, active medications, recent labs |

The database is seeded from `deployment/initdb.sql` — six synthetic members with histories. Nothing in this server writes.

All patient data in this example is synthetic.
