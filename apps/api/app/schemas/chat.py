"""Chat / agent schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import EvidenceRef, ToolCallRecord


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    project_id: str | None = None
    session_id: str | None = None
    revision_a: str | None = None
    revision_b: str | None = None
    analysis_id: str | None = None
    component_id: str | None = None
    max_tool_rounds: int = Field(default=4, ge=1, le=8)


class PendingAction(BaseModel):
    """Human-in-the-loop confirmation request surfaced in chat."""

    confirmation_id: str
    tool_name: str
    action_label: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    affected: list[dict[str, Any]] = Field(default_factory=list)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: str
    content: str = ""
    structured_json: dict[str, Any] = Field(default_factory=dict)
    tool_calls_json: list[ToolCallRecord] = Field(default_factory=list)
    evidence_json: list[EvidenceRef] = Field(default_factory=list)
    pending_confirmation_id: str | None = None
    mode: str = "demo"
    latency_ms: float = 0.0
    created_at: datetime | None = None


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    answer: str
    structured: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    pending_action: PendingAction | None = None
    mode: str = "demo"
    grounded: bool = False
    insufficient_evidence: bool = False
    latency_ms: float = 0.0


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    user_id: str = ""
    title: str = ""
    context_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ConfirmationDecision(BaseModel):
    approved: bool
    note: str = ""


class ConfirmationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    tool_name: str
    action_label: str = ""
    summary: str = ""
    payload_json: dict[str, Any] = Field(default_factory=dict)
    evidence_json: list[EvidenceRef] = Field(default_factory=list)
    status: str = "pending"
    requested_by: str = ""
    decided_by: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)
