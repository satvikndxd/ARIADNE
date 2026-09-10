# ADR-0001 — Deterministic first, LLM second

**Status:** accepted.

**Context.** Engineering review tooling cannot tolerate invented measurements
or citations, and LLMs hallucinate under exactly those pressures.

**Decision.** Every numeric comparison, authorization decision, graph
traversal, revision metadata lookup and rule evaluation is plain Python. The
LLM is used only for (a) semantic interpretation of visual candidates when a
vision provider is configured and (b) composing grounded prose from structured
tool outputs. Deterministic check results are passed to the LLM as
*authoritative inputs*, never recomputed by it.

**Consequences.** + auditable, testable core; + DEMO_MODE works fully offline;
− prose quality depends on provider; − rule coverage must be authored
(machine-readable rules live in requirement metadata).
