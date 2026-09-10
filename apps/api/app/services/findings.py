"""Finding lifecycle with server-side authorization."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.ids import new_id, utcnow
from app.core.security import Permission, Principal, authorize
from app.db.models import Component, Finding, FindingComponent, FindingEvidence
from app.schemas.common import BoundingBox
from app.schemas.domain import FindingCreate, FindingOut, FindingUpdate, FindingEvidenceOut
from app.services.audit import record

_VALID_TRANSITIONS = {
    "open": {"needs_review", "accepted", "rejected", "resolved"},
    "needs_review": {"accepted", "rejected", "resolved", "open"},
    "accepted": {"resolved"},
    "rejected": set(),
    "resolved": set(),
}


def to_out(session: Session, f: Finding) -> FindingOut:
    comp = session.get(Component, f.component_id) if f.component_id else None
    return FindingOut(
        id=f.id, project_id=f.project_id, revision_id=f.revision_id, component_id=f.component_id,
        analysis_run_id=f.analysis_run_id, change_id=f.change_id, title=f.title, severity=f.severity,
        confidence=f.confidence, description=f.description, recommendation=f.recommendation, status=f.status,
        source=f.source, created_by=f.created_by, reviewed_by=f.reviewed_by, resolution_note=f.resolution_note,
        metadata_json=f.metadata_json, created_at=f.created_at, updated_at=f.updated_at,
        evidence=[
            FindingEvidenceOut(
                id=e.id, evidence_type=e.evidence_type, document_id=e.document_id, chunk_id=e.chunk_id,
                page=e.page, section=e.section,
                bbox=BoundingBox(**e.bbox_json) if e.bbox_json else None,
                excerpt=e.excerpt, score=e.score,
            ).model_dump()
            for e in f.evidence
        ],
        affected_component_ids=[fc.component_id for fc in f.affected_components],
        component_name=comp.name if comp else "",
    )


def create_finding(session: Session, payload: FindingCreate, principal: Principal, *, source: str = "manual") -> Finding:
    authorize(principal.role, Permission.CREATE_FINDING, context={"action": "create_finding"})
    if not payload.evidence and source != "manual":
        raise ValidationError("Agent-created findings must carry at least one evidence reference.")
    f = Finding(
        id=new_id("fd"), project_id=payload.project_id, revision_id=payload.revision_id,
        component_id=payload.component_id, analysis_run_id=payload.analysis_run_id,
        change_id=payload.change_id, title=payload.title, severity=payload.severity.value,
        confidence=payload.confidence, description=payload.description, recommendation=payload.recommendation,
        status=payload.status.value, source=source, created_by=principal.user_id,
        metadata_json={**payload.metadata, "created_via": "api"},
    )
    session.add(f)
    session.flush()
    for ev in payload.evidence:
        session.add(
            FindingEvidence(
                id=new_id("fev"), finding_id=f.id, evidence_type=ev.evidence_type, document_id=ev.document_id,
                chunk_id=ev.chunk_id, page=ev.page, section=ev.section,
                bbox_json=ev.bbox.model_dump() if ev.bbox else None, excerpt=ev.excerpt, score=ev.score,
            )
        )
    for cid in dict.fromkeys([payload.component_id, *payload.affected_component_ids]):
        if cid:
            session.add(FindingComponent(id=new_id("flk"), finding_id=f.id, component_id=cid, role="affected"))
    session.flush()
    record(session, principal=principal, action="finding.create", entity_type="finding", entity_id=f.id,
           arguments={"title": f.title, "severity": f.severity, "source": source},
           result_summary=f"finding {f.id} created")
    return f


def update_finding(session: Session, finding_id: str, patch: FindingUpdate, principal: Principal) -> Finding:
    f = session.get(Finding, finding_id)
    if f is None:
        raise NotFoundError(f"Finding '{finding_id}' not found.")
    if patch.status is not None:
        return update_status(session, finding_id, patch.status.value, principal, note=patch.resolution_note or "")
    authorize(principal.role, Permission.CREATE_FINDING, context={"action": "finding.update"})
    for field_name in ("title", "description", "recommendation"):
        value = getattr(patch, field_name)
        if value is not None:
            setattr(f, field_name, value)
    if patch.severity is not None:
        f.severity = patch.severity.value
    f.updated_at = utcnow()
    session.flush()
    record(session, principal=principal, action="finding.update", entity_type="finding", entity_id=f.id,
           result_summary="finding updated")
    return f


def update_status(session: Session, finding_id: str, status: str, principal: Principal, *, note: str = "") -> Finding:
    f = session.get(Finding, finding_id)
    if f is None:
        raise NotFoundError(f"Finding '{finding_id}' not found.")
    authorize(principal.role, Permission.UPDATE_FINDING, context={"action": "finding.status", "finding": finding_id})
    allowed = _VALID_TRANSITIONS.get(f.status, set())
    if status not in allowed:
        raise ValidationError(f"Illegal status transition {f.status} → {status}.",
                              detail={"allowed": sorted(allowed)})
    f.status = status
    f.reviewed_by = principal.user_id
    f.resolution_note = note or f.resolution_note
    f.updated_at = utcnow()
    session.flush()
    record(session, principal=principal, action="finding.status", entity_type="finding", entity_id=f.id,
           arguments={"status": status}, result_summary=f"finding {finding_id} → {status}")
    return f


def list_findings(session: Session, project_id: str | None = None, status: str | None = None,
                  component_id: str | None = None) -> list[Finding]:
    stmt = select(Finding).order_by(Finding.created_at.desc())
    if project_id:
        stmt = stmt.where(Finding.project_id == project_id)
    if status:
        stmt = stmt.where(Finding.status == status)
    if component_id:
        stmt = stmt.where(Finding.component_id == component_id)
    return list(session.scalars(stmt).all())


def build_evidence_chain(session: Session, f: Finding) -> list[dict]:
    """Explicit trace: change → component → dependency → requirement →
    evidence → deterministic check → explanation → human review."""
    from app.db.models import AnalysisRun, Component, Requirement
    from app.services.graph import get_graph_store

    chain: list[dict] = []
    run = session.get(AnalysisRun, f.analysis_run_id) if f.analysis_run_id else None
    result = (run.result_json or {}) if run else {}
    changes = [c for c in result.get("changes", [])
               if c.get("component_id") == f.component_id and c.get("classification") == "consequential"]
    for c in changes[:4]:
        chain.append({"type": "change", "id": c.get("id"), "label": c.get("title"),
                      "detail": f"{c.get('change_type')} · {c.get('detection_method')} · "
                                f"consensus {(c.get('metadata') or {}).get('signals', {}).get('status', 'n/a')}"})
    comp = session.get(Component, f.component_id) if f.component_id else None
    if comp:
        chain.append({"type": "component", "id": comp.id, "label": comp.name,
                      "detail": f"{comp.subsystem or comp.type} · {comp.material or 'n/a'}"})
    if comp:
        view = get_graph_store().graph_view(session, comp.id, 2)
        deps = [f"{n.label} ({n.direction}, {n.depth} hop)" for n in view.nodes if n.direction != "root"]
        chain.append({"type": "dependency", "id": comp.id, "label": "dependency neighbourhood",
                      "detail": "; ".join(deps[:6]) or "isolated",
                      "link": f"/components/{comp.id}"})
    codes = {e.get("requirement_code") for e in result.get("deterministic_checks", [])}
    reqs = [r for r in session.query(Requirement).all()
            if r.code in codes and comp and comp.id in (r.applies_to_json or [])]
    for r in reqs[:4]:
        chk = next((c for c in result.get("deterministic_checks", []) if c["requirement_code"] == r.code), None)
        chain.append({"type": "requirement", "id": r.id, "label": r.code,
                      "detail": f"§{r.section} p.{r.page} · deterministic check: "
                                f"{chk['result'] if chk else 'n/a'}"})
    for e in f.evidence[:5]:
        chain.append({"type": "evidence", "id": e.id,
                      "label": e.document_id or e.evidence_type,
                      "detail": f"{e.evidence_type} · §{e.section or '—'} p.{e.page or '—'} · "
                                f"{(e.excerpt or '')[:80]}"})
    for c in result.get("deterministic_checks", []):
        if c["result"] in ("fail", "flag"):
            chain.append({"type": "check", "id": c["requirement_code"], "label": c["requirement_code"],
                          "detail": f"{c['rule']} → {c['result'].upper()} · inputs {c['inputs']} · "
                                    f"margin {c['margin']}{c['unit']}"})
    insight = result.get("insight") or {}
    if insight:
        chain.append({"type": "explanation", "id": run.id if run else None,
                      "label": f"LLM explanation ({insight.get('mode', 'n/a')})",
                      "detail": (insight.get("potential_impact") or "")[:200]})
    chain.append({"type": "review", "id": f.id, "label": f"human review: {f.status}",
                  "detail": f"created by {f.created_by} · reviewed by {f.reviewed_by or '—'} · "
                            f"source {f.source}"})
    return chain
