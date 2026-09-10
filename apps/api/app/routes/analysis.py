"""Analysis job endpoints (async, progress-streamable)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Permission, Principal, authorize, current_principal
from app.db.base import get_session
from app.db.models import AnalysisEvent, AnalysisRun, ToolExecution
from app.schemas.analysis import AnalysisProgress, AnalysisQueued, AnalysisRequest, AnalysisResult, AnalysisRunOut
from app.services.analysis import orchestrator
from app.services.audit import record

router = APIRouter(tags=["analysis"])


@router.post("/analysis", response_model=AnalysisQueued, status_code=202)
def start_analysis(req: AnalysisRequest, session: Session = Depends(get_session),
                   principal: Principal = Depends(current_principal)):
    authorize(principal.role, Permission.RUN_ANALYSIS, context={"action": "analysis.start"})
    run = orchestrator.queue_analysis(session, req.project_id, req.revision_a, req.revision_b,
                                      principal.user_id, req.options)
    record(session, principal=principal, action="analysis.start", entity_type="analysis", entity_id=run.id,
           arguments=req.model_dump(), result_summary=f"queued {run.id}", analysis_id=run.id)
    return AnalysisQueued(analysis_id=run.id, status=run.status)


@router.get("/analysis", response_model=list[AnalysisRunOut])
def list_analyses(project_id: str | None = None, session: Session = Depends(get_session),
                  principal: Principal = Depends(current_principal)):
    stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
    if project_id:
        stmt = stmt.where(AnalysisRun.project_id == project_id)
    return list(session.scalars(stmt).all())


@router.get("/analysis/{analysis_id}", response_model=AnalysisResult)
def get_analysis(analysis_id: str, session: Session = Depends(get_session),
                 principal: Principal = Depends(current_principal)):
    run = session.get(AnalysisRun, analysis_id)
    if run is None:
        raise NotFoundError(f"Analysis '{analysis_id}' not found.")
    result = orchestrator.get_result(session, run)
    if result is None:
        raise NotFoundError("Analysis result is not available yet.",
                            detail={"status": run.status, "stage": run.stage, "error": run.error})
    return result


@router.get("/analysis/{analysis_id}/status", response_model=AnalysisProgress)
def analysis_status(analysis_id: str, session: Session = Depends(get_session),
                    principal: Principal = Depends(current_principal)):
    run = session.get(AnalysisRun, analysis_id)
    if run is None:
        raise NotFoundError(f"Analysis '{analysis_id}' not found.")
    events = session.scalars(
        select(AnalysisEvent).where(AnalysisEvent.analysis_run_id == analysis_id).order_by(AnalysisEvent.seq)
    ).all()
    return AnalysisProgress(
        analysis_id=analysis_id, status=run.status, stage=run.stage, progress=run.progress,
        stage_index=len(events), message=events[-1].message if events else "",
        events=[{"seq": e.seq, "stage": e.stage, "message": e.message, "payload": e.payload_json,
                 "created_at": e.created_at} for e in events],
    )


@router.get("/analysis/{analysis_id}/changes")
def analysis_changes(analysis_id: str, session: Session = Depends(get_session),
                     principal: Principal = Depends(current_principal)):
    result = get_analysis(analysis_id, session, principal)
    return {"changes": result.changes, "deterministic_checks": result.deterministic_checks}


@router.get("/analysis/{analysis_id}/evidence")
def analysis_evidence(analysis_id: str, session: Session = Depends(get_session),
                      principal: Principal = Depends(current_principal)):
    result = get_analysis(analysis_id, session, principal)
    return {"evidence": result.evidence, "retrieval_strategies": result.retrieval_strategies}


@router.get("/analysis/{analysis_id}/tool-executions")
def analysis_tools(analysis_id: str, session: Session = Depends(get_session),
                   principal: Principal = Depends(current_principal)):
    rows = session.scalars(
        select(ToolExecution).where(ToolExecution.analysis_run_id == analysis_id)
        .order_by(ToolExecution.timestamp)
    ).all()
    return {"tool_executions": [
        {"id": t.id, "tool": t.tool_name, "arguments": t.arguments_json, "status": t.status,
         "transport": t.transport, "mutating": t.mutating, "latency_ms": t.latency_ms,
         "timestamp": t.timestamp, "error": t.error} for t in rows]}
