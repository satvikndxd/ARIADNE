import type { RevisionOut } from "../types/api";

export function RevisionTimeline({ revisions, activeId, onSelect }: {
  revisions: RevisionOut[]; activeId: string | null; onSelect: (id: string) => void;
}) {
  return (
    <div className="flex items-stretch gap-0 px-3 py-2 border-b border-line bg-ink-850/40 overflow-x-auto scroll-thin">
      {revisions.map((r, i) => (
        <div key={r.id} className="flex items-center">
          <button onClick={() => onSelect(r.id)} className="text-left group">
            <div className={`flex items-center gap-2 px-2.5 py-1 border ${activeId === r.id ? "border-cad-orange text-cad-orange" : "border-line text-slate-400 group-hover:text-slate-200"}`}>
              <span className="w-2 h-2 rounded-full" style={{ background: activeId === r.id ? "#e0762a" : "#2e4054" }} />
              <span className="font-mono text-[12px]">{r.name}</span>
              <span className="font-mono text-[10px] text-slate-600">{(r.metadata_json as { date?: string })?.date ?? ""}</span>
            </div>
            <div className="mt-1 max-w-[240px] text-[10px] text-slate-600 font-mono truncate" title={r.notes}>{r.notes}</div>
          </button>
          {i < revisions.length - 1 && <div className="w-8 h-px bg-line mx-1 shrink-0" />}
        </div>
      ))}
    </div>
  );
}
