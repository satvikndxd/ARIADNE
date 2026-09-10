"""Component endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import Component, ComponentRevision, Finding
from app.schemas.domain import ComponentOut
from app.services.graph import get_graph_store

router = APIRouter(tags=["components"])


def _component_out(session: Session, c: Component, revision_id: str | None = None) -> ComponentOut:
    dto = ComponentOut.model_validate(c)
    snap = None
    if revision_id:
        snap = session.scalars(
            select(ComponentRevision).where(ComponentRevision.component_id == c.id,
                                            ComponentRevision.revision_id == revision_id)
        ).first()
    if snap is None:
        snap = session.scalars(
            select(ComponentRevision).where(ComponentRevision.component_id == c.id)
            .order_by(ComponentRevision.revision_id.desc())
        ).first()
    dto.properties = dict(snap.properties_json or {}) if snap else {}
    dto.revision_id = snap.revision_id if snap else None
    dto.finding_count = len(session.scalars(select(Finding).where(Finding.component_id == c.id)).all())
    return dto


@router.get("/components", response_model=list[ComponentOut])
def list_components(project_id: str | None = Query(default=None),
                    session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    stmt = select(Component).order_by(Component.name)
    if project_id:
        stmt = stmt.where(Component.project_id == project_id)
    return [_component_out(session, c) for c in session.scalars(stmt).all()]


@router.get("/components/{component_id}", response_model=ComponentOut)
def get_component(component_id: str, revision_id: str | None = Query(default=None),
                  session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    c = session.get(Component, component_id)
    if c is None:
        raise NotFoundError(f"Component '{component_id}' not found.")
    return _component_out(session, c, revision_id)


@router.get("/components/{component_id}/dependencies")
def dependencies(component_id: str, depth: int = Query(default=2, ge=1, le=4),
                 session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    if session.get(Component, component_id) is None:
        raise NotFoundError(f"Component '{component_id}' not found.")
    return get_graph_store().graph_view(session, component_id, depth).model_dump()


@router.get("/components/{component_id}/revision-history")
def revision_history(component_id: str, session: Session = Depends(get_session),
                     principal: Principal = Depends(current_principal)):
    rows = session.scalars(
        select(ComponentRevision).where(ComponentRevision.component_id == component_id)
    ).all()
    ordered = sorted(rows, key=lambda r: r.revision_id)
    deltas = []
    for prev, cur in zip(ordered, ordered[1:]):
        deltas.append({
            "revision_id": cur.revision_id,
            "changed_properties": {
                k: {"old": prev.properties_json.get(k), "new": cur.properties_json.get(k)}
                for k in set(prev.properties_json) | set(cur.properties_json)
                if prev.properties_json.get(k) != cur.properties_json.get(k)
            },
        })
    return {"component_id": component_id, "snapshots": [
        {"revision_id": r.revision_id, "properties": r.properties_json} for r in ordered], "deltas": deltas}
