# @ariadne/shared-types

Pins the cross-app vocabulary (change types, severities, roles, relationship
types, MCP tool names, analysis stages). Runtime contracts live in the Python
schemas and the web/MCP mirrors; drift is caught by
`apps/api/tests/test_mcp_parity.py` and by review against this package.
