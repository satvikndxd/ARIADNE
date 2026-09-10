import { useState } from "react";

import type { ToolCallRecord } from "../types/api";

export function ToolExecutionPanel({ calls }: { calls: ToolCallRecord[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!calls.length) return null;
  return (
    <div className="border-t border-line">
      <div className="panel-title">tool usage · {calls.length}</div>
      {calls.map((c, i) => (
        <div key={c.execution_id || i} className="border-b border-line/60 last:border-0">
          <button className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-ink-800/60 font-mono text-[11px]"
            onClick={() => setOpen(open === i ? null : i)}>
            <span className="text-slate-600">{open === i ? "▾" : "▸"}</span>
            <span className="text-cad-blue">→</span>
            <span className="text-slate-200">{c.tool_name}</span>
            <span className="text-slate-600 truncate">{JSON.stringify(c.arguments).slice(0, 60)}</span>
            <span className="flex-1" />
            <span className={`chip ${c.status === "ok" ? "border-cad-green/50 text-cad-green" : "border-cad-red/60 text-cad-red"}`}>{c.status}</span>
            <span className="chip border-line text-slate-500">{c.transport}</span>
            <span className="text-slate-600">{c.latency_ms.toFixed(0)}ms</span>
          </button>
          {open === i && (
            <pre className="px-4 py-2 text-[10.5px] text-slate-400 bg-ink-950/60 overflow-x-auto scroll-thin">
{JSON.stringify({ arguments: c.arguments, result_summary: c.result_summary, error: c.error }, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
