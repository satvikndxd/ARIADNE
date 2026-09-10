import type { PendingAction } from "../types/api";

export function ConfirmationModal({ action, busy, onDecide, onClose }: {
  action: PendingAction; busy?: boolean;
  onDecide: (approved: boolean) => void; onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 grid place-items-center p-6" onClick={onClose}>
      <div className="panel w-full max-w-xl" onClick={(e) => e.stopPropagation()}>
        <div className="panel-title justify-between">
          <span className="text-cad-orange">human confirmation required</span>
          <span className="font-mono text-[10.5px] text-slate-600">{action.confirmation_id}</span>
        </div>
        <div className="p-4 space-y-3">
          <div className="text-[13px] text-slate-100 font-mono">{action.action_label}</div>
          <div className="text-[12.5px] text-slate-400">{action.summary}</div>
          {action.affected.length > 0 && (
            <div className="border border-line">
              <div className="px-3 py-1 text-[10.5px] uppercase tracking-wider text-slate-500 font-mono border-b border-line">affected</div>
              {action.affected.map((a) => (
                <div key={a.component_id} className="kv"><span>{a.name}</span><span>{a.severity}</span></div>
              ))}
            </div>
          )}
          {action.evidence.length > 0 && (
            <div className="border border-line max-h-40 overflow-y-auto scroll-thin">
              <div className="px-3 py-1 text-[10.5px] uppercase tracking-wider text-slate-500 font-mono border-b border-line">evidence</div>
              {action.evidence.map((e, i) => (
                <div key={i} className="px-3 py-1.5 border-b border-line/50 last:border-0 text-[11.5px] text-slate-400">
                  <span className="font-mono text-slate-300">{e.document_name} §{e.section} p.{e.page}</span>
                  <div className="line-clamp-2">{e.excerpt}</div>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 justify-end pt-1">
            <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="btn" onClick={() => onDecide(false)} disabled={busy}>Reject</button>
            <button className="btn btn-primary" onClick={() => onDecide(true)} disabled={busy}>
              {busy ? "executing…" : `Confirm · ${action.tool_name}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
