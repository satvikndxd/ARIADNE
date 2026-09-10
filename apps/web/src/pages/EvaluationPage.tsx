import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";

export function EvaluationPage() {
  const runs = useQuery({ queryKey: ["eval"], queryFn: () => api.evaluationRuns().then((r) => r.runs), refetchInterval: 8000 });
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = (runs.data ?? []).find((r) => r.id === runId) ?? runs.data?.[0] ?? null;
  const groups = active
    ? Object.entries(
        active.metrics.reduce<Record<string, typeof active.metrics>>((acc, m) => {
          (acc[m.subset] ??= []).push(m);
          return acc;
        }, {}),
      )
    : [];

  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 space-y-3">
      <div className="flex items-center gap-3">
        <div className="font-mono text-[13px] text-slate-200">evaluation runs</div>
        <button className="btn" disabled={busy} onClick={async () => { setBusy(true); try { await api.runEvaluation(); } finally { setTimeout(() => setBusy(false), 4000); } }}>
          run evaluation
        </button>
        <span className="font-mono text-[10.5px] text-slate-600">
          metrics are computed by executing the real pipeline against generated ground truth — never fabricated.
        </span>
      </div>

      <div className="flex gap-2 flex-wrap">
        {(runs.data ?? []).map((r) => (
          <button key={r.id} onClick={() => setRunId(r.id)}
            className={`chip px-2 py-1 ${active?.id === r.id ? "border-cad-orange text-cad-orange" : "border-line text-slate-400"}`}>
            {r.name} · {r.created_at?.slice(5, 16).replace("T", " ")}
          </button>
        ))}
      </div>

      <div className="font-mono text-[10.5px] text-slate-600">
        all values are <span className="text-cad-green">measured</span> by executing the real pipelines
        (blind benchmark, retrieval experiment, agent suite); absent subsets are labelled not-run in the
        JSON report, never estimated.
      </div>
      {active && (
        <div className="grid grid-cols-2 gap-3">
          {groups.map(([subset, metrics]) => (
            <div key={subset} className="panel">
              <div className="panel-title">{subset}</div>
              {metrics.map((m, i) => (
                <div key={i} className="kv">
                  <span>{m.metric}</span>
                  <span className="font-mono text-[12px]">
                    {m.value.toFixed(4)} <span className="text-slate-600">n={m.n}</span>
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {active && (
        <div className="panel">
          <div className="panel-title">failure analysis · top categories</div>
          {groups
            .filter(([subset]) => subset.startsWith("failure:"))
            .map(([subset, metrics]) => (
              <div key={subset} className="kv">
                <span>{subset.replace("failure:", "")}</span>
                <span className="font-mono">{metrics[0].value} / {metrics[0].n} failures</span>
              </div>
            ))}
          {!groups.some(([subset]) => subset.startsWith("failure:")) && (
            <div className="px-3 py-2 font-mono text-[11px] text-slate-600">no failures recorded in this run</div>
          )}
        </div>
      )}
      {active?.report_path && (
        <div className="font-mono text-[10.5px] text-slate-600">report: {active.report_path}</div>
      )}
    </div>
  );
}
