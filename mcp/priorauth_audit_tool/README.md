# Audit Trail

A MCP tool in the **prior authorization** example. The scenario, the full topology
and the build/deploy instructions live in the example's main README:
[Prior Authorization](../../a2a/priorauth_intake/README.md).

Appends each determination to two stores that are not databases-of-record: a JSON Lines file on a shared volume, and a Redis key.

| tool | does |
|---|---|
| `record_determination(...)` | appends the record to both stores |
| `count_determinations()` | how many records the file holds |

The record carries the patient's name, MRN and policy number alongside the outcome — an audit trail that cannot identify the subject of a decision is not an audit trail.

All patient data in this example is synthetic.
