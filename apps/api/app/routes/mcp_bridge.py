"""Bridge endpoint used by the TypeScript MCP server.

The MCP server is a protocol façade: it validates transport-level concerns and
refuses mutating calls without a confirmation id, but *all* authorization and
confirmation-digest enforcement happens here, server-side, in plain Python.
Executions arriving through this bridge are recorded with
``transport="mcp-http"`` so the audit trail shows the true path.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import Principal, resolve_principal
from app.db.base import get_session
from app.services.agent.gateway import ToolGateway

router = APIRouter(tags=["mcp"])


class BridgeRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/mcp-bridge/tools/{tool_name}/execute")
def execute(tool_name: str, payload: BridgeRequest, request: Request,
            session: Session = Depends(get_session)):
    ctx = payload.context or {}
    principal: Principal = resolve_principal(ctx.get("user_id") or request.headers.get("x-ariadne-user"))
    gateway = ToolGateway(session)
    result = gateway.execute(
        tool_name,
        payload.args,
        principal,
        confirmation_id=ctx.get("confirmation_id"),
        force_transport="in-process",
        transport_label="mcp-http",
    )
    session.commit()
    body = {
        "ok": result.ok,
        "tool": result.tool,
        "status": result.status,
        "transport": result.transport,
        "latency_ms": result.latency_ms,
        "execution_id": result.execution_id,
    }
    if result.ok:
        body["result"] = result.result
    else:
        body["error"] = result.error
        body["error_code"] = result.error_code
    from fastapi.responses import JSONResponse

    status = 200 if result.ok else (403 if result.status == "denied"
                                    else 409 if result.status == "pending_confirmation" else 422)
    return JSONResponse(status_code=status, content=body)
