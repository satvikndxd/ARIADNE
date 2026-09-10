import type { ChangeOut } from "../types/api";
import { API_BASE } from "../lib/api";
import { SeverityColor } from "./badges";

interface DrawingMeta { image_url: string; width_px: number; height_px: number; filename: string }

/** Split-screen comparison with translucent change overlays keyed to detections. */
export function DrawingComparison({ drawingA, drawingB, changes, selected, onSelect }: {
  drawingA: DrawingMeta | null; drawingB: DrawingMeta | null;
  changes: ChangeOut[]; selected: string | null; onSelect: (id: string) => void;
}) {
  const pane = (label: string, d: DrawingMeta | null, side: "a" | "b") => (
    <div className="flex-1 min-w-0 flex flex-col border-r border-line last:border-r-0">
      <div className="panel-title justify-between">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-slate-500">{d?.filename ?? "—"}</span>
      </div>
      <div className="flex-1 min-h-0 p-2 overflow-auto scroll-thin bg-ink-950">
        {d ? (
          <div className="drawing-paper w-full mx-auto" style={{ aspectRatio: `${d.width_px} / ${d.height_px}` }}>
            <img src={`${API_BASE}${d.image_url}`} alt={label} className="absolute inset-0 w-full h-full" />
            {changes
              .filter((c) => c.drawing_id && ((side === "b") || c.old_value !== null))
              .filter((c, _i, arr) => arr.findIndex((x) => x.id === c.id) === _i)
              .map((c) => {
                const color = SeverityColor(c.severity);
                const active = selected === c.id;
                const w = d.width_px || 1600;
                const h = d.height_px || 1100;
                return (
                  <button
                    key={`${side}-${c.id}`}
                    title={`${c.title} [${c.change_type}]`}
                    onClick={() => onSelect(c.id)}
                    className="overlay-box"
                    style={{
                      left: `${(c.location.x / w) * 100}%`,
                      top: `${(c.location.y / h) * 100}%`,
                      width: `${(Math.max(c.location.width, 24) / w) * 100}%`,
                      height: `${(Math.max(c.location.height, 18) / h) * 100}%`,
                      borderColor: color,
                      background: active ? `${color}44` : `${color}18`,
                      boxShadow: active ? `0 0 0 2px ${color}` : undefined,
                    }}
                  />
                );
              })}
          </div>
        ) : (
          <div className="h-full grid place-items-center text-slate-600 font-mono text-[12px]">no drawing</div>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      {pane("REVISION A", drawingA, "a")}
      {pane("REVISION B", drawingB, "b")}
    </div>
  );
}
