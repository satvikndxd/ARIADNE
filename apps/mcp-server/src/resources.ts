/** Read-only MCP resources (project summary + tool policy). */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { API_BASE } from "./context.js";
import { TOOL_META } from "./registry.js";

export function registerResources(server: McpServer): void {
  server.registerResource(
    "tool-policy",
    "ariadne://policy/tools",
    { description: "ARIADNE tool policy: permissions and mutating flags (server-side enforced).", mimeType: "application/json" },
    async () => ({
      contents: [
        { uri: "ariadne://policy/tools", mimeType: "application/json", text: JSON.stringify(TOOL_META, null, 2) },
      ],
    }),
  );
  server.registerResource(
    "orion-ev-summary",
    "ariadne://project/orion-ev/summary",
    { description: "Live summary of the synthetic Orion EV project (from the ARIADNE API).", mimeType: "application/json" },
    async () => {
      try {
        const res = await fetch(`${API_BASE}/projects/proj_orion_ev/overview`, {
          headers: { "x-ariadne-user": "u_viewer_1" },
        });
        const body = await res.json();
        return {
          contents: [{ uri: "ariadne://project/orion-ev/summary", mimeType: "application/json", text: JSON.stringify(body) }],
        };
      } catch (err) {
        return {
          contents: [
            {
              uri: "ariadne://project/orion-ev/summary",
              mimeType: "application/json",
              text: JSON.stringify({ error: String(err) }),
            },
          ],
        };
      }
    },
  );
}
