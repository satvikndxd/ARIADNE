# ADR-0004 — Deterministic tool-selection policy, LLM for prose

**Status:** accepted.

**Context.** Tool-selection accuracy is an acceptance criterion; free-form
LLM function-calling loops are hard to measure and fail offline.

**Decision.** Intent classification + tool planning are deterministic rules
over the request and project context (`services/agent/agent.py`). The LLM
(live mode) composes the final answer from structured tool outputs and must
return citations; citations not present in the retrieved evidence are dropped.
In DEMO_MODE answers are templates over the same structured outputs, labelled
`mode: demo`.

**Consequences.** + measurable tool selection (see evaluation); + full offline
functionality; − policy must be extended for new intents (pattern table).
