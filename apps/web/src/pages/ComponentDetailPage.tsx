import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { FindingTable } from "../components/FindingTable";
import { SeverityBadge } from "../components/badges";
import { api } from "../lib/api";

export function ComponentDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const comp = useQuery({ queryKey: ["component", id], queryFn: () => api.component(id) });
  const graph = useQuery({ queryKey: ["deps", id], queryFn: () => api.dependencies(id, 2) });
  const history = useQuery({ queryKey: ["history", id], queryFn: () => api.revisionHistory(id) });
  const findings = useQuery({ queryKey: ["findings-component", id], queryFn: () => api.findings(undefined, undefined) });
  const reqs = useQuery({ queryKey: ["reqs", id], queryFn: () => api.requirements(id) });

  const c = comp.data;
  if (!c) return <div className="p-6 font-mono text-slate-600">loading…</div>;
  const mine = (findings.data ?? []).filter((f) => f.affected_component_ids.includes(id) || f.component_id === id);

  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 space-y-3">
      <div className="flex items-center gap-3">
        <button className="btn" onClick={() => nav("/components")}>←</button>
        <div className="font-mono text-[15px] text-slate-100">{c.name}</div>
        <span className="chip border-line text-slate-400">{c.code}</span>
        <span className="chip border-line text-slate-400">{c.subsystem}</span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="panel">
          <div className="panel-title">properties (current snapshot)</div>
          {Object.entries(c.properties).map(([k, v]) => (
            <div key={k} className="kv"><span>{k}</span><span className="font-mono text-[11.5px]">{String(v)}</span></div>
          ))}
          <div className="kv"><span>material</span><span>{c.material || "—"}</span></div>
          <div className="kv"><span>mass</span><span>{c.weight_g} g</span></div>
        </div>

        <div className="panel">
          <div className="panel-title">dependencies</div>
          <div className="px-3 py-1.5 text-[10.5px] uppercase tracking-wider text-slate-500 font-mono">upstream</div>
          {(graph.data?.upstream ?? []).map((u) => (
            <button key={u} className="kv w-full hover:bg-ink-800" onClick={() => nav(`/components/${u}`)}>
              <span className="!text-cad-green">{graph.data?.nodes.find((n) => n.id === u)?.label ?? u}</span><span>↑</span>
            </button>
          ))}
          <div className="px-3 py-1.5 text-[10.5px] uppercase tracking-wider text-slate-500 font-mono">downstream</div>
          {(graph.data?.downstream ?? []).map((u) => (
            <button key={u} className="kv w-full hover:bg-ink-800" onClick={() => nav(`/components/${u}`)}>
              <span className="!text-cad-blue">{graph.data?.nodes.find((n) => n.id === u)?.label ?? u}</span><span>↓</span>
            </button>
          ))}
          <div className="px-3 py-1.5 text-[10.5px] uppercase tracking-wider text-slate-500 font-mono">governing specs</div>
          {(graph.data?.specifications ?? []).map((s) => (
            <div key={s} className="kv"><span className="!text-slate-300">{s}</span><span>§</span></div>
          ))}
        </div>

        <div className="panel">
          <div className="panel-title">revision history</div>
          {(history.data?.deltas ?? []).map((d, i) => (
            <div key={i} className="px-3 py-2 border-b border-line/60">
              <div className="font-mono text-[10.5px] text-slate-500">→ {d.revision_id}</div>
              {Object.entries(d.changed_properties).map(([k, v]) => (
                <div key={k} className="font-mono text-[11px] text-slate-300 mt-0.5">
                  {k}: <span className="text-slate-500 line-through">{String(v.old)}</span> → <span className="text-cad-orange">{String(v.new)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="panel">
          <div className="panel-title">applicable requirements</div>
          {(reqs.data ?? []).map((r) => (
            <div key={r.id} className="px-3 py-2 border-b border-line/60">
              <div className="font-mono text-[11px] text-cad-blue">{r.code} <span className="text-slate-500">§{r.section} p.{r.page}</span></div>
              <div className="text-[11.5px] text-slate-400 mt-0.5 line-clamp-2">{r.text}</div>
            </div>
          ))}
          {!reqs.data?.length && <div className="p-3 font-mono text-[11px] text-slate-600">none linked</div>}
        </div>
        <div className="panel">
          <div className="panel-title">findings · {mine.length}</div>
          <div className="max-h-72 overflow-auto scroll-thin">
            <FindingTable findings={mine} />
          </div>
        </div>
      </div>
      <div className="pb-2 font-mono text-[10.5px] text-slate-600">
        severity legend: <SeverityBadge severity="high" /> interface/limit · <SeverityBadge severity="medium" /> propagation · <SeverityBadge severity="low" /> cosmetic
      </div>
    </div>
  );
}
