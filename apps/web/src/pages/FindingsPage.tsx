import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";

import { FindingTable } from "../components/FindingTable";
import { ConfidenceBadge, SeverityBadge, StatusBadge } from "../components/badges";
import { api, ApiError, API_BASE, currentRole, currentUser } from "../lib/api";
import type { FindingStatus } from "../types/api";

export function FindingsPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const findings = useQuery({ queryKey: ["findings", projectId], queryFn: () => api.findings(projectId) });
  const selectedId = params.get("f") ?? findings.data?.[0]?.id ?? null;
  const sel = (findings.data ?? []).find((f) => f.id === selectedId) ?? null;
  const [note, setNote] = useState("");
  const chain = useQuery({
    queryKey: ["chain", selectedId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/findings/${selectedId}/chain`, {
        headers: { "x-ariadne-user": currentUser() },
      });
      return (await res.json()) as { finding_id: string; chain: { type: string; id: string | null; label: string; detail: string; link?: string }[] };
    },
    enabled: !!selectedId,
  });
  const role = currentRole();
  const canReview = role === "REVIEWER" || role === "ADMIN";

  const setStatus = async (status: FindingStatus) => {
    if (!sel) return;
    try {
      await api.patchFinding(sel.id, { status, resolution_note: note });
      qc.invalidateQueries({ queryKey: ["findings"] });
      setNote("");
    } catch (e) {
      setNote(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    }
  };

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 border-r border-line">
        <FindingTable findings={findings.data ?? []} />
      </div>
      <div className="w-[420px] shrink-0 overflow-y-auto scroll-thin bg-ink-900">
        {sel ? (
          <>
            <div className="panel-title justify-between">
              <span className="font-mono normal-case tracking-normal text-[12px] text-slate-200">{sel.id}</span>
              <StatusBadge status={sel.status} />
            </div>
            <div className="p-3 space-y-2">
              <div className="text-[13.5px] text-slate-100">{sel.title}</div>
              <div className="flex gap-2 items-center">
                <SeverityBadge severity={sel.severity} />
                <ConfidenceBadge value={sel.confidence} />
                <span className="chip border-line text-slate-500">{sel.source}</span>
              </div>
              <div className="text-[12px] text-slate-400">{sel.description}</div>
              <div className="text-[12px] text-cad-amber">{sel.recommendation}</div>
              <div className="kv"><span>component</span><span>{sel.component_name || "—"}</span></div>
              <div className="kv"><span>created by</span><span>{sel.created_by}</span></div>
              <div className="kv"><span>reviewed by</span><span>{sel.reviewed_by ?? "—"}</span></div>
            </div>
            <div className="panel-title">evidence · {sel.evidence.length}</div>
            {sel.evidence.map((e) => (
              <div key={e.id} className="px-3 py-2 border-b border-line/60">
                <div className="font-mono text-[10.5px] text-slate-500">
                  {e.evidence_type} · {e.section ? `§${e.section}` : ""} {e.page ? `p.${e.page}` : ""}
                  {e.bbox ? ` · region ${Math.round(e.bbox.x)},${Math.round(e.bbox.y)}` : ""}
                </div>
                <div className="text-[11.5px] text-slate-400 mt-0.5">{e.excerpt}</div>
              </div>
            ))}
            <div className="panel-title">evidence chain · backward-traceable</div>
            <div className="px-3 py-2 space-y-1.5">
              {(chain.data?.chain ?? []).map((n, i) => (
                <div key={`${n.type}-${i}`} className="border-l-2 border-line pl-2">
                  <div className="flex items-center gap-2 font-mono text-[10.5px]">
                    <span className="chip border-line text-slate-400">{n.type}</span>
                    {n.link ? (
                      <button className="text-cad-blue hover:underline" onClick={() => nav(n.link!)}>
                        {n.label}
                      </button>
                    ) : (
                      <span className="text-slate-200">{n.label}</span>
                    )}
                  </div>
                  <div className="text-[10.5px] text-slate-500">{n.detail}</div>
                </div>
              ))}
              {!chain.data && <div className="font-mono text-[10.5px] text-slate-600">loading chain…</div>}
            </div>
            <div className="p-3 space-y-2 border-t border-line">
              <input className="input" placeholder="review note…" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex gap-2">
                <button className="btn" disabled={!canReview} onClick={() => setStatus("needs_review")}>needs review</button>
                <button className="btn btn-primary" disabled={!canReview} onClick={() => setStatus("accepted")}>accept</button>
                <button className="btn btn-danger" disabled={!canReview} onClick={() => setStatus("rejected")}>reject</button>
              </div>
              {!canReview && <div className="font-mono text-[10.5px] text-slate-600">role {role} cannot change finding status (REVIEWER required)</div>}
              {note.includes(":") && <div className="font-mono text-[10.5px] text-cad-red">{note}</div>}
            </div>
          </>
        ) : (
          <div className="p-6 font-mono text-[12px] text-slate-600">select a finding</div>
        )}
      </div>
    </div>
  );
}
