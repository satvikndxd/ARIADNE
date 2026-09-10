"""Deterministic feature-based reranker.

This is a *transparent* scorer, not a black box: the final score is a weighted
sum of named signals and each weight is reported back in the API response so a
reviewer can see exactly why a chunk ranked where it did.

    final = 0.50·dense + 0.30·bm25_norm + 0.20·metadata

with ``metadata`` itself decomposed into component / revision / document-type /
authority signals.  A neural cross-encoder can be dropped in behind the same
signature later (see docs/rag.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.content_security import quarantine_reason
from app.services.rag.embeddings import tokenize

WEIGHTS = {"dense": 0.45, "lexical": 0.25, "metadata": 0.15, "fusion": 0.15}

META_W = {"component": 0.40, "revision": 0.25, "doc_type": 0.15, "authority": 0.20}

_PRIORITY_DOC_TYPES = {"specification", "standard", "revision_note", "guideline"}


@dataclass
class RerankInput:
    chunk_id: str
    text: str
    payload: dict
    dense: float
    lexical: float
    fusion: float = 0.0


def metadata_score(payload: dict, focus_components: list[str], revision: str | None) -> tuple[float, dict]:
    parts: dict[str, float] = {}
    comps = set(payload.get("component_ids") or [])
    parts["component"] = 1.0 if (set(focus_components) & comps) else (0.35 if comps else 0.0)
    parts["revision"] = 1.0 if revision and payload.get("revision") == revision else (0.4 if payload.get("revision") else 0.0)
    parts["doc_type"] = 1.0 if payload.get("document_type") in _PRIORITY_DOC_TYPES else 0.3
    parts["authority"] = 0.0 if payload.get("authority") in ("untrusted_vendor_note",) else 1.0
    score = sum(META_W[k] * v for k, v in parts.items())
    return score, parts


def lexical_overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = set(tokenize(text))
    inter = query_tokens & doc_tokens
    return len(inter) / len(query_tokens)


def rerank(
    inputs: list[RerankInput],
    *,
    focus_components: list[str],
    revision: str | None,
    top_n: int,
) -> list[dict]:
    ranked: list[dict] = []
    for item in inputs:
        meta, meta_parts = metadata_score(item.payload, focus_components, revision)
        final = (
            WEIGHTS["dense"] * item.dense
            + WEIGHTS["lexical"] * item.lexical
            + WEIGHTS["metadata"] * meta
            + WEIGHTS["fusion"] * item.fusion
        )
        quarantined = quarantine_reason(item.payload.get("text", item.text), item.payload.get("authority", ""))
        if quarantined:
            final *= 0.35
        ranked.append(
            {
                "chunk_id": item.chunk_id,
                "payload": item.payload,
                "dense": round(item.dense, 4),
                "lexical": round(item.lexical, 4),
                "metadata": round(meta, 4),
                "fusion": round(item.fusion, 4),
                "metadata_parts": {k: round(v, 3) for k, v in meta_parts.items()},
                "score": round(final, 4),
                "quarantined": bool(quarantined),
                "quarantine_reason": quarantined,
            }
        )
    ranked.sort(key=lambda r: -r["score"])
    return ranked[:top_n]
