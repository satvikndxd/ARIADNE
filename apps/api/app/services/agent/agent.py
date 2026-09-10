"""The ARIADNE agent.

Architecture decision (ADR-004): tool *selection* is a deterministic policy over
the request + project context; the LLM is used only to compose grounded prose
from the structured tool outputs.  This makes tool selection measurable and
keeps DEMO_MODE fully functional.  In live mode the same policy runs first and
the LLM may re-order/extend via function-calling in a later iteration — the
policy result is always the fallback.

Hard rules implemented here:
  * the agent never mutates state; it *proposes* and requests a confirmation;
  * every answer carries its evidence list; empty retrieval ⇒
    "Insufficient evidence to determine impact.";
  * retrieved text is data: quarantined chunks never enter the answer context.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_id, utcnow
from app.core.logging import Timer, get_logger
from app.db.models import AnalysisRun, ChatMessage, ChatSession, Component, Finding, Project, Revision
from app.schemas.chat import ChatRequest, ChatResponse, PendingAction
from app.schemas.common import EvidenceRef, Severity, ToolCallRecord
from app.schemas.domain import FindingCreate, FindingEvidenceIn
from app.core.security import Principal
from app.services.agent.gateway import ToolGateway, create_confirmation
from app.services.agent.tools import TOOL_BY_NAME

log = get_logger(__name__)

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("findings", [r"\b(list|show|get)\b[^.?]*\bfindings?\b", r"\bfindings?\b[^.?]*\b(list|status)\b"]),
    ("create_finding", [r"\b(create|file|raise)\b[^.?]*\bfinding", r"\bopen\b\s+a\s+[^.?]*finding"]),
    ("update_status", [r"\b(accept|reject|resolve|close)\b.*\bfinding"]),
    ("why_impact", [r"\bwhy\b.*\b(high|impact|severity|classified)", r"\bexplain\b.*\bimpact"]),
    ("dependencies", [r"\bdependenc", r"\bupstream\b", r"\bdownstream\b", r"\baffected\b"]),
    ("history", [r"\bhistory\b", r"\bprevious revisions\b", r"\bwhat changed before\b"]),
    ("evidence", [r"\bevidence\b", r"\bsource", r"\bcitation", r"\bshow me\b"]),
    ("requirements", [r"\brequirement", r"\bstandard", r"\bspecification", r"\bapply\b"]),
    ("changes", [r"\bwhat changed\b", r"\bchanges\b", r"\bcompare\b", r"\bdiff\b", r"\brev(ision)? [abc]\b"]),
]


@dataclass
class PlannedTool:
    name: str
    args: dict[str, Any]
    why: str


@dataclass
class AgentContext:
    project_id: str | None = None
    revision_a: str | None = None
    revision_b: str | None = None
    analysis: dict[str, Any] | None = None
    component_id: str | None = None
    component_name: str = ""
    affected: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)


class AgentRunner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.gateway = ToolGateway(session)

    # ------------------------------------------------------------------ #
    def run(self, principal: Principal, req: ChatRequest) -> ChatResponse:
        with Timer() as t:
            session_row = self._session(principal, req)
            self.session.add(
                ChatMessage(id=new_id("msg"), session_id=session_row.id, role="user", content=req.message)
            )
            self.session.flush()

            ctx = self._context(req)
            intent = self._intent(req.message)
            plan = self._plan(intent, req, ctx)

            outputs: list[dict[str, Any]] = []
            calls: list[ToolCallRecord] = []
            evidence: list[EvidenceRef] = []
            for step in plan:
                res = self.gateway.execute(
                    step.name, step.args, principal, chat_session_id=session_row.id
                )
                calls.append(
                    ToolCallRecord(tool_name=res.tool, arguments=step.args, status=res.status,
                                   transport=res.transport, latency_ms=res.latency_ms,
                                   mutating=res.mutating,
                                   result_summary=_summarize(res.result) if res.ok else (res.error or ""),
                                   error=res.error, execution_id=res.execution_id)
                )
                if res.ok:
                    outputs.append({"tool": step.name, "why": step.why, "result": res.result})
                    evidence += _evidence_from(res.tool, res.result)

            pending: PendingAction | None = None
            insufficient = False
            if intent == "create_finding":
                pending, insufficient = self._propose_finding(principal, session_row, ctx, evidence, outputs)
                answer = self._answer_create(principal, ctx, evidence, pending, insufficient)
            elif intent == "update_status":
                answer = self._answer_update(req.message, outputs, evidence)
            else:
                answer, insufficient = self._compose(principal, req.message, intent, ctx, outputs, evidence)

            msg = ChatMessage(
                id=new_id("msg"), session_id=session_row.id, role="assistant", content=answer,
                structured_json={"intent": intent, "outputs": _truncate(outputs),
                                 "insufficient_evidence": insufficient},
                tool_calls_json=[c.model_dump() for c in calls],
                evidence_json=[e.model_dump() for e in evidence[:10]],
                pending_confirmation_id=pending.confirmation_id if pending else None,
                mode="live" if _live() else "demo",
                latency_ms=t.ms,
            )
            self.session.add(msg)
            self.session.flush()
            return ChatResponse(
                session_id=session_row.id, message_id=msg.id, answer=answer,
                structured={"intent": intent, "outputs": _truncate(outputs)},
                tool_calls=calls, evidence=evidence[:10], pending_action=pending,
                mode=msg.mode, grounded=bool(evidence), insufficient_evidence=insufficient,
                latency_ms=t.ms,
            )

    # ------------------------------------------------------------------ #
    def _session(self, principal: Principal, req: ChatRequest) -> ChatSession:
        if req.session_id:
            row = self.session.get(ChatSession, req.session_id)
            if row is None:
                raise NotFoundError(f"Chat session '{req.session_id}' not found.")
            return row
        row = ChatSession(
            id=new_id("chs"), project_id=req.project_id, user_id=principal.user_id,
            title=req.message[:80], context_json={"revision_a": req.revision_a, "revision_b": req.revision_b},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _context(self, req: ChatRequest) -> AgentContext:
        ctx = AgentContext(project_id=req.project_id, revision_a=req.revision_a, revision_b=req.revision_b)
        if ctx.project_id is None:
            proj = self.session.scalars(select(Project).order_by(Project.created_at)).first()
            ctx.project_id = proj.id if proj else None
        if not ctx.revision_a or not ctx.revision_b:
            revs = self.session.scalars(
                select(Revision).where(Revision.project_id == ctx.project_id).order_by(Revision.sequence)
            ).all()
            if len(revs) >= 2 and not (ctx.revision_a and ctx.revision_b):
                ctx.revision_a, ctx.revision_b = revs[-2].id, revs[-1].id
        run = None
        if req.analysis_id:
            run = self.session.get(AnalysisRun, req.analysis_id)
        else:
            run = self.session.scalars(
                select(AnalysisRun)
                .where(AnalysisRun.project_id == ctx.project_id, AnalysisRun.status == "completed")
                .order_by(AnalysisRun.created_at.desc())
            ).first()
        if run and run.result_json:
            ctx.analysis = run.result_json
            ctx.changes = run.result_json.get("changes", [])
            ctx.affected = run.result_json.get("affected_components", [])
        if req.component_id:
            ctx.component_id = req.component_id
        else:
            # explicit mention in the message wins, then the analysis' affected set
            names = {c.name.lower(): c.id for c in self.session.scalars(select(Component)).all()}
            mention = next((cid for name, cid in names.items() if name in req.message.lower()), None)
            if mention:
                ctx.component_id = mention
            elif ctx.affected:
                ctx.component_id = ctx.affected[0].get("component_id")
        if not ctx.component_id and ctx.project_id:
            proj = self.session.get(Project, ctx.project_id)
            ctx.component_id = (proj.metadata_json or {}).get("primary_component") if proj else None
        if ctx.component_id:
            comp = self.session.get(Component, ctx.component_id)
            ctx.component_name = comp.name if comp else ""
        return ctx

    @staticmethod
    def _intent(message: str) -> str:
        low = message.lower()
        for intent, patterns in _INTENT_PATTERNS:
            if any(re.search(p, low) for p in patterns):
                return intent
        return "general"

    def _plan(self, intent: str, req: ChatRequest, ctx: AgentContext) -> list[PlannedTool]:
        pid = ctx.project_id
        rev_args = {"revision_a": ctx.revision_a, "revision_b": ctx.revision_b} if ctx.revision_a else {}
        change_ctx = {"changes": [c.get("title", "") for c in ctx.changes[:4]]}
        plan: list[PlannedTool] = []

        if intent == "changes":
            if rev_args:
                plan.append(PlannedTool("compare_revisions", rev_args, "deterministic revision comparison"))
            if ctx.component_id:
                plan.append(PlannedTool("get_dependencies", {"component_id": ctx.component_id, "depth": 2},
                                        "dependency traversal for affected components"))
        elif intent == "dependencies":
            target = ctx.component_id or (ctx.affected[0].get("component_id") if ctx.affected else None)
            if target:
                plan.append(PlannedTool("get_dependencies", {"component_id": target, "depth": 2},
                                        "dependency traversal"))
            if rev_args:
                plan.append(PlannedTool("compare_revisions", rev_args, "changes feed the impact question"))
        elif intent == "why_impact":
            if ctx.component_id:
                plan.append(PlannedTool("get_component_properties",
                                        {"component_id": ctx.component_id}, "property deltas explain severity"))
                plan.append(PlannedTool("get_dependencies", {"component_id": ctx.component_id, "depth": 2},
                                        "impact propagation path"))
            plan.append(PlannedTool(
                "search_requirements",
                {"query": f"{ctx.component_name} limit clearance tolerance requirement",
                 "project_id": pid, "component_ids": [ctx.component_id] if ctx.component_id else [],
                 "revision": _rev_name(self.session, ctx.revision_b)},
                "normative evidence for the severity call"))
        elif intent == "requirements":
            plan.append(PlannedTool(
                "search_requirements",
                {"query": req.message, "project_id": pid,
                 "component_ids": [ctx.component_id] if ctx.component_id else [],
                 "revision": _rev_name(self.session, ctx.revision_b)},
                "retrieve applicable requirements"))
        elif intent == "evidence":
            plan.append(PlannedTool(
                "search_requirements",
                {"query": req.message, "project_id": pid,
                 "component_ids": [ctx.component_id] if ctx.component_id else []},
                "evidence lookup"))
            if pid:
                plan.append(PlannedTool("get_findings", {"project_id": pid}, "existing findings context"))
        elif intent == "findings":
            if pid:
                plan.append(PlannedTool("get_findings", {"project_id": pid}, "list findings"))
        elif intent == "history":
            if ctx.component_id:
                plan.append(PlannedTool("get_revision_history", {"component_id": ctx.component_id},
                                        "property history across revisions"))
        elif intent == "create_finding":
            if ctx.component_id:
                plan.append(PlannedTool("get_component", {"component_id": ctx.component_id},
                                        "component identity for the finding"))
            plan.append(PlannedTool(
                "search_requirements",
                {"query": f"{ctx.component_name} clearance limit requirement conflict",
                 "project_id": pid, "component_ids": [ctx.component_id] if ctx.component_id else [],
                 "revision": _rev_name(self.session, ctx.revision_b)},
                "evidence that must back the finding"))
        elif intent == "update_status":
            if pid:
                plan.append(PlannedTool("get_findings", {"project_id": pid}, "identify the finding"))
        else:
            if pid:
                plan.append(PlannedTool("get_project", {"project_id": pid}, "project context"))
            plan.append(PlannedTool("search_requirements", {"query": req.message, "project_id": pid},
                                    "best-effort retrieval"))
        return plan[:5]

    # ------------------------------------------------------------------ #
    def _propose_finding(self, principal, session_row, ctx: AgentContext, evidence: list[EvidenceRef],
                         outputs: list[dict]) -> tuple[PendingAction | None, bool]:
        insufficient = not evidence
        checks = [c for c in (ctx.analysis or {}).get("deterministic_checks", []) if c["result"] in ("fail", "flag")]
        proposals = (ctx.analysis or {}).get("proposed_findings", [])
        proposed = next((p for p in proposals if p.get("component_id") == ctx.component_id), None) \
            or (proposals[0] if proposals else None)
        if proposed and proposed.get("component_id"):
            ctx.component_id = proposed["component_id"]
            comp = self.session.get(Component, ctx.component_id)
            ctx.component_name = comp.name if comp else ctx.component_name
        title = (proposed or {}).get("title") or (
            f"Review: potential impact on {ctx.component_name or 'component'} after revision change"
        )
        failing = [c for c in checks if c["result"] == "fail"]
        severity = Severity.HIGH if failing else Severity.MEDIUM
        payload = FindingCreate(
            project_id=ctx.project_id or "",
            revision_id=ctx.revision_b,
            component_id=ctx.component_id,
            analysis_run_id=(ctx.analysis or {}).get("analysis_id"),
            title=title,
            severity=severity,
            confidence=round(min(0.95, 0.5 + 0.1 * len(evidence)), 2),
            description=(
                "Proposed by ARIADNE from revision analysis. "
                + (f"Deterministic checks: {', '.join(c['requirement_code'] + '=' + c['result'] for c in failing)}. "
                   if failing else "No deterministic limit violation; reviewer judgement required. ")
                + "Potential — not confirmed — impact; human decision required."
            ),
            recommendation="Verify mating geometry and clearance before approving the revision.",
            affected_component_ids=[a.get("component_id") for a in ctx.affected[:4] if a.get("component_id")],
            evidence=[
                FindingEvidenceIn(
                    evidence_type=e.evidence_type, document_id=e.document_id, chunk_id=e.chunk_id,
                    page=e.page, section=e.section, bbox=e.bbox, excerpt=e.excerpt[:500], score=e.score,
                )
                for e in evidence[:5]
            ],
            metadata={"proposed_by": "agent", "chat_session_id": session_row.id},
        )
        args = {"finding": payload.model_dump(mode="json")}
        conf = create_confirmation(
            self.session, principal=principal, tool="create_review_finding", args=args,
            action_label=f"Create review finding — {title[:70]}",
            summary=(
                f"Component: {ctx.component_name or ctx.component_id}. "
                f"Severity: {severity.value}. Evidence items: {len(evidence)}. "
                "ARIADNE never creates findings without explicit approval."
            ),
            evidence=[e.model_dump() for e in evidence[:5]],
            project_id=ctx.project_id,
        )
        return (
            PendingAction(
                confirmation_id=conf.id, tool_name="create_review_finding", action_label=conf.action_label,
                summary=conf.summary, payload=args, evidence=evidence[:5],
                affected=[{"component_id": a.get("component_id"), "name": a.get("name"),
                           "severity": a.get("severity")} for a in ctx.affected[:4]],
            ),
            insufficient,
        )

    # ------------------------------------------------------------------ #
    def _answer_create(self, principal, ctx, evidence, pending, insufficient) -> str:
        if insufficient:
            return ("Insufficient evidence to determine impact. I retrieved no supporting document for a "
                    "finding on this component, so I will not propose one. Run an analysis or point me at "
                    "the relevant specification.")
        checks = [c for c in (ctx.analysis or {}).get("deterministic_checks", []) if c["result"] == "fail"]
        lines = [
            "I found sufficient evidence to *propose* a review finding — nothing has been created yet.",
            "",
            f"Component: {ctx.component_name or ctx.component_id}",
            f"Potential issue: {('deterministic check ' + checks[0]['requirement_code'] + ' reports ' + checks[0]['result'].upper()) if checks else 'change classified as potentially consequential by the analysis'}",
            f"Evidence: {len(evidence)} item(s) — "
            + "; ".join(f"{e.document_name} §{e.section} p.{e.page}" for e in evidence[:3]),
            "",
            "Create the finding?",
        ]
        return "\n".join(lines)

    def _answer_update(self, message: str, outputs: list[dict], evidence: list[EvidenceRef]) -> str:
        findings = next((o["result"] for o in outputs if o["tool"] == "get_findings"), None)
        if not findings:
            return "I could not list findings for this project."
        m = re.search(r"\b(accept|reject|resolve|close)\w*", message.lower())
        verb = m.group(1) if m else "update"
        listing = ", ".join(f"{f['id']} ({f['status']}) {f['title'][:40]}" for f in findings["findings"][:5])
        return (f"To {verb} a finding I need your explicit confirmation with REVIEWER rights. Current "
                f"findings: {listing}. Tell me which id to {verb} and I will request confirmation.")

    def _compose(self, principal, message: str, intent: str, ctx: AgentContext, outputs: list[dict],
                 evidence: list[EvidenceRef]) -> tuple[str, bool]:
        if _live():
            return self._compose_llm(message, ctx, outputs, evidence)
        return self._compose_demo(message, intent, ctx, outputs, evidence)

    def _compose_demo(self, message: str, intent: str, ctx: AgentContext, outputs: list[dict],
                      evidence: list[EvidenceRef]) -> tuple[str, bool]:
        compare = next((o["result"] for o in outputs if o["tool"] == "compare_revisions"), None)
        deps = next((o["result"] for o in outputs if o["tool"] == "get_dependencies"), None)
        props = next((o["result"] for o in outputs if o["tool"] == "get_component_properties"), None)
        search = next((o["result"] for o in outputs if o["tool"] == "search_requirements"), None)
        checks = (ctx.analysis or {}).get("deterministic_checks", [])
        failing = [c for c in checks if c["result"] == "fail"]
        flagged = [c for c in checks if c["result"] == "flag"]

        if intent in ("changes", "dependencies", "general") and compare:
            changes = compare.get("changes", [])
            consequential = [c for c in changes if c["change_type"] not in ("METADATA_CHANGE",)]
            lines = [
                f"Comparing {compare['revision_a']} → {compare['revision_b']} "
                f"({compare['method']}): {len(changes)} change(s), "
                f"{len(consequential)} potentially consequential.",
            ]
            for i, c in enumerate(changes[:6], 1):
                lines.append(f"{i}. {c['title']}  [{c['change_type']}, conf {c['confidence']}]")
            if deps:
                lines.append(
                    "Potentially affected (graph, ≤2 hops): "
                    + ", ".join(n["label"] for n in deps["nodes"] if n["direction"] != "root")
                    or "none"
                )
            if failing:
                lines.append("Deterministic checks FAILED: "
                             + "; ".join(f"{c['requirement_code']} margin {c['margin']}{c['unit']}" for c in failing))
            elif flagged:
                lines.append("Deterministic checks flagged: " + ", ".join(c["requirement_code"] for c in flagged))
            if evidence:
                lines.append("Evidence: " + "; ".join(f"{e.document_name} §{e.section} p.{e.page}" for e in evidence[:4]))
            lines.append("[demo mode — deterministic analysis, no LLM inference]")
            return "\n".join(lines), False

        if intent == "why_impact":
            snaps = (props or {}).get("snapshots", [])
            lines = [f"Why {ctx.component_name or 'the component'} is rated high impact:"]
            for c in failing:
                lines.append(f"- {c['requirement_code']} ({c['rule']}): FAIL — inputs {c['inputs']}, "
                             f"margin {c['margin']}{c['unit']}. This is a computed limit violation.")
            for c in flagged:
                lines.append(f"- {c['requirement_code']} ({c['rule']}): flagged — inputs {c['inputs']}.")
            if deps:
                lines.append("- Propagation: " + ", ".join(
                    f"{n['label']} ({n['direction']}, {n['depth']} hop)" for n in deps["nodes"]
                    if n["direction"] != "root")[:400])
            if snaps:
                lines.append(f"- Property snapshots available: {len(snaps)}.")
            if evidence:
                lines.append("- Governing text: " + "; ".join(
                    f"{e.document_name} §{e.section} p.{e.page}" for e in evidence[:3]))
            if not failing and not flagged:
                lines.append("- No deterministic violation computed; the rating reflects interface criticality "
                             "and change magnitude, not a confirmed breach.")
            lines.append("[demo mode — deterministic analysis, no LLM inference]")
            return "\n".join(lines), not (failing or flagged or evidence)

        if search is not None:
            results = search.get("results", [])
            if not results:
                return ("Insufficient evidence to determine impact: retrieval returned nothing above the "
                        "relevance floor for this query."), True
            lines = [f"Retrieved {len(results)} evidence item(s) with strategy '{search['strategy']}':"]
            for r in results[:5]:
                tag = " [QUARANTINED — excluded from synthesis]" if r.get("quarantined") else ""
                lines.append(f"- {r['document']} §{r['section']} p.{r['page']} (score {r['score']}): "
                             f"{r['text'][:160]}…{tag}")
            lines.append("[demo mode — deterministic retrieval, no LLM inference]")
            return "\n".join(lines), False

        return ("I have no grounded answer for that in the current context. Ask about changes, affected "
                "components, dependencies, requirements or findings."), True

    def _compose_llm(self, message: str, ctx: AgentContext, outputs: list[dict],
                     evidence: list[EvidenceRef]) -> tuple[str, bool]:
        from app.services.llm import prompts
        from app.services.llm.base import LLMMessage, get_llm_provider

        llm = get_llm_provider()
        resp = llm.generate(
            [
                LLMMessage(role="system", content=prompts.SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompts.answer_prompt(
                    message,
                    [{"tool": o["tool"], "result": _truncate(o["result"])} for o in outputs],
                    [e.model_dump(mode="json") for e in evidence[:8]],
                    {"project_id": ctx.project_id, "revision_b": ctx.revision_b,
                     "component": ctx.component_name},
                )),
            ],
            json_schema=prompts.ANSWER_SCHEMA,
        )
        data = resp.structured or {"answer": resp.text, "insufficient_evidence": False, "citations": []}
        allowed = {e.document_name for e in evidence} | {c["requirement_code"] for c in
                                                         (ctx.analysis or {}).get("deterministic_checks", [])}
        citations = [c for c in data.get("citations", []) if any(a and a in c for a in allowed)] or []
        answer = data.get("answer", "")
        if citations:
            answer += "\n\nCitations: " + ", ".join(citations)
        return answer, bool(data.get("insufficient_evidence")) or not evidence


def _rev_name(session: Session, revision_id: str | None) -> str | None:
    if not revision_id:
        return None
    rev = session.get(Revision, revision_id)
    return rev.name if rev else None


def _evidence_from(tool: str, result: dict) -> list[EvidenceRef]:
    if tool != "search_requirements":
        return []
    out = []
    for r in result.get("results", []):
        if r.get("quarantined"):
            continue
        out.append(
            EvidenceRef(
                evidence_id=r.get("chunk_id", ""), evidence_type="document", document_id=r.get("document_id"),
                document_name=r.get("document", ""), chunk_id=r.get("chunk_id"), page=r.get("page"),
                section=r.get("section", ""), excerpt=r.get("text", ""), score=r.get("score", 0.0),
                authority=r.get("authority", "synthetic"), retrieval_strategy=result.get("strategy", ""),
            )
        )
    return out


def _summarize(result: dict) -> str:
    text = json.dumps(result, default=str)
    return text[:300]


def _truncate(obj: Any, limit: int = 4000) -> Any:
    text = json.dumps(obj, default=str)
    return obj if len(text) <= limit else {"truncated": True, "preview": text[:limit]}


def _live() -> bool:
    from app.services.llm.base import is_live

    return is_live()
