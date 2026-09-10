import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";

export function AuditPage() {
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit(120), refetchInterval: 5000 });
  const execs = useQuery({ queryKey: ["execs"], queryFn: () => api.toolExecutions(60), refetchInterval: 5000 });
  const [tab, setTab] = useState<"audit" | "tools">("audit");

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-4 py-2 border-b border-line bg-ink-900 flex gap-2 items-center">
        <button className={`btn ${tab === "audit" ? "btn-primary" : ""}`} onClick={() => setTab("audit")}>audit trail</button>
        <button className={`btn ${tab === "tools" ? "btn-primary" : ""}`} onClick={() => setTab("tools")}>tool executions</button>
        <span className="font-mono text-[10.5px] text-slate-600 ml-2">append-only · who did what, with which tool, arguments and result</span>
      </div>
      <div className="flex-1 min-h-0 overflow-auto scroll-thin">
        {tab === "audit" ? (
          <table className="dense">
            <thead><tr><th>time</th><th>user</th><th>role</th><th>action</th><th>tool</th><th>arguments</th><th>result</th></tr></thead>
            <tbody>
              {(audit.data?.events ?? []).map((e) => (
                <tr key={String(e.id)}>
                  <td className="font-mono text-[10.5px] text-slate-500 whitespace-nowrap">{String(e.timestamp).slice(11, 19)}</td>
                  <td className="font-mono text-[11px]">{String(e.user)}</td>
                  <td className="font-mono text-[10.5px] text-slate-500">{String(e.role)}</td>
                  <td className={`font-mono text-[11px] ${String(e.severity) === "warning" ? "text-cad-amber" : "text-slate-300"}`}>{String(e.action)}</td>
                  <td className="font-mono text-[11px] text-cad-blue">{String(e.tool ?? "")}</td>
                  <td className="font-mono text-[10px] text-slate-500 max-w-[320px] truncate">{JSON.stringify(e.arguments)}</td>
                  <td className="text-[11px] text-slate-400 max-w-[320px] truncate">{String(e.result_summary)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="dense">
            <thead><tr><th>time</th><th>tool</th><th>status</th><th>transport</th><th>mutating</th><th>by</th><th>ms</th><th>arguments</th></tr></thead>
            <tbody>
              {(execs.data?.tool_executions ?? []).map((t) => (
                <tr key={String(t.id)}>
                  <td className="font-mono text-[10.5px] text-slate-500 whitespace-nowrap">{String(t.timestamp).slice(11, 19)}</td>
                  <td className="font-mono text-[11px] text-slate-200">{String(t.tool)}</td>
                  <td className="font-mono text-[11px]">{String(t.status)}</td>
                  <td className="font-mono text-[10.5px] text-cad-blue">{String(t.transport)}</td>
                  <td className="font-mono text-[10.5px]">{String(t.mutating)}</td>
                  <td className="font-mono text-[10.5px] text-slate-500">{String(t.requested_by)}</td>
                  <td className="font-mono text-[10.5px] text-slate-500">{Number(t.latency_ms).toFixed(0)}</td>
                  <td className="font-mono text-[10px] text-slate-500 max-w-[420px] truncate">{JSON.stringify(t.arguments)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
