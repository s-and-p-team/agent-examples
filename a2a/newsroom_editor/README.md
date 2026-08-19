# The Newsroom — a text-transformation chain example

An article arrives from the wire. The newsroom decides the angle, summarizes
it, titles the summary, pulls a quote, indexes it, and composes the front-page
brief. Every step takes text and produces new text derived from it — the point
of this example is that one turn's lineage graph shows a *chain of
derivations*, not just a fan-out:

```
article ──► summary ──► title
   │            └─────► keywords
   └──────► quote (verbatim, substring-checked)
                          all four ──► brief
```

Where the prior-authorization example is wide (seven services, two reviewers in
parallel), the newsroom is **deep**: the editor delegates to the summarizer,
and the summarizer delegates to the titler on its own — three agents in a
chain, with the payload transformed at each hop.

> The sample articles are invented. Places, institutions and people in them do
> not exist.

## The cast

| service | kind | what it does |
|---|---|---|
| **newsroom-editor** | agent | the only entry point. Decides the angle, assigns both desks at once, indexes, composes the brief, files it, announces it |
| **newsroom-summarizer** | agent | condenses the article to the angle, files the summary, delegates the headline onward |
| **newsroom-titler** | agent | writes a headline from the summary alone — it never sees the article |
| **newsroom-quoter** | agent | picks one verbatim sentence, verifies it really is a substring, files it |
| **newsroom-archive-tool** | MCP | in-memory artifact store. All four agents write to it; no database behind it |

## The flow of one article

```
        wire service
          │  A2A message/send: the raw article
          ▼
   ┌─────────────────┐
   │ newsroom-editor │──① angle ────────────────────────────► LLM
   │                 │──② assign both desks, concurrently:
   │                 │      ├────► newsroom-summarizer
   │                 │      │        └─ summarize ──────────► LLM
   │                 │      │        └─ save_artifact ──────► archive-tool
   │                 │      │        └─ delegate ───────────► newsroom-titler
   │                 │      │                └─ headline ───► LLM
   │                 │      │                └─ save_artifact ► archive-tool
   │                 │      └────► newsroom-quoter
   │                 │               └─ pick quote ─────────► LLM
   │                 │               └─ save_artifact ──────► archive-tool
   │                 │──③ keywords (from the summary) ──────► LLM
   │                 │──④ compose the brief ────────────────► LLM
   │                 │──⑤ save_artifact ×2 ─────────────────► archive-tool
   │                 │──⑥ syndicate ────────────────────────► external wire
   │                 │                                        (http and https)
   └─────────────────┘
          │  the front-page brief
          ▼
        wire service
```

Two shapes worth noticing:

- **The chain.** The editor never talks to the titler. The headline exists
  because the summarizer delegated on its own, and it derives from the summary,
  which derives from the article — a derivation of a derivation, three agents
  deep.
- **The fan-in.** Both desks' subtrees are open at the same time and both write
  to the same archive tool, which then also receives the editor's own two
  writes — five `save_artifact` calls on one story from four different callers.

The quoter is the checkable link: its output must be a literal substring of its
input, the code verifies it, and the result says whether the check passed.

## Build

Each service is its own image. From the repository root:

```sh
for svc in a2a/newsroom_editor a2a/newsroom_summarizer a2a/newsroom_titler \
           a2a/newsroom_quoter mcp/newsroom_archive_tool; do
  name=$(basename "$svc")
  podman build -t "docker.io/library/${name}:latest" "$svc"
done
```

On a Kind cluster, load them:

```sh
for svc in newsroom_editor newsroom_summarizer newsroom_titler \
           newsroom_quoter newsroom_archive_tool; do
  podman save "docker.io/library/${svc}:latest" -o "/tmp/${svc}.tar"
  KIND_EXPERIMENTAL_PROVIDER=podman kind load image-archive "/tmp/${svc}.tar" --name rossoctl
done
```

## Deploy

No databases to seed — the archive is in-memory. Tool first, then the agents
from the bottom of the chain up, so a caller's dependencies resolve before it
starts:

```sh
kubectl apply -f mcp/newsroom_archive_tool/deployment/k8s.yaml
kubectl apply -f a2a/newsroom_titler/deployment/k8s.yaml
kubectl apply -f a2a/newsroom_quoter/deployment/k8s.yaml
kubectl apply -f a2a/newsroom_summarizer/deployment/k8s.yaml
kubectl apply -f a2a/newsroom_editor/deployment/k8s.yaml
```

Each manifest carries a `Deployment`, a `Service` and an `AgentRuntime`. The
`AgentRuntime` is how the platform adopts the workload — it applies the
`rossoctl.io/type` label and injects the AuthBridge sidecar. Do not set that
label by hand; a `ValidatingAdmissionPolicy` reserves it for the operator and
will reject the manifest.

## Drive it

`samples/articles.json` holds three wire articles. `demo.sh` sends one:

```sh
./a2a/newsroom_editor/demo.sh 0          # the desalination plant
./a2a/newsroom_editor/demo.sh 1          # the quantum milestone
./a2a/newsroom_editor/demo.sh 2          # the bakery cooperative
```

## Configuration

| variable | default | applies to |
|---|---|---|
| `LLM_API_BASE` | `http://host.containers.internal:11434/v1` | all four agents |
| `LLM_MODEL` | `qwen2.5:7b` | all four agents |
| `ARCHIVE_MCP_URL` | `http://newsroom-archive-tool:8000/mcp` | all four agents |
| `SUMMARIZER_URL` / `QUOTER_URL` | the two desks' services | editor |
| `TITLER_URL` | the headline desk's service | summarizer |
| `SYNDICATION_HTTP_URL` / `SYNDICATION_HTTPS_URL` | `httpbingo.org` | editor |

## Notes

- The archive is in-memory on purpose: it restarts clean and needs no seed
  data. Read a story back with the archive tool's `get_story`.
- No `uv.lock` is committed for this example; dependencies resolve at build time.
- The services are not instrumented. They speak A2A, MCP and HTTP and nothing
  else; there is no tracing code in them.
