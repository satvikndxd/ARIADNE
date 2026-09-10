"""Append-only audit trail."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.logging import request_id_var
from app.core.security import Principal
from app.db.models import AuditEvent


def record(
    session: Session,
    *,
    principal: Principal | None,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    result_summary: str = "",
    analysis_id: str | None = None,
    severity: str = "info",
    llm_response_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=new_id("aud"),
        user_id=principal.user_id if principal else "system",
        role=principal.role.value if principal else "SYSTEM",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        analysis_id=analysis_id,
        tool=tool,
        arguments_json=arguments or {},
        result_summary=result_summary[:400],
        request_id=request_id_var.get(),
        llm_response_id=llm_response_id,
        severity=severity,
    )
    session.add(event)
    session.flush()
    return event
