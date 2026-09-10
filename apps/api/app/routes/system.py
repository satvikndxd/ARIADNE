"""Health + capability discovery (the UI shows exactly what is live)."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import DocumentChunk, VectorRecord
from app.services.llm.base import get_llm_provider
from app.services.rag.embeddings import embedding_backend_report
from app.services.rag.vector_store import get_vector_store
from app.services.graph import get_graph_store
from app.services.vision.providers import get_vision_provider, vision_active
from app.services.agent.gateway import mcp_healthy

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "service": settings.service_name, "env": settings.ariadne_env}


@router.get("/system/status")
def status():
    with SessionLocal() as session:
        chunks = session.scalar(select(func.count(DocumentChunk.id))) or 0
        vectors = session.scalar(select(func.count(VectorRecord.id))) or 0
    return {
        "demo_mode": settings.demo_mode,
        "llm": {"provider": get_llm_provider().name, "live": bool(settings.llm_configured),
                "model": settings.llm_model},
        "embeddings": {**embedding_backend_report(), "dim": settings.embedding_dim,
                       "live": bool(settings.embeddings_configured)},
        "vision": {"enabled": settings.vision_enabled, "model": settings.vision_model,
                   "provider": get_vision_provider().name, "active": vision_active()},
        "vector_store": get_vector_store().name,
        "graph_store": get_graph_store().name,
        "mcp": {"enabled": settings.mcp_enabled, "url": settings.mcp_server_url, "healthy": mcp_healthy()},
        "knowledge": {"chunks": chunks, "vectors": vectors},
        "database": "sqlite" if settings.is_sqlite else "postgresql",
    }
