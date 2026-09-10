import type { EvidenceRef } from "../types/api";

export function EvidencePanel({ evidence }: { evidence: EvidenceRef[] }) {
  const rows = evidence;
  return (
    <div className="overflow-y-auto scroll-thin h-full">
      {rows.map((e, i) => (
        <div key={`${e.evidence_id}-${i}`} className="px-3 py-2 border-b border-line/60">
          <div className="flex items-center gap-2 font-mono text-[10.5px]">
            <span className={`chip ${e.evidence_type === "structured" ? "border-cad-green/60 text-cad-green" : e.evidence_type === "drawing" ? "border-cad-blue/60 text-cad-blue" : "border-line text-slate-400"}`}>
              {e.evidence_type}
            </span>
            <span className="text-slate-300 truncate">{e.document_name || "structured project data"}</span>
            <span className="text-slate-600">§{e.section || "—"} p.{e.page ?? "—"}</span>
            <span className="flex-1" />
            <span className="text-slate-500">{e.score.toFixed(2)}</span>
          </div>
          <div className="mt-1 text-[11.5px] text-slate-400 line-clamp-3">{e.excerpt}</div>
          <div className="mt-0.5 font-mono text-[10px] text-slate-600">
            {e.retrieval_strategy} · authority {e.authority}
            {e.bbox ? ` · bbox ${Math.round(e.bbox.x)},${Math.round(e.bbox.y)}` : ""}
          </div>
        </div>
      ))}
      {!rows.length && <div className="p-4 text-slate-600 font-mono text-[12px]">no evidence retrieved</div>}
    </div>
  );
}
