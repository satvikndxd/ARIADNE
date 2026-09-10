#!/usr/bin/env python3
"""Independent MCP client probe.

Proves the TypeScript MCP server speaks the protocol correctly, outside the
API gateway: initializes a session, lists tools/resources, executes a read
tool, and demonstrates that (a) mutating tools refuse without a confirmation
and (b) roles are enforced server-side.  Run with the MCP server up:

    node apps/mcp-server/dist/index.js &
    python scripts/mcp_probe.py
"""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/mcp"
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            info = await s.list_tools()
            print(f"server: {s.server_info.name if s.server_info else '?'}  tools={len(info.tools)}")
            resources = await s.list_resources()
            print(f"resources: {[str(r.uri) for r in resources.resources]}")

            res = await s.call_tool("get_dependencies",
                                    {"component_id": "cmp_motor_mount", "depth": 2,
                                     "_context": {"user_id": "u_engineer_1"}})
            data = json.loads(res.content[0].text)
            print(f"get_dependencies → store={data['store']} nodes={len(data['nodes'])} "
                  f"downstream={data['downstream']}")

            denied = await s.call_tool("create_review_finding",
                                       {"finding": {"project_id": "proj_orion_ev", "title": "probe"},
                                        "_context": {"user_id": "u_engineer_1"}})
            err = json.loads(denied.content[0].text)
            print(f"mutating without confirmation → is_error={denied.is_error} code={err.get('error_code')}")

            forbidden = await s.call_tool("update_finding_status",
                                          {"finding_id": "fd_seed_002", "status": "accepted",
                                           "_context": {"user_id": "u_engineer_1"}})
            err2 = json.loads(forbidden.content[0].text)
            print(f"ENGINEER calling reviewer-only tool → is_error={forbidden.is_error} "
                  f"code={err2.get('error_code')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
