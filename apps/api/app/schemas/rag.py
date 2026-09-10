"""RAG request/response schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceRef

RetrievalStrategy = Literal["keyword", "vector", "metadata_aware", "revision_aware", "hybrid"]


class RetrievalFilters(BaseModel):
    project_id: str | None = None
    component_ids: list[str] = Field(default_factory=list)
    revision: str | None = None
    document_types: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    authority: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    strategy: RetrievalStrategy = "revision_aware"
    top_k: int = Field(default=8, ge=1, le=50)
    rerank_top_n: int = Field(default=5, ge=1, le=25)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    change_context: dict[str, Any] = Field(default_factory=dict)
    compare_strategies: bool = False


class ScoredChunk(EvidenceRef):
    rank: int = 0
    raw_score: float = 0.0
    rerank_score: float = 0.0
    lexical_score: float = 0.0
    dense_score: float = 0.0
    metadata_boost: float = 0.0
    text: str = ""
    token_count: int = 0
    requirement_code: str | None = None


class StrategyResult(BaseModel):
    strategy: str
    results: list[ScoredChunk] = Field(default_factory=list)
    latency_ms: float = 0.0
    candidate_count: int = 0


class SearchResponse(BaseModel):
    query: str
    strategy: str
    results: list[ScoredChunk] = Field(default_factory=list)
    comparison: list[StrategyResult] = Field(default_factory=list)
    planned_queries: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    embedding_provider: str = ""
    empty: bool = False
    notice: str = ""


class QueryPlan(BaseModel):
    """Structured retrieval dimensions — never just 'send the question'."""

    component: str = ""
    change: str = ""
    relationship: str = ""
    query: str = ""
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    sub_queries: list[str] = Field(default_factory=list)
    revision_scoped: bool = False
    rationale: str = ""
