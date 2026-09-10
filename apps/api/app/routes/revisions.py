"""Revision + comparison endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import Revision
from app.routes.projects import _drawing_out
from app.schemas.analysis import RevisionComparison
from app.schemas.analysis import ChangeOut
from app.schemas.common import ChangeClassification, Severity
from app.schemas.domain import RevisionOut
from app.services.analysis.revision_analyzer import get_revision_analyzer

router = APIRouter(tags=["revisions"])


@router.get("/revisions/compare", response_model=RevisionComparison)
def compare(revision_a: str = Query(...), revision_b: str = Query(...),
            session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    ra, rb = session.get(Revision, revision_a), session.get(Revision, revision_b)
    if ra is None or rb is None:
        raise NotFoundError("Revision not found.")
    out = get_revision_analyzer().analyze(session, ra, rb)
    changes = [
        ChangeOut(
            id=c.semantic, change_type=c.change_type, component_id=c.component_id, title=c.title,
            old_value=c.old_value, new_value=c.new_value, unit=c.unit, numeric_delta=c.numeric_delta,
            location=c.location, confidence=c.confidence, severity=Severity.MEDIUM,
            classification=ChangeClassification.COSMETIC if c.change_type.value == "METADATA_CHANGE"
            else ChangeClassification.CONSEQUENTIAL,
            detection_method=c.detection_method, description=c.description, drawing_id=c.drawing_id,
            revision_a=ra.name, revision_b=rb.name,
            metadata={**c.metadata, "cv_confirmed": c.cv_confirmed, "kind": c.kind},
        )
        for c in out.changes
    ]
    da = next((d for d in ra.drawings if (d.metadata_json or {}).get("drawing_kind") == "part"), None)
    db = next((d for d in rb.drawings if (d.metadata_json or {}).get("drawing_kind") == "part"), None)
    return RevisionComparison(
        project_id=ra.project_id,
        revision_a={"id": ra.id, "name": ra.name, "date": ra.metadata_json.get("date")},
        revision_b={"id": rb.id, "name": rb.name, "date": rb.metadata_json.get("date")},
        drawing_a=_drawing_out(da).model_dump() if da else None,
        drawing_b=_drawing_out(db).model_dump() if db else None,
        changes=changes,
        alignment=out.alignment,
    )


@router.get("/revisions/{revision_id}", response_model=RevisionOut)
def get_revision(revision_id: str, session: Session = Depends(get_session),
                 principal: Principal = Depends(current_principal)):
    rev = session.get(Revision, revision_id)
    if rev is None:
        raise NotFoundError(f"Revision '{revision_id}' not found.")
    dto = RevisionOut.model_validate(rev)
    dto.drawings = [_drawing_out(d) for d in rev.drawings]
    return dto


