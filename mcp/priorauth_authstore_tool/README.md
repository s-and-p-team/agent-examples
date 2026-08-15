# Authorization Store

A MCP tool in the **prior authorization** example. The scenario, the full topology
and the build/deploy instructions live in the example's main README:
[Prior Authorization](../../a2a/priorauth_intake/README.md).

Write-only persistence for referrals and determinations.

| tool | writes |
|---|---|
| `save_referral(...)` | a new referral row, returning its generated `referral_id` |
| `save_decision(...)` | the determination for a referral |

Its database is a different Postgres instance from the records database, so no component in the example both reads and writes patient data. Schema in `deployment/initdb.sql`.

All patient data in this example is synthetic.
