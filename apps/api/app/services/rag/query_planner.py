"""Structured retrieval planning.

Never send the raw question to a vector index.  A plan decomposes the request
into retrieval dimensions (component / change / relationship / normative query)
plus metadata filters, and derives sub-queries that are fused later with RRF.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Component
from app.schemas.rag import QueryPlan, RetrievalFilters

_STOP = {"what", "which", "why", "how", "does", "could", "would", "should", "the", "a", "an",
         "changed", "change", "changes", "affect", "affected", "impact", "requirements", "apply",
         "show", "me", "is", "are", "for", "this", "that", "with", "and", "of", "in", "to", "be"}


def _keywords(text: str) -> list[str]:
    return [w for w in re_split(text) if w not in _STOP and len(w) > 2][:14]


def re_split(text: str) -> list[str]:
    import re

    return [t for t in re.findall(r"[a-z0-9][a-z0-9._/-]*", text.lower())]


def plan_retrieval(
    session: Session,
    query: str,
    *,
    project_id: str | None = None,
    component_id: str | None = None,
    component_ids: list[str] | None = None,
    revision: str | None = None,
    change_context: dict | None = None,
) -> QueryPlan:
    change_context = change_context or {}
    names = {c.id: c.name for c in session.scalars(select(Component)).all()}

    mentioned = [cid for cid, name in names.items() if name.lower() in query.lower()]
    focus = component_ids or ([component_id] if component_id else []) or mentioned
    focus = focus[:6]

    changes: list[str] = change_context.get("changes", [])
    relationships: list[str] = change_context.get("relationships", [])
    change_text = "; ".join(changes[:4])

    core_terms = _keywords(query) + _keywords(change_text)
    normative = f"{' '.join(core_terms)} requirement specification limit clearance tolerance"

    # The PRIMARY ranking always runs on the user's own words (stopwords removed);
    # augmented/normative phrasings are *additional* sub-queries fused later, so a
    # generic vocabulary can never outrank the actual question.
    cleaned = " ".join(w for w in query.split() if w.lower() not in
                       {"what", "which", "why", "how", "does", "could", "show", "me", "the", "a", "an", "is", "are"})
    sub_queries = [normative.strip()]
    for cid in focus[:3]:
        sub_queries.append(f"{names.get(cid, cid)} {change_text} requirement specification".strip())
    for rel in relationships[:2]:
        sub_queries.append(f"{names.get(rel, rel)} interface clearance requirement".strip())
    if revision:
        sub_queries.append(f"revision note {revision} changed characteristics".strip())

    scoped_words = ("what changed", "changed in", "changes in", "diff between", "revision note",
                    "what's new", "new in", "modified in")
    plan = QueryPlan(
        revision_scoped=bool(revision) and any(w in query.lower() for w in scoped_words),
        component=", ".join(names.get(c, c) for c in focus) or "",
        change=change_text,
        relationship=", ".join(names.get(r, r) for r in relationships[:3]),
        query=cleaned.strip() or query.strip(),
        filters=RetrievalFilters(
            project_id=project_id,
            component_ids=focus,
            revision=revision,
            document_types=[],
        ),
        sub_queries=[s for s in dict.fromkeys(sub_queries)][:6],
        rationale=(
            "dimensions: focus components from request/analysis context, change description from detected "
            "changes, relationships from dependency traversal; sub-queries fused with reciprocal-rank fusion."
        ),
    )
    return plan
