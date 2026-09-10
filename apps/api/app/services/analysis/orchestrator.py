"""Analysis orchestrator — the 9-stage asynchronous pipeline.

Queued → running (stage events streamed into ``analysis_events``) → completed |
failed.  Any exception becomes ``status=failed`` plus a human-readable message;
stack traces go to the log only.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import new_id, utcnow
from app.core.logging import Timer, analysis_id_var, get_logger
from app.db.base import SessionLocal
from app.db.models import AnalysisEvent, AnalysisRun, Change, Component, Project, Revision
from app.schemas.analysis import AnalysisResult, ChangeOut, InsightBlock
from app.schemas.common import (
    AnalysisStatus,
    BoundingBox,
    ChangeClassification,
    ChangeType,
    DetectionMethod,
    Severity,
    ToolCallRecord,
)
from app.services.analysis import impact as impact_svc
from app.services.analysis.revision_analyzer import get_revision_analyzer
from app.services.analysis.rules import severity_for_change
from app.services.llm import prompts
from app.services.llm.base import LLMMessage, get_llm_provider, is_live

log = get_logger(__name__)

STAGES = [
    ("loading_revisions", "Loading revisions and drawings"),
    ("aligning_drawings", "Registering/aligning drawing images"),
    ("detecting_changes", "Detecting changed regions"),
    ("classifying_changes", "Classifying changes and severity"),
    ("mapping_components", "Mapping changes to components"),
    ("traversing_dependencies", "Traversing dependency graph"),
    ("retrieving_evidence", "Retrieving standards and specification evidence"),
    ("generating_impact", "Generating evidence-grounded impact analysis"),
    ("preparing_review", "Preparing human review package"),
]


def _emit(session: Session, run: AnalysisRun, index: int, message: str, payload: dict | None = None) -> None:
    stage = STAGES[index][0]
    run.stage, run.progress = stage, int((index + 1) / len(STAGES) * 100)
    session.add(
        AnalysisEvent(
            id=new_id("aev"), analysis_run_id=run.id, seq=index + 1, stage=stage, message=message,
            payload_json=payload or {},
        )
    )
    session.commit()


def queue_analysis(session: Session, project_id: str, rev_a: str, rev_b: str, user_id: str,
                   options: dict | None = None) -> AnalysisRun:
    run = AnalysisRun(
        id=new_id("an"), project_id=project_id, revision_a_id=rev_a, revision_b_id=rev_b,
        status=AnalysisStatus.QUEUED.value, stage="queued", progress=0,
        mode="live" if is_live() else "demo", requested_by=user_id, config_json=options or {},
    )
    session.add(run)
    session.commit()
    thread = threading.Thread(target=run_analysis, args=(run.id,), name=f"analysis-{run.id}", daemon=True)
    thread.start()
    return run


def run_analysis(analysis_id: str) -> None:
    analysis_id_var.set(analysis_id)
    t0 = time.perf_counter()
    with SessionLocal() as session:
        run = session.get(AnalysisRun, analysis_id)
        if run is None:
            log.error("analysis_run_missing", analysis_id=analysis_id)
            return
        run.status = AnalysisStatus.RUNNING.value
        run.started_at = utcnow()
        session.commit()
        try:
            result = _pipeline(session, run)
            run.status = AnalysisStatus.COMPLETED.value
            run.stage = "completed"
            run.progress = 100
            run.result_json = result.model_dump(mode="json")
            run.summary_json = {
                "changes": len(result.changes),
                "consequential": len([c for c in result.changes if c.classification == ChangeClassification.CONSEQUENTIAL]),
                "affected_components": len(result.affected_components),
                "evidence": len(result.evidence),
                "proposed_findings": len(result.proposed_findings),
                "confidence": result.confidence,
                "mode": result.mode,
            }
        except Exception as exc:  # noqa: BLE001 — boundary handler
            log.exception("analysis_failed", analysis_id=analysis_id, error=str(exc))
            run.status = AnalysisStatus.FAILED.value
            run.error = f"Analysis failed: {type(exc).__name__}: {exc}"
            _emit(session, run, len(STAGES) - 1, "Analysis failed — see error field.", {"error": run.error})
        run.completed_at = utcnow()
        run.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        session.commit()
        log.info("analysis_finished", analysis_id=analysis_id, status=run.status, latency_ms=run.latency_ms)


def _pipeline(session: Session, run: AnalysisRun) -> AnalysisResult:
    _emit(session, run, 0, STAGES[0][1])
    project = session.get(Project, run.project_id)
    rev_a = session.get(Revision, run.revision_a_id)
    rev_b = session.get(Revision, run.revision_b_id)
    if project is None or rev_a is None or rev_b is None:
        raise ValueError("project or revision not found")

    _emit(session, run, 1, STAGES[1][1])
    with Timer() as t_detect:
        analyzer = get_revision_analyzer()
        analysis = analyzer.analyze(session, rev_a, rev_b)
    _emit(session, run, 2, f"{len(analysis.changes)} candidate change regions",
          {"alignment": analysis.alignment, "cv_regions": len(analysis.cv_regions)})

    _emit(session, run, 3, STAGES[3][1])
    names = {c.id: c.name for c in session.scalars(select(Component)).all()}
    failing_fields = set()
    changes_out: list[ChangeOut] = []
    for cand in analysis.changes:
        sev, classification = severity_for_change(
            cand.change_type.value, cand.semantic, delta_mm=cand.numeric_delta, fails=[], flags=[]
        )
        changes_out.append(
            ChangeOut(
                id=cand.semantic,
                change_type=cand.change_type,
                component_id=cand.component_id,
                component_name=names.get(cand.component_id or "", ""),
                title=cand.title,
                old_value=cand.old_value,
                new_value=cand.new_value,
                unit=cand.unit,
                numeric_delta=cand.numeric_delta,
                location=cand.location,
                confidence=cand.confidence,
                severity=Severity(sev),
                classification=ChangeClassification(classification),
                detection_method=cand.detection_method,
                description=cand.description,
                drawing_id=cand.drawing_id,
                revision_a=rev_a.name,
                revision_b=rev_b.name,
                metadata={**cand.metadata, "cv_confirmed": cand.cv_confirmed, "kind": cand.kind,
                          "semantic": cand.semantic},
            )
        )
    # persist changes
    session.query(Change).filter(Change.analysis_run_id == run.id).delete()
    for i, co in enumerate(changes_out):
        session.add(
            Change(
                id=new_id("ch"), analysis_run_id=run.id, project_id=run.project_id,
                revision_a_id=rev_a.id, revision_b_id=rev_b.id, component_id=co.component_id,
                drawing_id=co.drawing_id, change_type=co.change_type.value, title=co.title,
                old_value=co.old_value, new_value=co.new_value, unit=co.unit,
                location_json=co.location.model_dump(), confidence=co.confidence,
                severity=co.severity.value, classification=co.classification.value,
                detection_method=co.detection_method.value, description=co.description,
                metadata_json={**co.metadata, "semantic": co.id, "change_index": i},
            )
        )
    session.commit()
    for co in changes_out:
        co.id = next(
            c.id for c in session.scalars(select(Change).where(Change.analysis_run_id == run.id)).all()
            if (c.metadata_json or {}).get("semantic") == co.id
        )

    _emit(session, run, 4, STAGES[4][1], {"components": sorted({c.component_name for c in changes_out if c.component_name})})
    _emit(session, run, 5, STAGES[5][1])
    _emit(session, run, 6, STAGES[6][1])

    cands = analysis.changes
    pkg = impact_svc.build_impact(session, run.project_id, rev_a.id, rev_b.id, cands, rev_b_name=rev_b.name)

    # re-apply deterministic severity now that checks exist
    for co in changes_out:
        for chk in pkg.checks:
            if chk.result == "fail" and chk.field and co.metadata.get("semantic") and _field_matches(chk.field, co):
                co.severity = Severity.HIGH
                co.classification = ChangeClassification.CONSEQUENTIAL
        if co.severity == Severity.HIGH:
            failing_fields.add(co.id)

    _emit(session, run, 7, STAGES[7][1],
          {"checks": [c.as_dict() for c in pkg.checks if c.result in ("fail", "flag")]})

    insight = _insight(session, run, pkg, changes_out)
    _emit(session, run, 8, STAGES[8][1], {"proposed_findings": len(pkg.proposed_findings)})

    return AnalysisResult(
        analysis_id=run.id,
        project={"id": project.id, "name": project.name},
        revisions={"a": {"id": rev_a.id, "name": rev_a.name}, "b": {"id": rev_b.id, "name": rev_b.name}},
        status=AnalysisStatus.COMPLETED,
        mode=run.mode,
        changes=changes_out,
        affected_components=pkg.affected,
        evidence=pkg.evidence,
        recommendations=pkg.recommendations,
        proposed_findings=pkg.proposed_findings,
        insight=insight,
        confidence=pkg.confidence.value,
        deterministic_checks=[c.as_dict() for c in pkg.checks],
        tool_executions=[],
        retrieval_strategies={"strategy": "revision_aware", "retrieval_latency_ms": pkg.retrieval_latency_ms,
                              "detection_latency_ms": t_detect.ms, "analyzer": analyzer.name},
        created_at=run.created_at,
        completed_at=utcnow(),
        latency_ms=run.latency_ms,
    )


def _field_matches(field: str, change: ChangeOut) -> bool:
    semantic = (change.metadata or {}).get("semantic", "")
    return field in semantic or semantic in field or semantic == field


def _insight(session: Session, run: AnalysisRun, pkg, changes: list[ChangeOut]) -> InsightBlock:
    names = [a.name for a in pkg.affected]
    if not is_live():
        return impact_svc.build_insight_demo(pkg, _as_candidates(changes), names)
    llm = get_llm_provider()
    resp = llm.generate(
        [
            LLMMessage(role="system", content=prompts.SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=prompts.insight_prompt(
                    [c.model_dump(mode="json") for c in changes],
                    [a.model_dump(mode="json") for a in pkg.affected],
                    [c.as_dict() for c in pkg.checks],
                    [e.model_dump(mode="json") for e in pkg.evidence],
                ),
            ),
        ],
        json_schema=prompts.INSIGHT_SCHEMA,
    )
    data = resp.structured or {}
    return InsightBlock(
        summary=data.get("summary", ""),
        potential_impact=data.get("potential_impact", ""),
        reasoning=data.get("reasoning", ""),
        uncertainty=data.get("uncertainty", ""),
        confidence=pkg.confidence,
        grounded=bool(pkg.evidence),
        mode="live",
    )


def _as_candidates(changes: list[ChangeOut]) -> list[Any]:
    class _C:
        pass

    out = []
    for c in changes:
        obj = _C()
        obj.change_type = c.change_type
        obj.kind = (c.metadata or {}).get("kind", "")
        obj.semantic = (c.metadata or {}).get("semantic", c.id)
        obj.cv_confirmed = bool((c.metadata or {}).get("cv_confirmed"))
        out.append(obj)
    return out


def get_result(session: Session, run: AnalysisRun) -> AnalysisResult | None:
    if not run.result_json:
        return None
    return AnalysisResult(**run.result_json)
