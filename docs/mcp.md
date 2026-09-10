# MCP architecture

`apps/mcp-server` is a real Model Context Protocol server (official TypeScript
SDK, streamable HTTP at `:8765/mcp`, health at `:8765/health`).

## Tools (12)
`get_project`, `get_revision`, `compare_revisions`, `get_component`,
`get_component_properties`, `get_dependencies`, `search_requirements`,
`get_requirement`, `get_revision_history`, `get_findings`,
`create_review_finding` (mutating), `update_finding_status` (mutating).

Schemas are zod on the TS side and Pydantic on the Python side; the parity test
`apps/api/tests/test_mcp_parity.py` fails the build if names or mutating flags
diverge.

## Security
* Every call carries `_context {user_id, role, confirmation_id}`.
* Mutating tools **refuse** without a confirmation id (protocol-level error
  `confirmation_required`).
* The API bridge (`POST /mcp-bridge/tools/{name}/execute`) re-checks role →
  permission, confirmation status, and the SHA-256 digest of the arguments
  before executing; confirmations are single-use.
* Read tools execute automatically; writes never do.

## Transports recorded in the audit trail
| transport | meaning |
|---|---|
| `mcp-http` | request arrived through the MCP server |
| `in-process` | DEMO/offline execution inside the API |
| `in-process-fallback` | MCP configured but unreachable/failed — logged, never silent |

## Resources
* `ariadne://policy/tools` — the tool policy table.
* `ariadne://project/orion-ev/summary` — live project summary from the API.

## Verification
`python scripts/mcp_probe.py` runs an independent MCP client session:
initialize → list tools/resources → read tool → mutating-without-confirmation
refusal → role refusal.

## Limitations
* The SDK's streamable-HTTP transport serves one session per instance in 1.x,
  so the server builds a stateless server per request.
* The bundled Python `mcp` 2.x client occasionally stalls during `call_tool`
  against this SDK version in some environments; the gateway caps that path at
  5 s and falls back in-process (recorded as `in-process-fallback`). Direct
  JSON-RPC clients and the probe script work reliably.
