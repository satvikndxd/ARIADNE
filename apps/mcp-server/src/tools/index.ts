/**
 * The twelve ARIADNE MCP tools.
 *
 * Schemas are typed with zod and mirrored 1:1 by the Python registry
 * (apps/api/app/services/agent/tools.py).  Handlers are thin: validation and
 * every security decision happen in the API bridge; here we only shape the
 * MCP response and surface structured errors to the client.
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { callBridge, ContextSchema, type CallerContext } from "../context.js";
import { TOOL_META } from "../registry.js";

const ctx = { _context: ContextSchema.optional() };

const bbox = z
  .object({ x: z.number(), y: z.number(), width: z.number(), height: z.number(), page: z.number().int().default(1) })
  .partial();

const evidenceIn = z.object({
  evidence_type: z.string().default("document"),
  document_id: z.string().nullable().optional(),
  document_name: z.string().optional(),
  chunk_id: z.string().nullable().optional(),
  page: z.number().int().nullable().optional(),
  section: z.string().optional(),
  bbox: bbox.nullable().optional(),
  excerpt: z.string().optional(),
  score: z.number().default(0),
});

const findingCreate = z.object({
  project_id: z.string(),
  revision_id: z.string().nullable().optional(),
  component_id: z.string().nullable().optional(),
  analysis_run_id: z.string().nullable().optional(),
  change_id: z.string().nullable().optional(),
  title: z.string().min(4).max(300),
  severity: z.enum(["high", "medium", "low", "info"]).default("medium"),
  confidence: z.number().min(0).max(1).default(0.5),
  description: z.string().default(""),
  recommendation: z.string().default(""),
  status: z.enum(["open", "needs_review", "accepted", "rejected", "resolved"]).default("open"),
  source: z.string().default("agent"),
  affected_component_ids: z.array(z.string()).default([]),
  evidence: z.array(evidenceIn).default([]),
  metadata: z.record(z.unknown()).default({}),
});

interface Shape {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any;
}

const SHAPES: Record<string, Shape> = {
  get_project: { ...ctx, project_id: z.string() },
  get_revision: { ...ctx, revision_id: z.string() },
  compare_revisions: { ...ctx, revision_a: z.string(), revision_b: z.string() },
  get_component: { ...ctx, component_id: z.string(), revision_id: z.string().nullable().optional() },
  get_component_properties: { ...ctx, component_id: z.string(), revision_id: z.string().nullable().optional() },
  get_dependencies: { ...ctx, component_id: z.string(), depth: z.number().int().min(1).max(4).default(2) },
  search_requirements: {
    ...ctx,
    query: z.string().min(1).max(1000),
    project_id: z.string().nullable().optional(),
    component_ids: z.array(z.string()).default([]),
    revision: z.string().nullable().optional(),
    top_k: z.number().int().min(1).max(20).default(6),
  },
  get_requirement: { ...ctx, requirement_id: z.string() },
  get_revision_history: { ...ctx, component_id: z.string() },
  get_findings: { ...ctx, project_id: z.string(), status: z.string().nullable().optional() },
  create_review_finding: { ...ctx, finding: findingCreate },
  update_finding_status: { ...ctx, finding_id: z.string(), status: z.string(), note: z.string().default("") },
};

function text(value: unknown): { content: { type: "text"; text: string }[]; isError?: boolean } {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function fail(error: string, code?: string): { content: { type: "text"; text: string }[]; isError: true } {
  return { isError: true, content: [{ type: "text", text: JSON.stringify({ error, error_code: code }) }] };
}

export function registerTools(server: McpServer): void {
  for (const meta of TOOL_META) {
    const shape = SHAPES[meta.name];
    if (!shape) throw new Error(`missing schema for tool ${meta.name}`);
    const description = meta.mutating
      ? `${meta.description} Requires an approved human confirmation; authorization is enforced server-side.`
      : meta.description;
    server.registerTool(
      meta.name,
      { description, inputSchema: shape },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      async (raw: any) => {
        const { _context, ...args } = raw as { _context?: CallerContext } & Record<string, unknown>;
        const context: CallerContext = ContextSchema.parse(_context ?? {});
        if (meta.mutating && !context.confirmation_id) {
          return fail(
            `Tool '${meta.name}' mutates project state and requires an approved human confirmation ` +
              `(pass _context.confirmation_id obtained from POST /confirmations).`,
            "confirmation_required",
          );
        }
        try {
          const res = await callBridge(meta.name, args, context);
          if (!res.ok) return fail(res.error ?? "tool failed", res.error_code);
          return text(res.result);
        } catch (err) {
          return fail(err instanceof Error ? err.message : String(err), "mcp_transport_error");
        }
      },
    );
  }
}
