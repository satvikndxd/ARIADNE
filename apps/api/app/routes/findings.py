"""Finding endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import Finding
from app.schemas.domain import FindingCreate, FindingOut, FindingUpdate
from app.services import findings as svc

router = APIRouter(tags=["findings"])


@router.get("/findings", response_model=list[FindingOut])
def list_findings(project_id: str | None = Query(default=None), status: str | None = Query(default=None),
                  component_id: str | None = Query(default=None),
                  session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    return [svc.to_out(session, f) for f in svc.list_findings(session, project_id, status, component_id)]


@router.get("/findings/counts")
def finding_counts(project_id: str | None = Query(default=None),
                   session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    rows = svc.list_findings(session, project_id)
    return {
        "open": sum(1 for f in rows if f.status == "open"),
        "needs_review": sum(1 for f in rows if f.status == "needs_review"),
        "accepted": sum(1 for f in rows if f.status == "accepted"),
        "rejected": sum(1 for f in rows if f.status == "rejected"),
        "resolved": sum(1 for f in rows if f.status == "resolved"),
        "total": len(rows),
    }


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: str, session: Session = Depends(get_session),
                principal: Principal = Depends(current_principal)):
    f = session.get(Finding, finding_id)
    if f is None:
        raise NotFoundError(f"Finding '{finding_id}' not found.")
    return svc.to_out(session, f)


@router.post("/findings", response_model=FindingOut, status_code=201)
def create_finding(payload: FindingCreate, session: Session = Depends(get_session),
                   principal: Principal = Depends(current_principal)):
    f = svc.create_finding(session, payload, principal, source=payload.source or "manual")
    session.commit()
    return svc.to_out(session, f)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def patch_finding(finding_id: str, patch: FindingUpdate, session: Session = Depends(get_session),
                  principal: Principal = Depends(current_principal)):
    f = svc.update_finding(session, finding_id, patch, principal)
    session.commit()
    return svc.to_out(session, f)
