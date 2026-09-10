import type { AnalysisProgress as P } from "../types/api";

const STAGES = [
  "loading_revisions", "aligning_drawings", "detecting_changes", "classifying_changes",
  "mapping_components", "traversing_dependencies", "retrieving_evidence", "generating_impact", "preparing_review",
];

export function AnalysisProgress({ progress }: { progress: P }) {
  const idx = STAGES.indexOf(progress.stage);
  return (
    <div className="px-3 py-2 border-b border-line bg-ink-850/60">
      <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
        <span className={progress.status === "failed" ? "text-cad-red" : "text-cad-blue"}>●</span>
        {progress.status} · {progress.stage.replace(/_/g, " ")} · {progress.progress}%
      </div>
      <div className="mt-2 grid grid-cols-9 gap-1">
        {STAGES.map((s, i) => (
          <div key={s} title={s} className="h-1.5"
            style={{
              background:
                progress.status === "failed" && i === idx ? "#d64533"
                : i < idx || progress.status === "completed" ? "#4fa37a"
                : i === idx ? "#4d8fd1" : "#223041",
            }}
          />
        ))}
      </div>
      <div className="mt-1.5 font-mono text-[10.5px] text-slate-500">{progress.message}</div>
    </div>
  );
}
