# Prior Authorization — a multi-agent example

A referral arrives as a clinical note. The system identifies the patient, checks
their coverage, reviews the clinical facts, decides, and files the decision.

That is the whole story. It takes seven services to tell it, because that is
roughly how many a real one takes.

> **All patient data in this example is synthetic.** Names, MRNs, dates of
> birth, addresses, phone numbers, policy numbers, NPIs and prescription numbers
> are invented. They are shaped like real records on purpose — an example that
> moves obviously-fake data does not exercise the things that matter.

## The cast

| service | kind | what it does |
|---|---|---|
| **priorauth-intake** | agent | the only entry point. Extracts the referral's facts, files it, asks both reviewers at once, decides, records the outcome |
| **priorauth-eligibility** | agent | reads the member's policy, decides whether the plan covers the request |
| **priorauth-clinical** | agent | reads the patient's history and the code definitions, decides whether the request is justified |
| **priorauth-records-tool** | MCP | **read-only** access to members, policies and clinical history |
| **priorauth-authstore-tool** | MCP | **write-only** persistence of referrals and decisions |
| **priorauth-coding-tool** | MCP | ICD-10 / CPT / drug reference lookups. Never sees a patient identifier |
| **priorauth-audit-tool** | MCP | appends each determination to a shared file and to Redis |

Three datastores sit behind them: `priorauth-records-db` (Postgres, read from),
`priorauth-auth-db` (Postgres, written to) and `priorauth-audit-redis`. The two
Postgres instances are deliberately separate servers — no component in this
example both reads and writes patient data.

## The flow of one referral

```
        clinic
          │  A2A message/send: the referral note
          ▼
   ┌─────────────────┐
   │ priorauth-intake│──① extract ─────────────────────────► LLM
   │                 │──② get_member ────► records-tool ──► records-db
   │                 │──③ save_referral ─► authstore-tool ► auth-db
   │                 │──④ verify provider ───────────────► external directory
   │                 │                                      (http and https)
   │                 │──⑤ ask both reviewers, concurrently:
   │                 │        ├──────────────► priorauth-eligibility
   │                 │        │                   └─ get_policy ─► records-tool
   │                 │        │                   └─ judge ──────► LLM
   │                 │        └──────────────► priorauth-clinical
   │                 │                            └─ get_clinical_history ─► records-tool
   │                 │                            └─ lookup_procedure_code ─► coding-tool
   │                 │                            └─ lookup_drug ───────────► coding-tool
   │                 │                            └─ recommend ────────────► LLM
   │                 │──⑥ decide ──────────────────────────► LLM
   │                 │──⑦ save_decision ─► authstore-tool ─► auth-db
   │                 │──⑧ record ────────► audit-tool ─────► file + redis
   └─────────────────┘
          │  the determination
          ▼
        clinic
```

Step ⑤ is the interesting one: the two reviewers run at the same time, and both
call the records service, so the records service handles two requests from two
different callers that belong to the same referral.

## Build

Each service is its own image. From the repository root:

```sh
for svc in a2a/priorauth_intake a2a/priorauth_eligibility a2a/priorauth_clinical \
           mcp/priorauth_records_tool mcp/priorauth_authstore_tool \
           mcp/priorauth_coding_tool mcp/priorauth_audit_tool; do
  name=$(basename "$svc")
  podman build -t "docker.io/library/${name}:latest" "$svc"
done
```

On a Kind cluster, load them:

```sh
for svc in priorauth_intake priorauth_eligibility priorauth_clinical \
           priorauth_records_tool priorauth_authstore_tool \
           priorauth_coding_tool priorauth_audit_tool; do
  podman save "docker.io/library/${svc}:latest" -o "/tmp/${svc}.tar"
  KIND_EXPERIMENTAL_PROVIDER=podman kind load image-archive "/tmp/${svc}.tar" --name rossoctl
done
```

## Deploy

The two databases are seeded from SQL held beside the tool that owns them:

```sh
kubectl create configmap priorauth-records-initdb -n team2 \
  --from-file=initdb.sql=mcp/priorauth_records_tool/deployment/initdb.sql
kubectl create configmap priorauth-auth-initdb -n team2 \
  --from-file=initdb.sql=mcp/priorauth_authstore_tool/deployment/initdb.sql
```

Then apply the services. Datastores and tools first, so an agent's dependencies
resolve before it starts:

```sh
kubectl apply -f mcp/priorauth_records_tool/deployment/k8s.yaml
kubectl apply -f mcp/priorauth_authstore_tool/deployment/k8s.yaml
kubectl apply -f mcp/priorauth_coding_tool/deployment/k8s.yaml
kubectl apply -f mcp/priorauth_audit_tool/deployment/k8s.yaml
kubectl apply -f a2a/priorauth_eligibility/deployment/k8s.yaml
kubectl apply -f a2a/priorauth_clinical/deployment/k8s.yaml
kubectl apply -f a2a/priorauth_intake/deployment/k8s.yaml
```

Each manifest carries a `Deployment`, a `Service` and an `AgentRuntime`. The
`AgentRuntime` is how the platform adopts the workload — it applies the
`rossoctl.io/type` label and injects the AuthBridge sidecar. Do not set that
label by hand; a `ValidatingAdmissionPolicy` reserves it for the operator and
will reject the manifest.

## Drive it

`samples/referrals.json` holds six referral notes, one per member in the seed
data, each written the way a clinic would write it. `demo.sh` sends one:

```sh
./a2a/priorauth_intake/demo.sh 0          # first referral
./a2a/priorauth_intake/demo.sh 3          # fourth referral
```

## Configuration

| variable | default | applies to |
|---|---|---|
| `LLM_API_BASE` | `http://host.containers.internal:11434/v1` | all three agents |
| `LLM_MODEL` | `qwen2.5:7b` | all three agents |
| `RECORDS_MCP_URL` | `http://priorauth-records-tool:8000/mcp` | intake, eligibility, clinical |
| `CODING_MCP_URL` | `http://priorauth-coding-tool:8000/mcp` | clinical |
| `AUTHSTORE_MCP_URL` | `http://priorauth-authstore-tool:8000/mcp` | intake |
| `AUDIT_MCP_URL` | `http://priorauth-audit-tool:8000/mcp` | intake |
| `ELIGIBILITY_URL` / `CLINICAL_URL` | the two reviewers' services | intake |
| `DIRECTORY_HTTP_URL` / `DIRECTORY_HTTPS_URL` | `httpbingo.org` | intake |
| `RECORDS_DATABASE_URL` | the records Postgres | records tool |
| `AUTHSTORE_DATABASE_URL` | the authorizations Postgres | authstore tool |
| `AUDIT_DIR` / `REDIS_URL` | `/audit`, the audit Redis | audit tool |

## Notes

- The model is asked for JSON at two points. Small models sometimes wrap it in
  prose or a code fence, so the intake agent recovers the object rather than
  failing the referral — but a model that cannot follow the instruction at all
  will produce empty fields, and the determination will pend.
- No `uv.lock` is committed for this example; dependencies resolve at build time.
- The services are not instrumented. They speak A2A, MCP and HTTP and nothing
  else; there is no tracing code in them.
