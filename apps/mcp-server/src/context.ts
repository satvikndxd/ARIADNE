/**
 * Caller context carried inside every MCP tool call.
 *
 * The LLM is never the security layer: this context is *validated server-side*
 * by the ARIADNE API (role → permission, confirmation digest), so a model that
 * invents a role still receives a deterministic authorization error.
 */
import { z } from "zod";

export const ContextSchema = z
  .object({
    user_id: z.string().min(1).default("u_engineer_1"),
    role: z.enum(["VIEWER", "ENGINEER", "REVIEWER", "ADMIN"]).optional(),
    confirmation_id: z.string().nullable().optional(),
  })
  .passthrough()
  .default({ user_id: "u_engineer_1" });

export type CallerContext = z.infer<typeof ContextSchema>;

export const API_BASE = process.env.MCP_API_BASE_URL ?? "http://localhost:8000";

export interface BridgeResponse {
  ok: boolean;
  tool: string;
  result?: unknown;
  error?: string;
  error_code?: string;
  status?: string;
  transport?: string;
  latency_ms?: number;
}

/** Execute a tool through the API's guarded bridge (single enforcement point). */
export async function callBridge(
  tool: string,
  args: Record<string, unknown>,
  ctx: CallerContext,
): Promise<BridgeResponse> {
  const res = await fetch(`${API_BASE}/mcp-bridge/tools/${tool}/execute`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-ariadne-user": ctx.user_id ?? "u_engineer_1",
      "x-ariadne-via": "mcp",
    },
    body: JSON.stringify({ args, context: ctx }),
  });
  const body = (await res.json()) as BridgeResponse & { error?: unknown };
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } }).error;
    return {
      ok: false,
      tool,
      status: res.status === 403 ? "denied" : "error",
      error: err?.message ?? `HTTP ${res.status}`,
      error_code: err?.code ?? "http_error",
    };
  }
  return body;
}
