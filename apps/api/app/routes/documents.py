"""Document / knowledge endpoints."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import Document, DocumentChunk, Requirement
from app.schemas.domain import DocumentOut, RequirementOut

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(project_id: str | None = Query(default=None),
                   session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    stmt = select(Document).order_by(Document.title)
    if project_id:
        stmt = stmt.where(Document.project_id == project_id)
    out = []
    for d in session.scalars(stmt).all():
        dto = DocumentOut.model_validate(d)
        dto.chunk_count = session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == d.id)) or 0
        out.append(dto)
    return out


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: Session = Depends(get_session),
                 principal: Principal = Depends(current_principal)):
    d = session.get(Document, document_id)
    if d is None:
        raise NotFoundError(f"Document '{document_id}' not found.")
    dto = DocumentOut.model_validate(d)
    dto.chunk_count = len(d.chunks)
    return dto


@router.get("/documents/{document_id}/chunks")
def document_chunks(document_id: str, session: Session = Depends(get_session),
                    principal: Principal = Depends(current_principal)):
    d = session.get(Document, document_id)
    if d is None:
        raise NotFoundError(f"Document '{document_id}' not found.")
    return {"chunks": [
        {"id": c.id, "page": c.page, "section": c.section, "text": c.text, "bbox": c.bbox_json,
         "token_count": c.token_count, "metadata": c.metadata_json}
        for c in sorted(d.chunks, key=lambda c: (c.page, c.chunk_index))]}


@router.get("/documents/{document_id}/layout")
def document_layout(document_id: str, session: Session = Depends(get_session),
                    principal: Principal = Depends(current_principal)):
    """Page geometry for the document viewer (block bboxes in PDF points)."""
    d = session.get(Document, document_id)
    if d is None:
        raise NotFoundError(f"Document '{document_id}' not found.")
    slug = Path(d.source).stem if d.source else d.id
    sidecar = settings.documents_dir / f"{slug}.layout.json"
    if not sidecar.exists():
        raise NotFoundError("No layout sidecar for this document.")
    return json.loads(sidecar.read_text())


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(project_id: str | None = Query(default=None), component_id: str | None = Query(default=None),
                      session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    stmt = select(Requirement).order_by(Requirement.code)
    if project_id:
        stmt = stmt.where(Requirement.project_id == project_id)
    rows = list(session.scalars(stmt).all())
    if component_id:
        rows = [r for r in rows if component_id in (r.applies_to_json or [])]
    titles = {d.id: d.title for d in session.scalars(select(Document)).all()}
    out = []
    for r in rows:
        dto = RequirementOut.model_validate(r)
        dto.document_title = titles.get(r.document_id, "")
        out.append(dto)
    return out
