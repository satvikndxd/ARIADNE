"""The TypeScript MCP registry and the Python tool registry must agree."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.security import TOOL_POLICY
from app.services.agent.tools import TOOLS

REPO = Path(__file__).resolve().parents[3]


def test_tool_names_match_typescript_registry():
    ts = (REPO / "apps" / "mcp-server" / "src" / "registry.ts").read_text()
    ts_names = re.findall(r'name: "([a-z_]+)", description', ts)
    py_names = [t.name for t in TOOLS]
    assert ts_names == py_names, (ts_names, py_names)


def test_mutating_flags_match_policy():
    ts = (REPO / "apps" / "mcp-server" / "src" / "registry.ts").read_text()
    for name, meta in TOOL_POLICY.items():
        block = ts[ts.index(f'name: "{name}"'):]
        block = block[: block.index("}")]
        assert (f"mutating: {'true' if meta['mutating'] else 'false'}" in block), name


def test_every_tool_has_schema_and_handler():
    for t in TOOLS:
        schema = t.input_schema()
        assert schema["type"] == "object"
        assert callable(t.handler)
        assert t.description


def test_bridge_rejects_unknown_tool(client):
    r = client.post("/mcp-bridge/tools/destroy_everything/execute", json={"args": {}, "context": {}})
    assert r.status_code == 422
    assert r.json()["error_code"] == "unknown_tool"


def test_bridge_executes_read_tool(client):
    r = client.post("/mcp-bridge/tools/get_dependencies/execute",
                    json={"args": {"component_id": "cmp_motor_mount", "depth": 2},
                          "context": {"user_id": "u_engineer_1"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transport"] == "mcp-http"
    assert body["result"]["root_component_id"] == "cmp_motor_mount"
