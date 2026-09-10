import type { ChangeOut } from "../types/api";
import { ConfidenceBadge, SeverityBadge } from "./badges";

export function ChangeList({ changes, selected, onSelect }: {
  changes: ChangeOut[]; selected: string | null; onSelect: (id: string) => void;
}) {
  return (
    <div className="overflow-y-auto scroll-thin h-full">
      {changes.map((c, i) => (
        <button
          key={c.id}
          onClick={() => onSelect(c.id)}
          className={`w-full text-left px-3 py-2 border-b border-line/60 hover:bg-ink-800/60 ${
            selected === c.id ? "bg-ink-800 border-l-2 border-l-cad-orange" : "border-l-2 border-l-transparent"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10.5px] text-slate-600">#{String(i + 1).padStart(2, "0")}</span>
            <span className="chip border-line text-slate-400">{c.change_type.replace("_", " ").toLowerCase()}</span>
            <SeverityBadge severity={c.severity} />
            <span className="chip border-line text-slate-500">{c.classification}</span>
            <span className="flex-1" />
            <ConfidenceBadge value={c.confidence} />
          </div>
          <div className="mt-1 text-[12.5px] text-slate-200">{c.title}</div>
          <div className="mt-0.5 font-mono text-[10.5px] text-slate-500">
            {c.component_name || "—"} · {c.detection_method}
            {c.numeric_delta !== null ? ` · Δ ${c.numeric_delta}${c.unit}` : ""}
          </div>
        </button>
      ))}
      {!changes.length && <div className="p-4 text-slate-600 font-mono text-[12px]">no changes detected</div>}
    </div>
  );
}
