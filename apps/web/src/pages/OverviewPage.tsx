import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useOutletContext } from "react-router-dom";

import { StatusBadge } from "../components/badges";
import { api } from "../lib/api";

export function OverviewPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const nav = useNavigate();
  const ov = useQuery({ queryKey: ["overview", projectId], queryFn: () => api.overview(projectId) });
  const d = ov.data;
  if (!d) return <div className="p-6 font-mono text-slate-600">loading…</div>;
  const s = d.latest_analysis?.summary as Record<string, number> | undefined;
  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 space-y-4">
      <div className="grid grid-cols-4 gap-3">
        {[
          ["project", d.project.name],
          ["active revision", d.active_revision ?? "—"],
          ["revisions", String(d.revision_count)],
          ["findings", String(d.findings_total)],
        ].map(([k, v]) => (
          <div key={k} className="panel px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">{k}</div>
            <div className="mt-1 font-mono text-[15px] text-slate-100">{v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="panel col-span-2">
          <div className="panel-title">latest analysis</div>
          {d.latest_analysis ? (
            <>
              <div className="kv"><span>id</span><span className="font-mono text-[11px]">{d.latest_analysis.id}</span></div>
              <div className="kv"><span>status</span><span><StatusBadge status={d.latest_analysis.status} /></span></div>
              <div className="kv"><span>mode</span><span>{d.latest_analysis.mode === "demo" ? "demo (deterministic)" : "live providers"}</span></div>
              <div className="kv"><span>changes</span><span>{s?.changes ?? 0} ({s?.consequential ?? 0} consequential)</span></div>
              <div className="kv"><span>affected components</span><span>{s?.affected_components ?? 0}</span></div>
              <div className="kv"><span>evidence items</span><span>{s?.evidence ?? 0}</span></div>
              <div className="kv"><span>proposed findings</span><span>{s?.proposed_findings ?? 0}</span></div>
              <div className="p-3">
                <button className="btn" onClick={() => nav("/revisions")}>open comparison</button>
              </div>
            </>
          ) : (
            <div className="p-4 font-mono text-[12px] text-slate-600">no analysis yet — run one from Revisions.</div>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">findings by status</div>
          {Object.entries(d.findings_by_status).map(([k, v]) => (
            <div key={k} className="kv"><span>{k.replace("_", " ")}</span><span>{v}</span></div>
          ))}
          <div className="panel-title !border-t-0">unresolved changes</div>
          <div className="px-3 py-2 font-mono text-[13px] text-cad-orange">{d.unresolved_changes}</div>
          <div className="panel-title !border-t-0">affected components</div>
          <div className="px-3 py-2 flex flex-wrap gap-1.5">
            {d.affected_components.map((c) => (
              <button key={c} className="chip border-line text-slate-300 hover:border-cad-blue" onClick={() => nav("/components")}>
                {c}
              </button>
            ))}
            {!d.affected_components.length && <span className="text-slate-600 font-mono text-[11px]">—</span>}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">recent activity</div>
        <table className="dense">
          <thead><tr><th>analysis</th><th>status</th><th>mode</th><th>created</th></tr></thead>
          <tbody>
            {d.recent_activity.map((r) => (
              <tr key={r.id}>
                <td className="font-mono text-[10.5px] text-slate-500">{r.id}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="font-mono text-[11px]">{r.mode}</td>
                <td className="font-mono text-[10.5px] text-slate-500">{r.created_at?.slice(0, 19).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
