import type { RevisionOut } from "../types/api";

export function RevisionSelector({ revisions, a, b, onChange }: {
  revisions: RevisionOut[]; a: string; b: string;
  onChange: (a: string, b: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 font-mono text-[12px]">
      <span className="text-slate-500">compare</span>
      {revisions.map((r) => (
        <button
          key={r.id}
          onClick={() => onChange(r.id, b)}
          className={`px-2.5 py-1 border ${a === r.id ? "border-cad-orange text-cad-orange bg-cad-orange/10" : "border-line text-slate-400 hover:text-slate-200"}`}
        >
          {r.name}
        </button>
      ))}
      <span className="text-slate-600">→</span>
      {revisions.map((r) => (
        <button
          key={r.id}
          onClick={() => onChange(a, r.id)}
          className={`px-2.5 py-1 border ${b === r.id ? "border-cad-blue text-cad-blue bg-cad-blue/10" : "border-line text-slate-400 hover:text-slate-200"}`}
        >
          {r.name}
        </button>
      ))}
    </div>
  );
}
