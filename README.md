# ARIADNE

**Trace what changed. Understand what follows.**

ARIADNE is a local-first, revision-aware engineering impact analysis platform.
Given two revisions of an engineering drawing/project it detects what
materially changed, traces which components and dependencies may be affected,
retrieves the governing requirements with page-level provenance, computes
**deterministic** rule checks, and proposes review findings that a human must
explicitly approve.

> ARIADNE is **decision-support software**, not an autonomous compliance gate.
> It is an independent prototype inspired by modern CAD/design-data platforms
> and agentic engineering workflows. It is **not** an Autodesk product and has
> no official Autodesk integration. All engineering documents in the dataset
> are synthetic and clearly labelled; public standards appear only as
> provenance pointers whose normative text is deliberately not reproduced.

---

## What problem does it solve?

Revision review today is fragmented: compare drawings by eye, open related
documents, search standards, trace dependencies by memory, write findings by
hand. ARIADNE automates the *investigation* — detection, traversal, retrieval,
rule evaluation, evidence packaging — and keeps the engineering decision with
a qualified human.

```
Revision A ─
            ├─► align (OpenCV) ─► diff ► candidate regions
Revision B ─┘                          │
                                       ▼
                        manifest diff (ground-truth structure)
                                       ▼
                    change classification (deterministic policy)
                                       ▼
                     dependency traversal (graph, ≤ N hops)
                                       ▼
              revision-aware retrieval (standards, specs, notes)
                                       ▼
                  deterministic rule checks (limits, clearances)
                                       ▼
                    evidence-grounded insight + proposed findings
                                       ▼
                          human confirmation → MCP action
```

## Demo (2 minutes)

```bash
git clone <this repo> && cd ariadne
cp .env.example .env
make seed          # drawings + PDFs + DB + vector index + benchmark
make api           # terminal 1  → http://localhost:8000/docs
make mcp           # terminal 2  → MCP server :8765
make web           # terminal 3  → http://localhost:5173
```

1. Open **Revisions**, keep `Rev A → Rev B`, press **Analyze Revision**.
2. Watch the 9-stage progress bar; then the split drawing view shows overlaid
   change regions (red = high, blue = medium, grey = low).
3. Click the flange change: the affected-component list, deterministic checks
   (`ORN-FS-017 §4.2 FAIL, clearance 1.0 mm vs required 3.0 mm`) and evidence
   panel all update together.
4. Open **Chat**: *“Why is Motor Mount classified as high impact?”* — the
   answer cites the failing deterministic check and the governing clauses,
   with tool calls expandable beneath.
5. *“Create a review finding for the possible clearance conflict.”* — ARIADNE
   proposes, shows evidence, and **waits**. Confirm in the modal; the MCP tool
   `create_review_finding` executes and the finding appears in **Findings**,
   on the component, and in the audit trail.
6. Switch the user selector (top-right) to **Dana Okoye (VIEWER)** and try to
   run an analysis or approve a confirmation: deterministic 403/409.

## Repository structure

```
ariadne/
├── apps/
│   ├── api/                  FastAPI + SQLAlchemy + Alembic + services
│   │   ├── app/core/         config, logging, errors, security, fonts, content-security
│   │   ├── app/db/           models, session, migrations
│   │   ├── app/schemas/      pydantic contracts (changes, analysis, rag, chat…)
│   │   ├── app/services/
│   │   │   ├── rag/          embeddings, vector stores, BM25, chunking/ingestion,
│   │   │   │                 query planner, reranker, retriever
│   │   │   ├── vision/       OpenCV registration + differencing + VLM providers
│   │   │   ├── analysis/     rules engine, revision analyzer, impact, orchestrator
│   │   │   ├── llm/          provider abstraction + prompts + schemas
│   │   │   └── agent/        tool registry, gateway (authz+confirmation+transport), agent
│   │   ├── app/routes/       REST endpoints incl. /mcp-bridge
│   │   └── tests/            pytest suite (33 tests)
│   ├── web/                  React 18 + TS strict + Vite + Tailwind + React Flow
│   └── mcp-server/           TypeScript MCP server (official SDK, streamable HTTP)
├── packages/
│   ├── evaluation/           metric functions (precision/recall/F1, Recall@K, MRR, nDCG…)
│   └── shared-types/         cross-app type notes (contracts live in api schemas + web types)
├── scripts/                  generate_drawings, generate_documents, seed, generate_benchmark,
│                             mcp_probe, restart_api
├── data/                     drawings/, documents/ (PDF + layout sidecars), seed/, evaluation/
├── docs/                     architecture, rag, mcp, evaluation, decisions/
├── docker-compose.yml        postgres+pgvector, api, mcp, web, optional neo4j (profile graph)
├── Makefile                  install / seed / dev / test / eval / build
└── .env.example
```

## System design

See [`docs/architecture.md`](docs/architecture.md) (Mermaid diagrams included).
Key points:

* **Nine-stage asynchronous analysis pipeline** with persisted progress events.
* **Layered change detection**: normalisation → ORB/RANSAC registration →
  absdiff+morphology+connected components → manifest diff → cross-check →
  optional VLM interpretation.
* **VLM perception layer** (Qwen2.5-VL-7B-Instruct via any OpenAI-compatible
  vision endpoint): strict-JSON interpretation of candidate crops, cross-checked
  against structured data and CV (`AGREED / CONFLICT / UNCERTAIN`, disagreements
  surfaced in the UI). Never authoritative: rules, authz and state stay
  deterministic/server-side (`docs/vlm.md`).
* **Semantic embeddings** (default `BAAI/bge-m3`, configurable; local
  sentence-transformers or remote endpoint) with the lexical hashing embedder
  retained as offline fallback; backend reported at startup and index
  auto-rebuilt on backend change.
* **Blind revision benchmark** (24 cases, ground truth unreadable by the
  analyzer, enforced by directory/module/process contracts) with failure
  analysis (`docs/benchmark.md`). The LLM never invents a difference: structured
  values come from manifests; CV regions act as an independent second signal;
  unmapped pixel differences are reported *uninterpreted*.
* **Deterministic rules engine**: requirements carry machine-readable rules
  (`numeric_range`, `tolerance_class`, `hole_clearance`, `min_radial_clearance`,
  `relative_increase`, `enum`, …). `52 > 50` is Python, not a model.
* **Graph abstraction**: SQL BFS by default, Neo4j when configured; the active
  store is reported in every graph response.
* **Agent**: deterministic tool-selection policy (measurable) + LLM prose over
  structured outputs (live mode). The agent never mutates state.
* **MCP**: 12 tools, zod schemas mirrored by a Python parity test; mutating
  tools refuse without an approved, digest-bound, single-use confirmation.

## RAG architecture

See [`docs/rag.md`](docs/rag.md). Ingestion preserves page/section/bbox
provenance and verifies layout blocks against pypdf text. Retrieval plans
structured dimensions (component / change / relationship / normative), runs a
strategy (`keyword`, `vector`, `metadata_aware`, `revision_aware`, `hybrid`),
and reranks with a transparent weighted scorer whose weights are returned per
result. Retrieved text is untrusted data: instruction-shaped content is
quarantined.

## MCP architecture

See [`docs/mcp.md`](docs/mcp.md) and `scripts/mcp_probe.py`.

## Data model

25 tables: `projects`, `revisions`, `drawings`, `components`,
`component_revisions` (per-revision property snapshots), `dependencies`,
`documents`, `document_chunks`, `requirements`, `vector_records`,
`analysis_runs`, `analysis_events`, `changes`, `tool_executions`,
`confirmations`, `findings`, `finding_evidence`, `finding_components`,
`chat_sessions`, `chat_messages`, `audit_events`, `evaluation_runs`,
`evaluation_metrics`, `users` (+ alembic version). Migrations live in
`apps/api/app/db/migrations`.

## Evaluation

See [`docs/evaluation.md`](docs/evaluation.md). `make eval` (or
`POST /evaluation/run`) executes the pipeline over 32 generated revision pairs,
12 retrieval qrels and 14 tool cases, and persists metrics + a JSON report.

Latest measured run (offline embedder, SQLite; `GET /evaluation/runs`):

| area | metric | value | n |
|---|---|---|---|
| change detection | precision / recall / F1 | 1.000 / 1.000 / 1.000 | 80 changes |
| change detection | type accuracy | 0.925 | 80 |
| change detection | CV localization confirmation | 1.000 | 80 |
| extraction | exact / normalized | 1.000 / 1.000 | 80 |
| retrieval `keyword` (baseline A) | Recall@5 / MRR / nDCG@5 | 0.917 / 0.833 / 0.825 | 12 |
| retrieval `vector` (baseline B) | Recall@5 / MRR / nDCG@5 | 0.917 / 0.875 / 0.866 | 12 |
| retrieval `revision_aware` (proposed) | Recall@5 / MRR / nDCG@5 | **1.000** / 0.875 / **0.906** | 12 |
| agent | tool-selection accuracy | 1.000 | 14 |
| grounding | findings with evidence | 1.000 | 2 |
| grounding | unsupported-claim rate | 0.000 | 13 changes |
| system | analysis latency | ≈ 0.7–0.9 s | 1 |

**What improves?** Revision-aware retrieval wins on revision-scoped and
metadata-heavy questions because revision metadata is a first-class retrieval
dimension (the revision note of the requested revision is the authoritative
change record) and because metadata predicates keep out-of-scope chunks from
consuming rank budget. **Where does it fail?** Narrative queries needing true
semantic bridging (e.g. “impact review scope when a mating interface dimension
changes” against the offline hashing embedder) still miss; a real embedding
model is the expected fix. The change-detection P/R of 1.0 measures pipeline +
CV agreement against construction-generated ground truth, not an independently
trained detector — see the caveats section of `docs/evaluation.md`.

## Security

* Server-side RBAC (VIEWER/ENGINEER/REVIEWER/ADMIN) enforced in FastAPI
  dependencies, the tool gateway and MCP tools; the LLM is never consulted.
* State changes require an approved confirmation bound to the exact arguments
  by SHA-256 digest; confirmations are single-use.
* Documents are untrusted input: prompt-injection patterns are detected and
  quarantined; untrusted authorities are excluded from evidence synthesis.
* Parameterised queries, Pydantic/zod validation, typed errors without stack
  traces, structured JSON logs, no secrets in source.

## Design decisions

`docs/decisions/` — ADR-0001 deterministic-first, ADR-0002 SQLite-first with
pgvector/Neo4j behind abstractions, ADR-0003 confirmation gate with digest
binding, ADR-0004 deterministic tool policy + LLM prose.

## Local setup

```bash
cp .env.example .env
make install      # pip + npm installs
make seed         # synthetic dataset + DB + index + benchmark
make dev          # API on :8000 (see Makefile for mcp/web terminals)
# or, with infrastructure:
docker compose up --build          # postgres+pgvector, api, mcp, web
docker compose --profile graph up  # + neo4j
```

Fresh-clone path that CI exercises:
`make seed && make test && make eval && make build`.

## Environment variables

See [`.env.example`](.env.example) — the authoritative list. Highlights:

| variable | default | meaning |
|---|---|---|
| `DEMO_MODE` | `1` | deterministic providers; UI badges “demo analysis” |
| `DATABASE_URL` | sqlite file | PostgreSQL DSN switches pgvector on (`VECTOR_STORE=auto`) |
| `VECTOR_STORE` / `GRAPH_STORE` | `auto` | `numpy|pgvector` / `sql|neo4j` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | any OpenAI-compatible chat endpoint |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | — | any OpenAI-compatible embeddings endpoint |
| `VISION_ENABLED` / `VISION_MODEL` | `0` | VLM interpretation of candidate regions |
| `MCP_ENABLED` / `MCP_SERVER_URL` | `1` / `http://localhost:8765/mcp` | MCP transport for tool execution |
| `RAG_TOP_K` / `RAG_RERANK_TOP_N` | `8` / `5` | retrieval tuning |
| `GRAPH_DEFAULT_DEPTH` / `GRAPH_MAX_DEPTH` | `2` / `4` | traversal bounds |

## Testing

```bash
make eval-blind    # blind benchmark: CV-only vs CV+VLM + failure analysis
make eval-rag      # retrieval baselines A–E (+graph arm)
make eval-vlm      # VLM arm (labels not-run without an endpoint)
make test          # pytest (api) + vitest (web) + vitest (mcp)
cd apps/api && python -m pytest -q          # 33 tests
cd apps/web && npx vitest run               # component tests
cd apps/mcp-server && npx vitest run        # registry parity/contract tests
python scripts/mcp_probe.py                 # live MCP client probe
cd apps/web && npx playwright test          # e2e (requires browsers + stack up)
```

Coverage highlights: rule engine arithmetic, graph traversal/depth, RBAC
matrix, confirmation approve/reject/tamper flows, RAG provenance + quarantine
+ revision-scoped ordering, full pipeline over seeded drawings, MCP registry
parity, metric functions.

## Future work

* Neural cross-encoder reranker and a real multimodal embedder behind the
  existing protocols; LoRA-fine-tuned Qwen2.5-VL for region interpretation.
* True CAD kernel input (STEP/Revit via APS-style adapters) instead of
  rendered drawings + manifests.
* Incremental vector indexing (HNSW) and chunk-level citation heatmaps.
* Multi-user sessions with OIDC instead of the demo identity header.
* Playwright e2e in CI with recorded HAR fixtures.

## Research questions

*Can revision-aware multimodal retrieval combined with dependency traversal
and MCP tool use improve evidence-grounded engineering change analysis?*
Implemented and measured: strategy comparison, tool-selection accuracy,
grounding rates. Hypothesized (not yet measured): that the same architecture
with a semantic embedder closes the remaining narrative-query gap, and that
reviewer time-to-decision drops versus manual comparison — both require a user
study.

## Use cases

* Revision impact review in mechanical/electrical design teams.
* Onboarding: “what actually changed between these releases, and why does it
  matter?” with citations.
* QA/regression: deterministic rule checks as regression gates over drawing
  parameters.
* Platform engineering: a reference implementation of guarded MCP actions with
  human confirmation and full audit.

## Limitations

* Synthetic dataset: geometry, documents and rules are fictional by design;
  conclusions about real standards require licensed sources and qualified
  reviewers.
* Change detection scores against construction-generated ground truth (see
  evaluation caveats); the CV stage is the independent signal.
* Offline embeddings are lexical; semantic retrieval quality depends on
  configuring a real embedding model.
* The Python MCP client path can fall back to in-process execution in some
  environments (recorded as `in-process-fallback`); the MCP server itself is
  verified by `scripts/mcp_probe.py`.
* Single-node prototype: no clustering, no HNSW, no Kubernetes — deliberately.
* The VLM arm of the blind benchmark is **not measured** in environments
  without a vision endpoint; reports carry `not_run_no_vlm_endpoint` and no VLM
  accuracy claim is made anywhere.
* Semantic retrieval was measured in the sandbox with
  `all-MiniLM-L6-v2` (1 GB RAM budget); the configured default `BAAI/bge-m3`
  requires more memory. Reports name the model actually loaded.
* Headless Chromium in memory-constrained sandboxes can fail with
  `V8 process OOM (Failed to reserve virtual memory for CodeRange)`; launch with
  `--js-flags=--jitless` there (the Playwright config and CI are unaffected).

## License

See `LICENSE`.
