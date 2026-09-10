import type { AffectedComponent, DeterministicCheck, Insight, Recommendation } from "../types/api";
import { SeverityBadge } from "./badges";

export function ImpactPanel({ affected, checks, recommendations, insight, onCreateFinding, canCreate }: {
  affected: AffectedComponent[]; checks: DeterministicCheck[]; recommendations: Recommendation[];
  insight: Insight; onCreateFinding: () => void; canCreate: boolean;
}) {
  const notable = checks.filter((c) => c.result !== "n/a");
  return (
    <div className="flex flex-col min-h-0">
      <div className="panel-title">AI analysis · impact</div>
      <div className="px-3 py-2 border-b border-line/60 space-y-2">
        <div className="text-[12.5px] text-slate-200">{insight.summary}</div>
        <div className={`text-[12.5px] ${insight.potential_impact.includes("FAIL") ? "text-cad-red" : "text-slate-300"}`}>
          {insight.potential_impact}
        </div>
        <div className="text-[11.5px] text-slate-500">{insight.uncertainty}</div>
        <div className="font-mono text-[10.5px] text-slate-600">
          confidence {(insight.confidence.value * 100).toFixed(0)}% · basis: {insight.confidence.basis} · mode: {insight.mode}
        </div>
      </div>

      <div className="panel-title !border-t-0">affected components</div>
      <div className="max-h-40 overflow-y-auto scroll-thin">
        {affected.map((a) => (
          <div key={a.component_id} className="kv">
            <span className="!text-slate-300">{a.name}</span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-[10.5px] text-slate-500">{a.distance_hops} hop</span>
              <SeverityBadge severity={a.severity} />
            </span>
          </div>
        ))}
      </div>

      <div className="panel-title !border-t-0">deterministic checks</div>
      <div className="max-h-44 overflow-y-auto scroll-thin">
        {notable.map((c) => (
          <div key={c.requirement_code} className="px-3 py-1.5 border-b border-line/60">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-slate-300">{c.requirement_code}</span>
              <span className={`chip ${c.result === "fail" ? "border-cad-red/70 text-cad-red" : c.result === "flag" ? "border-cad-amber/70 text-cad-amber" : "border-cad-green/60 text-cad-green"}`}>
                {c.result}
              </span>
              <span className="font-mono text-[10.5px] text-slate-500">{c.rule}</span>
            </div>
            <div className="font-mono text-[10.5px] text-slate-500 mt-0.5">
              inputs {JSON.stringify(c.inputs)} {c.margin !== null ? `· margin ${c.margin}${c.unit}` : ""}
            </div>
          </div>
        ))}
      </div>

      <div className="panel-title !border-t-0">recommended actions</div>
      <div className="px-3 py-2 space-y-1.5 max-h-32 overflow-y-auto scroll-thin">
        {recommendations.map((r, i) => (
          <div key={i} className="text-[12px] text-slate-300 flex gap-2">
            <span className="chip border-line text-slate-500 shrink-0">{r.action_type}</span>
            <span>{r.text}</span>
          </div>
        ))}
        {!recommendations.length && <div className="text-slate-600 font-mono text-[11px]">none</div>}
      </div>

      <div className="p-3 border-t border-line">
        <button className="btn btn-primary w-full" onClick={onCreateFinding} disabled={!canCreate}>
          Create Review Finding
        </button>
        <div className="mt-1.5 text-[10.5px] text-slate-600 font-mono text-center">
          nothing is created without explicit confirmation
        </div>
      </div>
    </div>
  );
}
