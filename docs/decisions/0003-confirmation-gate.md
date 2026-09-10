# ADR-0003 — Human confirmation as a server-side gate with digest binding

**Status:** accepted.

**Context.** The product must never auto-create engineering findings, and the
LLM must never be the security layer.

**Decision.** Mutating MCP tools require a `Confirmation` row: status
`approved`, single-use, and a SHA-256 digest binding the approved payload to
the executed arguments (tamper guard). The agent may only *propose*; the UI
shows a confirmation modal with evidence; the decision endpoint executes the
tool through the same gateway as everything else and records the transport.

**Consequences.** + no silent mutations, replay/tamper resistance; + audit
trail answers "who approved what"; − one extra round-trip per write (by design).
