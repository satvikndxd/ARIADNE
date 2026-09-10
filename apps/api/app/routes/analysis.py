"""Analysis job endpoints (async, progress-streamable)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
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


@router.get("/analysis/{analysis_id}/changes/{change_id}/crop")
def change_crop(analysis_id: str, change_id: str, side: str = Query(default="b", pattern="^(a|b)$"),
                pad: int = Query(default=12, ge=0, le=60),
                session: Session = Depends(get_session),
                principal: Principal = Depends(current_principal)):
    """PNG crop of a detected change region from either revision (visual evidence)."""
    import io
    from pathlib import Path

    from PIL import Image

    from app.core.errors import NotFoundError
    from app.db.models import Change, Drawing

    run = session.get(AnalysisRun, analysis_id)
    if run is None:
        raise NotFoundError(f"Analysis '{analysis_id}' not found.")
    change = session.scalars(select(Change).where(Change.id == change_id,
                                                   Change.analysis_run_id == analysis_id)).first()
    if change is None:
        # tolerate semantic ids (compare-phase changes carry the semantic as id)
        change = session.scalars(
            select(Change).where(Change.analysis_run_id == analysis_id)
        ).all() and next((c for c in session.scalars(
            select(Change).where(Change.analysis_run_id == analysis_id)).all()
            if (c.metadata_json or {}).get("semantic") == change_id), None)
    if change is None:
        raise NotFoundError(f"Change '{change_id}' not found.")
    revision_id = run.revision_a_id if side == "a" else run.revision_b_id
    drawing = session.scalars(
        select(Drawing).where(Drawing.revision_id == revision_id, Drawing.drawing_type == "part")
    ).first()
    if drawing is None or not Path(drawing.storage_path).exists():
        raise NotFoundError("Drawing for this revision side is missing.")
    loc = change.location_json or {}
    img = Image.open(drawing.storage_path)
    x1 = max(0, int(loc.get("x", 0)) - pad)
    y1 = max(0, int(loc.get("y", 0)) - pad)
    x2 = min(img.width, int(loc.get("x", 0) + loc.get("width", 0)) + pad)
    y2 = min(img.height, int(loc.get("y", 0) + loc.get("height", 0)) + pad)
    buf = io.BytesIO()
    img.crop((x1, y1, x2, y2)).save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"cache-control": "public, max-age=3600"})
