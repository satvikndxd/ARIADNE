"""Audit trail endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import AuditEvent, ToolExecution

router = APIRouter(tags=["audit"])


@router.get("/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), entity_type: str | None = None,
              session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    stmt = select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    rows = session.scalars(stmt).all()
    return {"events": [
        {"id": e.id, "timestamp": e.timestamp, "user": e.user_id, "role": e.role, "action": e.action,
         "entity_type": e.entity_type, "entity_id": e.entity_id, "tool": e.tool,
         "arguments": e.arguments_json, "result_summary": e.result_summary, "severity": e.severity,
         "request_id": e.request_id} for e in rows]}


@router.get("/tool-executions")
def tool_executions(limit: int = Query(default=100, ge=1, le=500),
                    session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    rows = session.scalars(select(ToolExecution).order_by(ToolExecution.timestamp.desc()).limit(limit)).all()
    return {"tool_executions": [
        {"id": t.id, "tool": t.tool_name, "arguments": t.arguments_json, "result": t.result_json,
         "status": t.status, "transport": t.transport, "mutating": t.mutating, "error": t.error,
         "requested_by": t.requested_by, "latency_ms": t.latency_ms, "timestamp": t.timestamp}
        for t in rows]}
