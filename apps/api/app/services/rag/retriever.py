"""Retrieval engine: strategies, fusion, reranking, provenance.

Strategies (each measurable, each reported):

``keyword``        BM25 only                                  — baseline A
``vector``         dense only, no metadata, no filters       — baseline B
``metadata_aware`` dense + metadata predicate + boost
``revision_aware`` multi-query RRF + metadata + revision salience  — proposed
``hybrid``         RRF(keyword, metadata_aware)

Every returned chunk keeps document / page / section / bbox provenance and a
quarantine flag produced by ``core.content_security``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import Timer, get_logger
from app.db.models import Document, DocumentChunk
from app.schemas.common import BoundingBox, EvidenceRef
from app.schemas.rag import ScoredChunk, SearchRequest, SearchResponse, StrategyResult
from app.services.rag import rerank as rerank_mod
from app.services.rag.embeddings import get_embedding_provider, tokenize
from app.services.rag.lexical import BM25Index
from app.services.rag.query_planner import plan_retrieval
from app.services.rag.vector_store import CHUNK_STORE, get_vector_store

log = get_logger(__name__)

RRF_K = 60


@dataclass
class Candidate:
    chunk: DocumentChunk
    payload: dict
    text: str


def _candidates(session: Session, project_id: str | None) -> list[Candidate]:
    rows = list(
        session.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id))
        .tuples()
        .all()
    )
    out: list[Candidate] = []
    for chunk, doc in rows:
        if project_id and doc.project_id not in (project_id, None):
            continue
        meta = chunk.metadata_json or {}
        bbox = chunk.bbox_json
        out.append(
            Candidate(
                chunk=chunk,
                text=chunk.text,
                payload={
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "document_name": doc.title,
                    "document_type": chunk.document_type or doc.document_type,
                    "authority": doc.authority,
                    "page": chunk.page,
                    "section": chunk.section,
                    "bbox": bbox,
                    "component_ids": meta.get("component_ids", []),
                    "revision": meta.get("revision"),
                    "verified": meta.get("verified_against_pdf", True),
                    "requirement_code": meta.get("requirement_code"),
                    "text": chunk.text,
                },
            )
        )
    return out


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return scores
    lo, hi = min(scores.values()), max(scores.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _dense_scores(session: Session, cands: list[Candidate], query: str, predicate) -> dict[str, float]:
    provider = get_embedding_provider()
    q = provider.embed_query(query)
    hits = get_vector_store().search(session, CHUNK_STORE, q, max(len(cands), 1), predicate=predicate)
    return {ref: score for ref, _payload, score in hits}


def _rrf(rankings: list[list[str]]) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, ref in enumerate(ranking):
            fused[ref] = fused.get(ref, 0.0) + 1.0 / (RRF_K + rank + 1)
    return fused


def search(session: Session, req: SearchRequest) -> SearchResponse:
    t0 = time.perf_counter()
    provider = get_embedding_provider()
    revision = req.filters.revision
    focus = list(req.filters.component_ids)

    with Timer() as t_plan:
        plan = plan_retrieval(
            session,
            req.query,
            project_id=req.filters.project_id or req.project_id,
            component_ids=focus or None,
            revision=revision,
            change_context=req.change_context,
        )
    effective_focus = focus or [
        cid for cid in _mentioned_components(session, req.query)
    ]

    cands = _candidates(session, req.filters.project_id or req.project_id)
    if not cands:
        return SearchResponse(
            query=req.query, strategy=req.strategy, results=[], empty=True,
            notice="The knowledge base is empty. Run scripts/seed.py first.",
        )

    def predicate(payload: dict) -> bool:
        if req.filters.document_types and payload.get("document_type") not in req.filters.document_types:
            return False
        if req.filters.authority and payload.get("authority") != req.filters.authority:
            return False
        return True

    with Timer() as t_ret:
        dense_single = _dense_scores(session, cands, plan.query, predicate)
        bm25 = BM25Index().build([(c.chunk.id, c.payload, c.text) for c in cands])
        lex_raw = dict(bm25.score(plan.query))
        dense_n, lex_n = _normalize(dense_single), _normalize(lex_raw)

        rankings: dict[str, list[str]] = {
            "keyword": [ref for ref, _ in sorted(lex_raw.items(), key=lambda kv: -kv[1])],
            "vector": [ref for ref, _ in sorted(dense_single.items(), key=lambda kv: -kv[1])],
        }

        if req.strategy in ("metadata_aware", "revision_aware", "hybrid"):
            meta_pred = _metadata_predicate(effective_focus, req)
            dense_meta = _dense_scores(session, cands, plan.query, lambda p: predicate(p) and meta_pred(p))
            rankings["metadata_aware"] = [
                ref for ref, _ in sorted(dense_meta.items(), key=lambda kv: -kv[1])
            ]
        if req.strategy == "revision_aware" and settings.rag_revision_aware:
            sub_rankings = []
            for sub in plan.sub_queries[:4]:
                d = _dense_scores(session, cands, sub, lambda p: predicate(p) and _metadata_predicate(effective_focus, req)(p))
                sub_rankings.append([ref for ref, _ in sorted(d.items(), key=lambda kv: -kv[1])])
            fused = _rrf(sub_rankings + [rankings.get("metadata_aware", rankings["vector"]),
                                          rankings["keyword"]])
            # Revision salience: the revision note of the requested revision IS the
            # authoritative record of what changed in it, so revision metadata is a
            # first-class retrieval dimension here — not merely a post-filter.
            if revision:
                for c in cands:
                    if c.payload.get("revision") == revision and c.payload.get("document_type") == "revision_note":
                        fused[c.chunk.id] = fused.get(c.chunk.id, 0.0) + 0.02
            rankings["revision_aware"] = [ref for ref, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
        if req.strategy == "hybrid":
            fused = _rrf([rankings["keyword"], rankings.get("metadata_aware", rankings["vector"])])
            rankings["hybrid"] = [ref for ref, _ in sorted(fused.items(), key=lambda kv: -kv[1])]

    chosen = rankings.get(req.strategy, rankings["vector"])
    cand_by_id = {c.chunk.id: c for c in cands}
    top_ids = chosen[: max(req.top_k * 2, req.top_k)]

    query_tokens = set(tokenize(plan.query))
    inputs = []
    dense_all = _normalize(dense_single)
    fusion_all = _normalize({ref: 1.0 / (i + 1) for i, ref in enumerate(chosen)})
    for cid in top_ids:
        c = cand_by_id[cid]
        inputs.append(
            rerank_mod.RerankInput(
                chunk_id=cid,
                text=c.text,
                payload=c.payload,
                dense=dense_all.get(cid, 0.0),
                lexical=max(lex_n.get(cid, 0.0), rerank_mod.lexical_overlap(query_tokens, c.text)),
                fusion=fusion_all.get(cid, 0.0),
            )
        )
    pool = req.rerank_top_n * 3 if (req.strategy == "revision_aware" and plan.revision_scoped) else req.rerank_top_n
    ranked = rerank_mod.rerank(
        inputs, focus_components=effective_focus, revision=revision, top_n=pool
    )
    if req.strategy == "revision_aware" and plan.revision_scoped and revision:
        # Metadata-first ordering for revision-scoped questions: the revision note of
        # that revision is the authoritative change record, so it leads the evidence
        # package; semantic results follow in rerank order.
        tier1 = [r for r in ranked
                 if cand_by_id[r["chunk_id"]].payload.get("revision") == revision
                 and cand_by_id[r["chunk_id"]].payload.get("document_type") == "revision_note"]
        rest = [r for r in ranked if r not in tier1]
        ranked = (tier1 + rest)[: req.rerank_top_n]

    results = [_to_scored(cand_by_id[r["chunk_id"]], r, i + 1) for i, r in enumerate(ranked)]
    response = SearchResponse(
        query=req.query,
        strategy=req.strategy,
        results=results,
        planned_queries=[{"query": plan.query, "sub_queries": plan.sub_queries, "rationale": plan.rationale,
                          "component": plan.component, "change": plan.change, "relationship": plan.relationship}],
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        retrieval_latency_ms=t_ret.ms,
        embedding_provider=provider.name,
        empty=not results,
        notice="" if results else "No evidence above the relevance floor.",
    )

    if req.compare_strategies:
        comparison: list[StrategyResult] = []
        for name in ("keyword", "vector", "revision_aware"):
            ranking = rankings.get(name, [])
            comparison.append(
                StrategyResult(
                    strategy=name,
                    candidate_count=len(ranking),
                    results=[
                        _to_scored(cand_by_id[ref], {"score": round(dense_all.get(ref, 0.0), 4),
                                                     "dense": dense_all.get(ref, 0.0),
                                                     "lexical": lex_n.get(ref, 0.0),
                                                     "metadata": 0.0, "metadata_parts": {},
                                                     "quarantined": False, "quarantine_reason": None},
                                   i + 1)
                        for i, ref in enumerate(ranking[: req.rerank_top_n])
                        if ref in cand_by_id
                    ],
                )
            )
        response.comparison = comparison
    return response


def _metadata_predicate(focus: list[str], req: SearchRequest):
    def pred(payload: dict) -> bool:
        comps = set(payload.get("component_ids") or [])
        if focus and not (comps & set(focus)):
            # keep globally-relevant normative chunks but let the reranker down-weight them
            return payload.get("document_type") in ("standard", "specification")
        if req.filters.revision and payload.get("revision") not in (req.filters.revision, None):
            return payload.get("document_type") in ("standard", "specification", "revision_note")
        return True

    return pred


def _mentioned_components(session: Session, query: str) -> list[str]:
    from app.db.models import Component

    low = query.lower()
    return [c.id for c in session.scalars(select(Component)).all() if c.name.lower() in low]


def _to_scored(cand: Candidate, ranked: dict, rank: int) -> ScoredChunk:
    bbox = cand.payload.get("bbox")
    return ScoredChunk(
        rank=rank,
        evidence_id=cand.chunk.id,
        evidence_type="document",
        document_id=cand.payload["document_id"],
        document_name=cand.payload["document_name"],
        chunk_id=cand.chunk.id,
        page=cand.payload.get("page"),
        section=cand.payload.get("section", ""),
        bbox=BoundingBox(**{k: bbox[k] for k in ("x", "y", "width", "height")}) if bbox else None,
        excerpt=cand.text[:600],
        score=float(ranked.get("score", 0.0)),
        component_id=(cand.payload.get("component_ids") or [None])[0],
        revision=cand.payload.get("revision"),
        authority=cand.payload.get("authority", "synthetic"),
        retrieval_strategy=str(ranked.get("strategy", "")),
        raw_score=float(ranked.get("score", 0.0)),
        rerank_score=float(ranked.get("score", 0.0)),
        lexical_score=float(ranked.get("lexical", 0.0)),
        dense_score=float(ranked.get("dense", 0.0)),
        metadata_boost=float(ranked.get("metadata", 0.0)),
        text=cand.text,
        token_count=len(tokenize(cand.text)),
        requirement_code=(cand.chunk.metadata_json or {}).get("requirement_code"),
    )


def to_evidence_refs(scored: list[ScoredChunk], strategy: str = "") -> list[EvidenceRef]:
    out = []
    for s in scored:
        ref = EvidenceRef(**{k: v for k, v in s.model_dump().items() if k in EvidenceRef.model_fields})
        ref.retrieval_strategy = strategy
        out.append(ref)
    return out
