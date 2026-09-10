import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { ConfirmationModal } from "../components/ConfirmationModal";
import { ToolExecutionPanel } from "../components/ToolExecutionPanel";
import { api, ApiError } from "../lib/api";
import type { ChatMessageOut, PendingAction } from "../types/api";

interface UiMessage {
  id: string; role: "user" | "assistant"; content: string;
  tool_calls: ChatMessageOut["tool_calls_json"]; evidence: ChatMessageOut["evidence_json"];
  mode: string;
}

const SUGGESTED = [
  "What changed in Rev B and which components might be affected?",
  "Why is Motor Mount classified as high impact?",
  "Show me the evidence.",
  "Which requirements apply to this component?",
  "Create a review finding for the possible clearance conflict.",
];

export function ChatPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const qc = useQueryClient();
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const revisions = useQuery({ queryKey: ["revisions", projectId], queryFn: () => api.revisions(projectId) });
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, pending]);

  const send = useMutation({
    mutationFn: (text: string) =>
      api.chat({
        message: text,
        project_id: projectId,
        session_id: sessionId ?? undefined,
        revision_a: revisions.data?.[revisions.data.length - 2]?.id,
        revision_b: revisions.data?.[revisions.data.length - 1]?.id,
      }),
    onMutate: (text) => {
      setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text, tool_calls: [], evidence: [], mode: "" }]);
      setError(null);
    },
    onSuccess: (d) => {
      setSessionId(d.session_id);
      setMessages((m) => [
        ...m,
        { id: d.message_id, role: "assistant", content: d.answer, tool_calls: d.tool_calls, evidence: d.evidence, mode: d.mode },
      ]);
      if (d.pending_action) setPending(d.pending_action);
      if (d.insufficient_evidence) setError("retrieval returned no supporting evidence");
    },
    onError: (e: ApiError) => setError(`${e.code}: ${e.message}`),
  });

  const decide = useMutation({
    mutationFn: (approved: boolean) => api.decide(pending!.confirmation_id, approved),
    onSuccess: (d) => {
      setPending(null);
      setMessages((m) => [
        ...m,
        {
          id: `c${Date.now()}`, role: "assistant", mode: "system",
          content:
            d.status === "approved"
              ? `Confirmation approved by ${d.decided_by}. MCP tool ${d.tool_name} executed → finding created.`
              : "Confirmation rejected. Nothing was created or modified.",
          tool_calls: [], evidence: [],
        },
      ]);
      qc.invalidateQueries({ queryKey: ["findings"] });
    },
    onError: (e: ApiError) => setError(`${e.code}: ${e.message}`),
  });

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-4 py-2 border-b border-line bg-ink-900 font-mono text-[11px] text-slate-500 flex gap-3 items-center">
          <span>agent session {sessionId ?? "new"}</span>
          <span className="chip border-line text-slate-500">tool calls always visible</span>
          <span className="chip border-cad-amber/50 text-cad-amber">mutations need confirmation</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin px-4 py-3 space-y-3">
          {messages.map((m) => (
            <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
              <div className={`max-w-[820px] ${m.role === "user" ? "border border-cad-blue/40 bg-cad-blue/5 px-3 py-2" : "panel"}`}>
                {m.role === "assistant" && (
                  <div className="panel-title !py-1">
                    <span>ariadne</span>
                    {m.mode && <span className="chip border-line text-slate-500">{m.mode}</span>}
                  </div>
                )}
                <div className="px-3 py-2 whitespace-pre-wrap text-[12.5px] text-slate-200">{m.content}</div>
                {m.tool_calls.length > 0 && <ToolExecutionPanel calls={m.tool_calls} />}
                {m.evidence.length > 0 && (
                  <div className="border-t border-line px-3 py-1.5 space-y-1">
                    {m.evidence.map((e, i) => (
                      <div key={i} className="font-mono text-[10.5px] text-slate-500">
                        ⌗ {e.document_name} §{e.section} p.{e.page} <span className="text-slate-600">score {e.score.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {send.isPending && <div className="font-mono text-[11px] text-cad-blue">… reasoning + tool use</div>}
          {error && <div className="font-mono text-[11px] text-cad-amber">{error}</div>}
          <div ref={bottom} />
        </div>
        <form
          className="p-3 border-t border-line bg-ink-900 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (input.trim()) {
              send.mutate(input.trim());
              setInput("");
            }
          }}
        >
          <input className="input" value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="ask about changes, impact, evidence, requirements… (e.g. why is the motor mount high impact?)" />
          <button className="btn btn-primary" disabled={send.isPending}>send</button>
        </form>
      </div>
      <div className="w-64 shrink-0 border-l border-line bg-ink-900 p-3 space-y-1.5">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono mb-2">suggested</div>
        {SUGGESTED.map((s) => (
          <button key={s} className="block w-full text-left px-2 py-1.5 border border-line text-[11.5px] text-slate-400 hover:text-slate-200 hover:border-cad-blue/50"
            onClick={() => send.mutate(s)}>
            {s}
          </button>
        ))}
      </div>
      {pending && (
        <ConfirmationModal action={pending} busy={decide.isPending}
          onDecide={(a) => decide.mutate(a)} onClose={() => setPending(null)} />
      )}
    </div>
  );
}
