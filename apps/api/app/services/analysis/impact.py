"""Impact analysis: dependency traversal + deterministic checks + evidence.

Order of operations is deliberate (design principle 7): deterministic first,
semantic second.  Graph traversal and rule evaluation are pure Python; RAG only
supplies citations; the LLM only writes the prose that ties it together.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import Timer, get_logger
from app.db.models import Component, ComponentRevision, Document, Requirement
from app.schemas.analysis import (
    AffectedComponent,
    InsightBlock,
    ProposedFinding,
    Recommendation,
)
from app.schemas.common import BoundingBox, Confidence, EvidenceRef, Severity
from app.schemas.rag import SearchRequest, RetrievalFilters
from app.services.analysis.revision_analyzer import ChangeCandidate
from app.services.analysis.rules import CheckContext, CheckResult, evaluate_rule
from app.services.graph import get_graph_store
from app.services.rag import retriever

log = get_logger(__name__)

_HOP_ATTENUATION = {1: 0, 2: 1}  # severity step-down per hop


@dataclass
class ImpactPackage:
    affected: list[AffectedComponent] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    proposed_findings: list[ProposedFinding] = field(default_factory=list)
    confidence: Confidence = field(default_factory=lambda: Confidence(value=0.0, basis="none"))
    retrieval_latency_ms: float = 0.0


def _props_map(session: Session, revision_id: str) -> dict[str, dict]:
    rows = session.scalars(select(ComponentRevision).where(ComponentRevision.revision_id == revision_id)).all()
    return {r.component_id: dict(r.properties_json or {}) for r in rows}


def run_deterministic_checks(session: Session, props_a: dict, props_b: dict, related: dict) -> list[CheckResult]:
    ctx = CheckContext(props_a=props_a, props_b=props_b, related=related)
    results: list[CheckResult] = []
    for req in session.scalars(select(Requirement)).all():
        rule = (req.metadata_json or {}).get("rule") or {}
        if not rule.get("rule"):
            continue
        results.append(evaluate_rule(req.code, rule, ctx))
    return results


def build_impact(
    session: Session,
    project_id: str,
    revision_a_id: str,
    revision_b_id: str,
    changes: list[ChangeCandidate],
    *,
    rev_b_name: str,
) -> ImpactPackage:
    pkg = ImpactPackage()
    props_a, props_b = _props_map(session, revision_a_id), _props_map(session, revision_b_id)
    names = {c.id: c.name for c in session.scalars(select(Component)).all()}

    consequential = [c for c in changes if c.kind not in ("metadata",) and c.change_type.value != "METADATA_CHANGE"]
    roots = sorted({c.component_id for c in consequential if c.component_id})
    related = {cid: props_b.get(cid, {}) for cid in names if cid not in roots}

    # ---- deterministic checks -------------------------------------------- #
    for root in roots or list(props_b)[:1]:
        pkg.checks += run_deterministic_checks(session, props_a.get(root, {}), props_b.get(root, {}), related)
    seen: set[str] = set()
    deduped: list[CheckResult] = []
    for c in pkg.checks:
        key = (c.requirement_code, c.result)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    pkg.checks = deduped

    failing = [c for c in pkg.checks if c.result == "fail"]
    flagged = [c for c in pkg.checks if c.result == "flag"]

    # ---- structured evidence for checks ---------------------------------- #
    req_by_code = {r.code: r for r in session.scalars(select(Requirement)).all()}
    doc_titles = {d.id: d.title for d in session.scalars(select(Document)).all()}
    for chk in failing + flagged:
        req = req_by_code.get(chk.requirement_code)
        pkg.evidence.append(
            EvidenceRef(
                evidence_id=f"chk_{chk.requirement_code}_{chk.result}",
                evidence_type="structured",
                document_id=req.document_id if req else None,
                document_name=doc_titles.get(req.document_id, "") if req else "",
                page=req.page if req else None,
                section=req.section if req else "",
                excerpt=f"{chk.requirement_code}: deterministic {chk.rule} check → {chk.result.upper()} "
                        f"(inputs={chk.inputs}, margin={chk.margin}{chk.unit})",
                score=1.0,
                retrieval_strategy="deterministic-rule",
            )
        )

    # ---- dependency traversal -------------------------------------------- #
    graph = get_graph_store()
    affected_by_component: dict[str, AffectedComponent] = {}
    for change in consequential:
        if not change.component_id:
            continue
        for hit in graph.traverse(session, change.component_id, settings.graph_default_depth):
            step = _HOP_ATTENUATION.get(hit.hops, 1)
            sev = _attenuate(_severity_of(change, failing), step)
            prev = affected_by_component.get(hit.component_id)
            if prev is None or _rank(prev.severity) < _rank(sev):
                affected_by_component[hit.component_id] = AffectedComponent(
                    component_id=hit.component_id,
                    name=names.get(hit.component_id, hit.component_id),
                    severity=sev,
                    reason=f"{hit.hops} hop(s) from {names.get(change.component_id, change.component_id)} "
                           f"via {hit.via_type}",
                    distance_hops=hit.hops,
                    relationship_path=hit.path,
                    via_change_ids=[change.semantic],
                    confidence=round(max(0.35, change.confidence - 0.12 * (hit.hops - 1)), 3),
                )
            else:
                prev.via_change_ids.append(change.semantic)
    for cid in roots:
        affected_by_component.setdefault(
            cid,
            AffectedComponent(
                component_id=cid, name=names.get(cid, cid), severity=_max_sev([_severity_of(c, failing) for c in consequential if c.component_id == cid]),
                reason="component carrying the detected change", distance_hops=0, confidence=0.95,
            ),
        )
    pkg.affected = sorted(affected_by_component.values(), key=lambda a: (-_rank(a.severity), a.name))

    # ---- retrieval -------------------------------------------------------- #
    with Timer() as t_rag:
        for change in consequential[:4]:
            req = SearchRequest(
                query=f"{change.semantic.replace('_', ' ')} {change.old_value or ''} {change.new_value or ''} "
                      f"requirement limit clearance tolerance",
                project_id=project_id,
                strategy="revision_aware",
                top_k=settings.rag_top_k,
                rerank_top_n=3,
                filters=RetrievalFilters(project_id=project_id, component_ids=[change.component_id or ""],
                                         revision=rev_b_name),
                change_context={"changes": [change.title], "relationships": [a.component_id for a in pkg.affected[:3]]},
            )
            resp = retriever.search(session, req)
            for chunk in resp.results:
                if chunk.quarantined if hasattr(chunk, "quarantined") else False:
                    continue
                if any(e.chunk_id == chunk.chunk_id for e in pkg.evidence):
                    continue
                ref = EvidenceRef(**{k: v for k, v in chunk.model_dump().items() if k in EvidenceRef.model_fields})
                ref.retrieval_strategy = resp.strategy
                pkg.evidence.append(ref)
    pkg.retrieval_latency_ms = t_rag.ms

    # ---- recommendations -------------------------------------------------- #
    for chk in failing:
        pkg.recommendations.append(
            Recommendation(
                text=f"{chk.requirement_code} check '{chk.rule}' failed "
                     f"(inputs {chk.inputs}); verify before approval.",
                action_type="verify", component_id=roots[0] if roots else None,
                priority=Severity.HIGH, grounded_in=[f"chk_{chk.requirement_code}_fail"],
            )
        )
    for chk in flagged:
        pkg.recommendations.append(
            Recommendation(
                text=f"{chk.requirement_code}: '{chk.rule}' flagged "
                     f"({chk.inputs}); reviewer attention requested.",
                action_type="review", component_id=roots[0] if roots else None,
                priority=Severity.MEDIUM, grounded_in=[f"chk_{chk.requirement_code}_flag"],
            )
        )
    if any(c.change_type.value == "MATERIAL_CHANGE" for c in changes):
        pkg.recommendations.append(
            Recommendation(text="Material substitution: re-verify thermal capability and galvanic couple with "
                                "the Chassis Interface (ORN-MM-042 §4.2, ORN-TH-100 §2.3).",
                           action_type="recalculate", priority=Severity.MEDIUM,
                           grounded_in=["ORN-MM-042 §4.2", "ORN-TH-100 §2.3"]),
        )

    # ---- proposed findings (never auto-created) --------------------------- #
    for change in consequential:
        sev = _severity_of(change, failing)
        if sev != Severity.HIGH:
            continue
        ev = [e for e in pkg.evidence][:4]
        pkg.proposed_findings.append(
            ProposedFinding(
                title=f"{change.title} — potential impact on {names.get(change.component_id, 'component')}",
                severity=sev,
                confidence=change.confidence,
                component_id=change.component_id,
                change_id=change.semantic,
                description=f"{change.description} Deterministic checks: "
                            f"{', '.join(c.requirement_code + '=' + c.result for c in failing) or 'none failing'}.",
                recommendation="Engineer review required before release of the next revision.",
                affected_component_ids=[a.component_id for a in pkg.affected[:4]],
                evidence=ev,
                requires_confirmation=True,
            )
        )

    # ---- confidence -------------------------------------------------------- #
    cv_ratio = (sum(1 for c in changes if c.cv_confirmed) / len(changes)) if changes else 0.0
    ev_ratio = min(1.0, len([e for e in pkg.evidence if e.evidence_type == "document"]) / 3.0)
    chk_ratio = min(1.0, len([c for c in pkg.checks if c.result != "n/a"]) / 4.0)
    value = round(min(0.97, 0.45 + 0.22 * cv_ratio + 0.18 * ev_ratio + 0.12 * chk_ratio), 3)
    pkg.confidence = Confidence(
        value=value,
        basis="weighted: cv-confirmation ratio, evidence coverage, deterministic-check coverage",
        factors={"cv_confirmation": round(cv_ratio, 3), "evidence_coverage": round(ev_ratio, 3),
                 "check_coverage": round(chk_ratio, 3)},
    )
    return pkg


def build_insight_demo(pkg: ImpactPackage, changes: list[ChangeCandidate], affected_names: list[str]) -> InsightBlock:
    """Deterministic insight composition for DEMO_MODE (clearly labelled)."""
    n_ch = len(changes)
    n_con = len([c for c in changes if c.kind != "metadata" and c.change_type.value != "METADATA_CHANGE"])
    failing = [c for c in pkg.checks if c.result == "fail"]
    flagged = [c for c in pkg.checks if c.result == "flag"]
    summary = f"{n_ch} changes detected between the selected revisions; {n_con} classified as potentially " \
              f"consequential and {n_ch - n_con} as cosmetic/metadata."
    if failing:
        impact = ("Deterministic rule evaluation reports "
                  + ", ".join(f"{c.requirement_code} FAIL (margin {c.margin}{c.unit})" for c in failing)
                  + ". This is a computed limit violation, not a model opinion; reviewer confirmation still required.")
    elif flagged:
        impact = ("No hard limit violation was computed, but "
                  + ", ".join(c.requirement_code for c in flagged)
                  + " flag(s) require reviewer attention.")
    else:
        impact = "No deterministic limit violation was computed for the detected changes."
    reasoning = ("Affected components were derived by graph traversal (default 2 hops) from the changed "
                 "components: " + (", ".join(affected_names[:5]) or "none") + ". Evidence was retrieved with the "
                 "revision-aware strategy and every citation keeps document/page/section provenance.")
    uncertainty = ("Visual interpretation was not performed (deterministic mode). Unmapped pixel differences, "
                   "if any, are listed separately and were not interpreted.")
    return InsightBlock(summary=summary, potential_impact=impact, reasoning=reasoning, uncertainty=uncertainty,
                        confidence=pkg.confidence, grounded=bool(pkg.evidence), mode="demo")


def _severity_of(change: ChangeCandidate, failing: list[CheckResult]) -> Severity:
    if any(f.field == change.semantic for f in failing):
        return Severity.HIGH
    return Severity(change.metadata.get("severity") or _default_sev(change))


def _default_sev(change: ChangeCandidate) -> str:
    mapping = {
        "DIMENSION_CHANGE": "medium", "GEOMETRIC_CHANGE": "medium", "MATERIAL_CHANGE": "medium",
        "TOLERANCE_CHANGE": "medium", "FEATURE_ADDED": "medium", "FEATURE_REMOVED": "medium",
        "COMPONENT_ADDED": "medium", "COMPONENT_REMOVED": "medium", "ANNOTATION_CHANGE": "low",
        "METADATA_CHANGE": "low",
    }
    if change.change_type.value == "ANNOTATION_CHANGE" and change.semantic in ("fastener_size", "fastener_callout"):
        return "high"
    if change.change_type.value == "DIMENSION_CHANGE" and change.numeric_delta is not None and abs(change.numeric_delta) >= 1.0:
        return "high"
    return mapping.get(change.change_type.value, "low")


def _attenuate(sev: Severity, steps: int) -> Severity:
    order = [Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
    idx = min(len(order) - 1, order.index(sev) + steps)
    return order[idx]


def _rank(sev: Severity) -> int:
    return {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}[sev]


def _max_sev(sevs: list[Severity]) -> Severity:
    return max(sevs, key=_rank) if sevs else Severity.LOW
