/**
 * ARIADNE MCP server — streamable HTTP transport (official MCP SDK).
 *
 * Security model: this process performs NO authorization itself beyond refusing
 * mutating calls without a confirmation id; the authoritative checks (roles,
 * permissions, confirmation digests) run in the ARIADNE API bridge.  Two layers,
 * both deterministic, neither of them the LLM.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

import { registerResources } from "./resources.js";
import { registerTools } from "./tools/index.js";

const PORT = Number(process.env.MCP_SERVER_PORT ?? 8765);

export function buildServer(): McpServer {
  const server = new McpServer(
    { name: "ariadne", version: "0.1.0" },
    { capabilities: { tools: {}, resources: {} } },
  );
  registerTools(server);
  registerResources(server);
  return server;
}

async function main(): Promise<void> {
  const http = createServer(async (req: IncomingMessage, res: ServerResponse) => {
    const url = req.url ?? "/";
    if (url.startsWith("/health")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ status: "ok", service: "ariadne-mcp", tools: 12 }));
      return;
    }
    if (url.startsWith("/mcp")) {
      try {
        // Stateless mode: one McpServer + transport per request.  The SDK 1.x
        // streamable-HTTP transport serves a single session per instance, so a
        // long-lived shared transport would 500 every client after the first.
        const server = buildServer();
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
        await server.connect(transport);
        res.on("close", () => {
          void transport.close().catch(() => undefined);
          void server.close().catch(() => undefined);
        });
        // The SDK's node adapter reads the request body itself (Hono bridge);
        // we must NOT consume the stream here.
        await transport.handleRequest(req, res, undefined);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("[ariadne-mcp] handleRequest failed:", err);
        if (!res.headersSent) {
          res.writeHead(500, { "content-type": "application/json" });
        }
        res.end(JSON.stringify({ error: String(err) }));
      }
      return;
    }
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
  });

  http.listen(PORT, () => {
    // eslint-disable-next-line no-console
    console.log(`[ariadne-mcp] streamable-http listening on :${PORT}/mcp`);
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("[ariadne-mcp] fatal:", err);
  process.exit(1);
});
