"""Analysis pipeline schemas — strict Pydantic, no prose parsing."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import (
    AnalysisStatus,
    BoundingBox,
    ChangeClassification,
    ChangeType,
    Confidence,
    DetectionMethod,
    EvidenceRef,
    Severity,
    ToolCallRecord,
)


class ChangeOut(BaseModel):
    """A single detected revision change with location + provenance."""

    id: str = ""
    change_type: ChangeType
    component_id: str | None = None
    component_name: str = ""
    title: str = ""
    old_value: str | None = None
    new_value: str | None = None
    unit: str = ""
    numeric_delta: float | None = None
    location: BoundingBox = Field(default_factory=BoundingBox)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: Severity = Severity.LOW
    classification: ChangeClassification = ChangeClassification.COSMETIC
    detection_method: DetectionMethod = DetectionMethod.STRUCTURED
    description: str = ""
    drawing_id: str | None = None
    revision_a: str = ""
    revision_b: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AffectedComponent(BaseModel):
    component_id: str
    name: str = ""
    subsystem: str = ""
    severity: Severity = Severity.MEDIUM
    reason: str = ""
    distance_hops: int = 0
    relationship_path: list[str] = Field(default_factory=list)
    via_change_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class Recommendation(BaseModel):
    text: str
    action_type: Literal["verify", "review", "recalculate", "notify", "none"] = "review"
    component_id: str | None = None
    change_id: str | None = None
    priority: Severity = Severity.MEDIUM
    grounded_in: list[str] = Field(default_factory=list)  # evidence ids


class ProposedFinding(BaseModel):
    """A finding the agent *proposes*; creation still needs human confirmation."""

    title: str
    severity: Severity = Severity.MEDIUM
    confidence: float = 0.0
    component_id: str | None = None
    change_id: str | None = None
    description: str = ""
    recommendation: str = ""
    affected_component_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    requires_confirmation: bool = True


class InsightBlock(BaseModel):
    """The 'Ariadne's Insight' panel — grounded natural language."""

    summary: str = ""
    potential_impact: str = ""
    reasoning: str = ""
    uncertainty: str = ""
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.0, basis="none"))
    grounded: bool = False
    mode: Literal["demo", "live"] = "demo"


class AnalysisProgress(BaseModel):
    analysis_id: str
    status: AnalysisStatus = AnalysisStatus.QUEUED
    stage: str = "queued"
    stage_index: int = 0
    progress: int = 0
    message: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)


class AnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_a_id: str
    revision_b_id: str
    status: AnalysisStatus = AnalysisStatus.QUEUED
    stage: str = "queued"
    progress: int = 0
    mode: str = "demo"
    requested_by: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: float = 0.0
    error: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    summary_json: dict[str, Any] = Field(default_factory=dict)


class AnalysisRequest(BaseModel):
    project_id: str
    revision_a: str
    revision_b: str
    options: dict[str, Any] = Field(default_factory=dict)  # depth, strategies, force_mode...


class AnalysisQueued(BaseModel):
    analysis_id: str
    status: AnalysisStatus = AnalysisStatus.QUEUED


class AnalysisResult(BaseModel):
    """The strict output contract of a full revision analysis."""

    analysis_id: str
    project: dict[str, Any] = Field(default_factory=dict)
    revisions: dict[str, Any] = Field(default_factory=dict)
    status: AnalysisStatus = AnalysisStatus.COMPLETED
    mode: Literal["demo", "live"] = "demo"
    changes: list[ChangeOut] = Field(default_factory=list)
    affected_components: list[AffectedComponent] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    proposed_findings: list[ProposedFinding] = Field(default_factory=list)
    insight: InsightBlock = Field(default_factory=InsightBlock)
    confidence: float = 0.0
    deterministic_checks: list[dict[str, Any]] = Field(default_factory=list)
    tool_executions: list[ToolCallRecord] = Field(default_factory=list)
    retrieval_strategies: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: float = 0.0


class RevisionComparison(BaseModel):
    """Side-by-side comparison payload for the drawing viewer."""

    project_id: str
    revision_a: dict[str, Any]
    revision_b: dict[str, Any]
    drawing_a: dict[str, Any] | None = None
    drawing_b: dict[str, Any] | None = None
    changes: list[ChangeOut] = Field(default_factory=list)
    analysis_id: str | None = None
    alignment: dict[str, Any] = Field(default_factory=dict)
