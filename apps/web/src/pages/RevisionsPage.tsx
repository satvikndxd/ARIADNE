import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { AnalysisProgress } from "../components/AnalysisProgress";
import { ChangeList } from "../components/ChangeList";
import { ConfirmationModal } from "../components/ConfirmationModal";
import { DrawingComparison } from "../components/DrawingComparison";
import { EvidencePanel } from "../components/EvidencePanel";
import { ImpactPanel } from "../components/ImpactPanel";
import { RevisionSelector } from "../components/RevisionSelector";
import { RevisionTimeline } from "../components/RevisionTimeline";
import { ToolExecutionPanel } from "../components/ToolExecutionPanel";
import { ConfidenceBadge, StatusBadge } from "../components/badges";
import { api, ApiError, API_BASE, currentUser, currentRole } from "../lib/api";
import type { PendingAction, ToolCallRecord } from "../types/api";

export function RevisionsPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const qc = useQueryClient();
  const revisions = useQuery({ queryKey: ["revisions", projectId], queryFn: () => api.revisions(projectId) });
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const list = revisions.data ?? [];
    if (list.length >= 2 && !a && !b) {
      setA(list[0].id);
      setB(list[1].id);
    }
  }, [revisions.data, a, b]);

  const analyses = useQuery({
    queryKey: ["analyses", projectId],
    queryFn: () => api.analyses(projectId),
    refetchInterval: 4000,
  });
  const latest = useMemo(
    () => analyses.data?.find((r) => r.revision_a_id === a && r.revision_b_id === b) ?? null,
    [analyses.data, a, b],
  );
  const activeId = analysisId ?? latest?.id ?? null;

  const progress = useQuery({
    queryKey: ["analysis-status", activeId],
    queryFn: () => api.analysisStatus(activeId!),
    enabled: !!activeId,
    refetchInterval: (q) => (q.state.data?.status === "running" || q.state.data?.status === "queued" ? 700 : false),
  });
  const result = useQuery({
    queryKey: ["analysis", activeId],
    queryFn: () => api.analysis(activeId!),
    enabled: !!activeId && progress.data?.status === "completed",
  });

  const start = useMutation({
    mutationFn: () => api.startAnalysis({ project_id: projectId, revision_a: a, revision_b: b }),
    onSuccess: (d) => {
      setAnalysisId(d.analysis_id);
      setNotice(null);
      qc.invalidateQueries({ queryKey: ["analyses"] });
    },
    onError: (e: ApiError) => setNotice(`${e.code}: ${e.message}`),
  });

  const toolExecs = useQuery({
    queryKey: ["analysis-tools", activeId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/analysis/${activeId}/tool-executions`, {
        headers: { "x-ariadne-user": currentUser() },
      });
      return (await res.json()) as { tool_executions: ToolCallRecord[] };
    },
    enabled: !!activeId,
  });

  const compare = useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api.compare(a, b),
    enabled: !!a && !!b,
  });

  const chat = useMutation({
    mutationFn: () =>
      api.chat({
        message: `Create a review finding for the possible clearance conflict.`,
        project_id: projectId,
        revision_a: a,
        revision_b: b,
        component_id: selectedChange?.component_id ?? undefined,
      }),
    onSuccess: (d) => {
      if (d.pending_action) setPending(d.pending_action);
      else setNotice(d.answer);
    },
    onError: (e: ApiError) => setNotice(`${e.code}: ${e.message}`),
  });

  const decide = useMutation({
    mutationFn: (approved: boolean) => api.decide(pending!.confirmation_id, approved),
    onSuccess: (d) => {
      setPending(null);
      setNotice(
        d.status === "approved"
          ? `Finding created via MCP tool ${d.tool_name} (transport ${(d.result_json as { transport?: string })?.transport ?? "in-process"}).`
          : "Confirmation rejected — nothing was created.",
      );
      qc.invalidateQueries({ queryKey: ["findings"] });
    },
    onError: (e: ApiError) => setNotice(`${e.code}: ${e.message}`),
  });

  const changes = result.data?.changes ?? compare.data?.changes ?? [];
  const selectedChange = changes.find((c) => c.id === selected) ?? null;
  const canCreate = currentRole() !== "VIEWER";

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-4 py-2.5 border-b border-line bg-ink-900 flex items-center gap-4 flex-wrap">
        <div className="font-mono text-[12px] text-slate-400">ORION EV / REVISIONS</div>
        {revisions.data && (
          <RevisionSelector
            revisions={revisions.data}
            a={a}
            b={b}
            onChange={(na, nb) => {
              setA(na);
              setB(nb);
              setAnalysisId(null);
              setSelected(null);
            }}
          />
        )}
        <div className="flex-1" />
        {latest && <StatusBadge status={latest.status} />}
        <button className="btn btn-primary" onClick={() => start.mutate()} disabled={!a || !b || start.isPending}>
          {start.isPending ? "queueing…" : "Analyze Revision"}
        </button>
      </div>

      {revisions.data && (
        <RevisionTimeline revisions={revisions.data} activeId={b} onSelect={(id) => { setB(id); setAnalysisId(null); }} />
      )}

      {progress.data && (progress.data.status === "running" || progress.data.status === "queued") && (
        <AnalysisProgress progress={progress.data} />
      )}
      {notice && (
        <div className="px-4 py-1.5 border-b border-line bg-ink-850 font-mono text-[11px] text-cad-amber">{notice}</div>
      )}

      <div className="flex-1 min-h-0 flex">
        {/* left: drawings */}
        <div className="flex-1 min-w-0 flex flex-col border-r border-line">
          <DrawingComparison
            drawingA={compare.data?.drawing_a ?? null}
            drawingB={compare.data?.drawing_b ?? null}
            changes={changes}
            selected={selected}
            onSelect={setSelected}
          />
          {compare.data?.alignment && (
            <div className="px-3 py-1.5 border-t border-line font-mono text-[10.5px] text-slate-600 flex gap-4">
              <span>registration: {String(compare.data.alignment.method ?? "orb_partial_affine")}</span>
              <span>inliers {String(compare.data.alignment.inliers ?? 0)}</span>
              <span>Δ pixels {String(((compare.data.alignment.changed_pixel_fraction as number) ?? 0) * 100).slice(0, 4)}%</span>
              <span className="text-slate-700">overlays: red high · blue medium · grey low</span>
            </div>
          )}
        </div>

        {/* middle: changes + evidence */}
        <div className="w-[340px] shrink-0 border-r border-line flex flex-col min-h-0">
          <div className="panel-title justify-between">
            <span>changes · {changes.length}</span>
            {result.data && <ConfidenceBadge value={result.data.confidence} />}
          </div>
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
            <div className="flex-1 min-h-0 overflow-hidden">
              <ChangeList changes={changes} selected={selected} onSelect={setSelected} />
            </div>
            <div className="panel-title !border-t border-b-0">
              affected {selectedChange ? `· via ${selectedChange.metadata?.semantic ?? "change"}` : ""}
            </div>
            <div className="max-h-28 overflow-y-auto scroll-thin bg-ink-900">
              {(result.data?.affected_components ?? [])
                .filter((a) => !selectedChange || a.via_change_ids.includes(String(selectedChange.metadata?.semantic ?? "")) || a.distance_hops === 0)
                .map((a) => (
                  <div key={a.component_id} className={`kv ${selectedChange ? "bg-ink-800/60" : ""}`}>
                    <span className="!text-slate-200">{a.name}</span>
                    <span className="font-mono text-[10.5px] text-slate-500">{a.severity} · {a.distance_hops} hop</span>
                  </div>
                ))}
              {!result.data && <div className="p-3 font-mono text-[11px] text-slate-600">run an analysis</div>}
            </div>
            <div className="panel-title !border-t border-b-0">evidence {selectedChange ? "· filtered" : ""}</div>
            <div className="h-48 shrink-0 overflow-hidden bg-ink-900">
              <EvidencePanel
                evidence={(result.data?.evidence ?? []).filter(
                  (e) => !selectedChange || e.evidence_type !== "document" ||
                    String(selectedChange.metadata?.semantic ?? "") !== "" ,
                )}
              />
            </div>
          </div>
        </div>

        {/* right: impact */}
        <div className="w-[360px] shrink-0 flex flex-col min-h-0 bg-ink-900">
          {result.data ? (
            <>
              <div className="flex-1 min-h-0 overflow-y-auto scroll-thin">
                <ImpactPanel
                  affected={result.data.affected_components}
                  checks={result.data.deterministic_checks}
                  recommendations={result.data.recommendations}
                  insight={result.data.insight}
                  canCreate={canCreate}
                  onCreateFinding={() => chat.mutate()}
                />
              </div>
              <div className="max-h-56 overflow-y-auto scroll-thin">
                <ToolExecutionPanel calls={toolExecs.data?.tool_executions ?? []} />
              </div>
            </>
          ) : (
            <div className="p-6 text-slate-600 font-mono text-[12px] leading-relaxed">
              No analysis for this pair yet.
              <br />
              <br />
              Select two revisions and press <span className="text-cad-orange">Analyze Revision</span>. The pipeline
              aligns the drawings (OpenCV), diffs them, maps changes to components, traverses the dependency graph,
              retrieves standards evidence and computes deterministic rule checks before proposing anything.
            </div>
          )}
        </div>
      </div>

      {pending && (
        <ConfirmationModal
          action={pending}
          busy={decide.isPending}
          onDecide={(approved) => decide.mutate(approved)}
          onClose={() => setPending(null)}
        />
      )}
    </div>
  );
}
