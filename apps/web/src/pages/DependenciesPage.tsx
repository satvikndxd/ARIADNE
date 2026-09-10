import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router-dom";

import { DependencyGraphView } from "../components/DependencyGraph";
import { api } from "../lib/api";

export function DependenciesPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const comps = useQuery({ queryKey: ["components", projectId], queryFn: () => api.components(projectId) });
  const [root, setRoot] = useState("cmp_motor_mount");
  const [depth, setDepth] = useState(2);
  const [selected, setSelected] = useState<string | null>(null);
  const graph = useQuery({ queryKey: ["deps", root, depth], queryFn: () => api.dependencies(root, depth) });
  const sel = graph.data?.nodes.find((n) => n.id === selected);

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-4 py-2.5 border-b border-line bg-ink-900 flex items-center gap-3">
        <span className="font-mono text-[11px] text-slate-500">root</span>
        <select className="input !w-56 !py-1" value={root} onChange={(e) => { setRoot(e.target.value); setSelected(null); }}>
          {(comps.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <span className="font-mono text-[11px] text-slate-500">depth</span>
        <select className="input !w-16 !py-1" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
          {[1, 2, 3, 4].map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <span className="chip border-line text-slate-500">store: {graph.data?.store ?? "…"}</span>
        <span className="chip border-line text-slate-500">{graph.data?.nodes.length ?? 0} nodes · {graph.data?.edges.length ?? 0} edges</span>
        <div className="flex-1" />
        <span className="font-mono text-[10.5px] text-slate-600">red edges = critical · click a node for details</span>
      </div>
      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0">
          {graph.data && <DependencyGraphView graph={graph.data} selected={selected} onSelect={setSelected} />}
        </div>
        <div className="w-72 shrink-0 border-l border-line bg-ink-900 overflow-y-auto scroll-thin">
          <div className="panel-title">node</div>
          {sel ? (
            <>
              <div className="kv"><span>name</span><span>{sel.label}</span></div>
              <div className="kv"><span>type</span><span>{sel.type}</span></div>
              <div className="kv"><span>subsystem</span><span>{sel.subsystem || "—"}</span></div>
              <div className="kv"><span>material</span><span>{sel.material || "—"}</span></div>
              <div className="kv"><span>direction</span><span>{sel.direction}</span></div>
              <div className="kv"><span>hops</span><span>{sel.depth}</span></div>
              <div className="p-3 space-y-1.5">
                {(graph.data?.edges ?? [])
                  .filter((e) => e.source_component_id === sel.id || e.target_component_id === sel.id)
                  .map((e) => (
                    <div key={e.id} className="font-mono text-[10.5px] text-slate-400">
                      {e.source_component_id === sel.id ? "→" : "←"} {e.relationship_type}{" "}
                      <span className="text-slate-600">
                        {e.source_component_id === sel.id ? e.target_component_id : e.source_component_id}
                      </span>
                    </div>
                  ))}
              </div>
            </>
          ) : (
            <div className="p-4 font-mono text-[11px] text-slate-600">select a node</div>
          )}
        </div>
      </div>
    </div>
  );
}
