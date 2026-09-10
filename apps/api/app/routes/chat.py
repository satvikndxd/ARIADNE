"""Chat + confirmation endpoints (human-in-the-loop)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.ids import utcnow
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import ChatMessage, ChatSession, Confirmation
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionOut,
    ConfirmationDecision,
    ConfirmationOut,
)
from app.services.agent.agent import AgentRunner
from app.services.agent.gateway import ToolGateway
from app.services.audit import record

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, session: Session = Depends(get_session),
         principal: Principal = Depends(current_principal)):
    runner = AgentRunner(session)
    resp = runner.run(principal, req)
    session.commit()
    return resp


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
def list_sessions(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    rows = session.scalars(select(ChatSession).order_by(ChatSession.created_at.desc())).all()
    return [ChatSessionOut.model_validate(r) for r in rows]


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionOut)
def get_session_row(session_id: str, session: Session = Depends(get_session),
                    principal: Principal = Depends(current_principal)):
    row = session.get(ChatSession, session_id)
    if row is None:
        raise NotFoundError(f"Chat session '{session_id}' not found.")
    return ChatSessionOut.model_validate(row)


# --------------------------------------------------------------------------- #
@router.get("/confirmations", response_model=list[ConfirmationOut])
def list_confirmations(status: str | None = None, session: Session = Depends(get_session),
                       principal: Principal = Depends(current_principal)):
    stmt = select(Confirmation).order_by(Confirmation.created_at.desc())
    if status:
        stmt = stmt.where(Confirmation.status == status)
    return list(session.scalars(stmt).all())


@router.get("/confirmations/{confirmation_id}", response_model=ConfirmationOut)
def get_confirmation(confirmation_id: str, session: Session = Depends(get_session),
                     principal: Principal = Depends(current_principal)):
    conf = session.get(Confirmation, confirmation_id)
    if conf is None:
        raise NotFoundError(f"Confirmation '{confirmation_id}' not found.")
    return ConfirmationOut.model_validate(conf)


@router.post("/confirmations/{confirmation_id}/decision", response_model=ConfirmationOut)
def decide(confirmation_id: str, decision: ConfirmationDecision,
           session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    conf = session.get(Confirmation, confirmation_id)
    if conf is None:
        raise NotFoundError(f"Confirmation '{confirmation_id}' not found.")
    if conf.status != "pending":
        raise ValidationError(f"Confirmation already {conf.status}.")
    conf.decided_by = principal.user_id
    conf.decided_at = utcnow()
    if not decision.approved:
        conf.status = "rejected"
        conf.result_json = {"note": decision.note}
        record(session, principal=principal, action="confirmation.rejected", entity_type="confirmation",
               entity_id=conf.id, tool=conf.tool_name, result_summary=decision.note)
        session.commit()
        return ConfirmationOut.model_validate(conf)

    conf.status = "approved"
    session.flush()
    gateway = ToolGateway(session)
    args = (conf.payload_json or {}).get("args", {})
    result = gateway.execute(conf.tool_name, args, principal, confirmation_id=conf.id)
    if not result.ok:
        conf.status = "pending"  # execution refused → the gate stays open, nothing mutated
        conf.result_json = {}
        record(session, principal=principal, action="confirmation.execution_failed", entity_type="confirmation",
               entity_id=conf.id, tool=conf.tool_name, result_summary=result.error or "", severity="error")
        session.commit()
        raise ValidationError(result.error or "Execution failed after approval.",
                              detail={"code": result.error_code})
    conf.result_json = {"executed": True, "result": result.result, "transport": result.transport}
    record(session, principal=principal, action="confirmation.approved", entity_type="confirmation",
           entity_id=conf.id, tool=conf.tool_name, arguments=args,
           result_summary=f"executed via {result.transport}")
    session.commit()
    return ConfirmationOut.model_validate(conf)
