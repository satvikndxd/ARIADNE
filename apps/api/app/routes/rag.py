"""RAG search endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.schemas.rag import SearchRequest, SearchResponse
from app.services.rag import retriever

router = APIRouter(tags=["rag"])


@router.post("/rag/search", response_model=SearchResponse)
def search(req: SearchRequest, session: Session = Depends(get_session),
           principal: Principal = Depends(current_principal)):
    return retriever.search(session, req)
