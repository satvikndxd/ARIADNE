import { useState } from "react";

import { API_BASE } from "../lib/api";
import type { ChangeOut } from "../types/api";

interface Signals {
  status?: string;
  signals?: Record<string, { present: boolean; change_type?: string | null; confidence?: number; detail?: string }>;
  notes?: string[];
  confidence?: number;
}

/** Per-change transparency: CV vs VLM vs structured, and their consensus. */
export function ChangeSignals({ change, analysisId }: { change: ChangeOut | null; analysisId: string | null }) {
  const [open, setOpen] = useState(false);
  if (!change) return null;
  const meta = (change.metadata ?? {}) as {
    cv_confirmed?: boolean; vlm?: Record<string, unknown>; signals?: Signals; semantic?: string; kind?: string;
  };
  const signals = (meta.signals ?? {}) as Signals;
  const vlm = meta.vlm as {
    change_type?: string; confidence?: number; feature?: string | null; old_value?: string | null;
    new_value?: string | null; description?: string; provider?: string;
  } | undefined;
  const consensus = signals.status ?? "n/a";
  const tone =
    consensus === "AGREED" ? "border-cad-green/60 text-cad-green"
    : consensus === "CONFLICT" ? "border-cad-red/70 text-cad-red"
    : "border-cad-amber/60 text-cad-amber";

  return (
    <div className="border-b border-line bg-ink-850/50">
      <div className="px-3 py-2">
        <div className="flex items-center gap-2 font-mono text-[11px]">
          <span className="text-slate-500">CHANGE</span>
          <span className="text-slate-200 truncate">{change.title}</span>
        </div>
        <div className="mt-1 font-mono text-[12px] text-cad-orange">
          {change.old_value ?? "—"} → {change.new_value ?? "—"} {change.unit}
        </div>
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[10.5px]">
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">CV:</span>
            <span className={meta.cv_confirmed ? "text-cad-green" : "text-slate-400"}>
              {meta.cv_confirmed ? "CONFIRMED" : "not confirmed"}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">VLM:</span>
            {vlm ? (
              <span className="text-cad-blue">
                {vlm.change_type} {Math.round((vlm.confidence ?? 0) * 100)}%
              </span>
            ) : (
              <span className="text-slate-500">not run (no endpoint)</span>
            )}
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">STRUCTURED:</span>
            <span className={meta.kind === "cv" ? "text-slate-500" : "text-cad-green"}>
              {meta.kind === "cv" ? "n/a (cv-only)" : "CONFIRMED"}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">CONSENSUS:</span>
            <span className={`chip ${tone}`}>{consensus}</span>
          </div>
        </div>
        {signals.notes && signals.notes.length > 0 && (
          <div className="mt-1 font-mono text-[10px] text-cad-amber">{signals.notes.join(" · ")}</div>
        )}
        <button className="mt-1.5 font-mono text-[10.5px] text-cad-blue hover:underline"
          onClick={() => setOpen(!open)}>
          {open ? "▾ hide" : "▸ show"} Vision Analysis
        </button>
        {open && (
          <div className="mt-2 space-y-2">
            {analysisId && change.id && (
              <div className="flex gap-2">
                {(["a", "b"] as const).map((side) => (
                  <figure key={side} className="flex-1 min-w-0">
                    <img
                      src={`${API_BASE}/analysis/${analysisId}/changes/${change.id}/crop?side=${side}`}
                      alt={`revision ${side} crop`}
                      className="w-full border border-line bg-[#f4f4f1]"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                    <figcaption className="font-mono text-[9.5px] text-slate-600">
                      revision {side.toUpperCase()} crop (after analysis completes)
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
            {vlm ? (
              <div className="font-mono text-[10.5px] text-slate-400 space-y-0.5">
                <div>change type: <span className="text-slate-200">{vlm.change_type}</span></div>
                <div>feature: <span className="text-slate-200">{vlm.feature ?? "—"}</span></div>
                <div>old: <span className="text-slate-200">{vlm.old_value ?? "—"}</span> · new: <span className="text-slate-200">{vlm.new_value ?? "—"}</span></div>
                <div>confidence: <span className="text-slate-200">{Math.round((vlm.confidence ?? 0) * 100)}%</span></div>
                <div className="text-slate-500">{vlm.description}</div>
                <div className="text-slate-600">provider: {vlm.provider}</div>
                <div className={consensus === "CONFLICT" ? "text-cad-red" : "text-cad-green"}>
                  signal: {consensus === "AGREED" ? "agrees with structured data"
                    : consensus === "CONFLICT" ? "disagrees with structured data — inspect before trusting"
                    : "no comparable VLM signal"}
                </div>
              </div>
            ) : (
              <div className="font-mono text-[10.5px] text-slate-500">
                No VLM endpoint configured (VISION_ENABLED + VISION_API_KEY). Perception signals limited to
                OpenCV; consensus computed over structured + CV only.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
