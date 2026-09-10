"""Project / revision endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import AnalysisRun, Component, Drawing, Finding, Project, Revision
from app.schemas.domain import DrawingOut, ProjectOut, RevisionOut

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    out = []
    for p in session.scalars(select(Project).order_by(Project.created_at)).all():
        dto = ProjectOut.model_validate(p)
        dto.stats = {
            "revisions": session.scalar(select(func.count(Revision.id)).where(Revision.project_id == p.id)) or 0,
            "components": session.scalar(select(func.count(Component.id)).where(Component.project_id == p.id)) or 0,
            "findings": session.scalar(select(func.count(Finding.id)).where(Finding.project_id == p.id)) or 0,
            "analyses": session.scalar(select(func.count(AnalysisRun.id)).where(AnalysisRun.project_id == p.id)) or 0,
        }
        out.append(dto)
    return out


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session),
                principal: Principal = Depends(current_principal)):
    p = session.get(Project, project_id)
    if p is None:
        raise NotFoundError(f"Project '{project_id}' not found.")
    dto = ProjectOut.model_validate(p)
    dto.stats = {
        "revisions": session.scalar(select(func.count(Revision.id)).where(Revision.project_id == p.id)) or 0,
        "components": session.scalar(select(func.count(Component.id)).where(Component.project_id == p.id)) or 0,
        "findings": session.scalar(select(func.count(Finding.id)).where(Finding.project_id == p.id)) or 0,
        "analyses": session.scalar(select(func.count(AnalysisRun.id)).where(AnalysisRun.project_id == p.id)) or 0,
        "open_findings": session.scalar(
            select(func.count(Finding.id)).where(Finding.project_id == p.id, Finding.status.in_(["open", "needs_review"]))
        ) or 0,
    }
    return dto


@router.get("/projects/{project_id}/revisions", response_model=list[RevisionOut])
def list_revisions(project_id: str, session: Session = Depends(get_session),
                   principal: Principal = Depends(current_principal)):
    revs = session.scalars(
        select(Revision).where(Revision.project_id == project_id).order_by(Revision.sequence)
    ).all()
    out = []
    for r in revs:
        dto = RevisionOut.model_validate(r)
        dto.drawings = [_drawing_out(d) for d in r.drawings]
        out.append(dto)
    return out


@router.get("/projects/{project_id}/overview")
def project_overview(project_id: str, session: Session = Depends(get_session),
                     principal: Principal = Depends(current_principal)):
    p = session.get(Project, project_id)
    if p is None:
        raise NotFoundError(f"Project '{project_id}' not found.")
    revs = session.scalars(select(Revision).where(Revision.project_id == project_id).order_by(Revision.sequence)).all()
    findings = session.scalars(select(Finding).where(Finding.project_id == project_id)).all()
    runs = session.scalars(
        select(AnalysisRun).where(AnalysisRun.project_id == project_id).order_by(AnalysisRun.created_at.desc())
    ).all()
    latest = runs[0] if runs else None
    unresolved = [c for c in (latest.result_json.get("changes", []) if latest and latest.result_json else [])]
    return {
        "project": ProjectOut.model_validate(p).model_dump(),
        "revision_count": len(revs),
        "active_revision": revs[-1].name if revs else None,
        "findings_total": len(findings),
        "findings_by_status": {s: sum(1 for f in findings if f.status == s)
                               for s in ("open", "needs_review", "accepted", "rejected", "resolved")},
        "affected_components": sorted({a.get("name") for a in
                                       (latest.result_json or {}).get("affected_components", [])}),
        "unresolved_changes": len([u for u in unresolved if u.get("classification") == "consequential"]),
        "latest_analysis": {
            "id": latest.id, "status": latest.status, "mode": latest.mode, "created_at": latest.created_at,
            "summary": latest.summary_json,
        } if latest else None,
        "recent_activity": [
            {"id": r.id, "status": r.status, "created_at": r.created_at, "mode": r.mode} for r in runs[:5]
        ],
    }


def _drawing_out(d: Drawing) -> DrawingOut:
    dto = DrawingOut.model_validate(d)
    dto.image_url = f"/drawings/{d.storage_path.split('data/drawings/')[-1]}"
    return dto
