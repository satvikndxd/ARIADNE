"""Domain read/write schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import BoundingBox, EvidenceRef, FindingStatus, Severity


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Project / Revision / Drawing ----------------------------------------- #
class ProjectOut(ORMModel):
    id: str
    name: str
    code: str = ""
    description: str = ""
    status: str = "active"
    active_revision_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    stats: dict[str, int] = Field(default_factory=dict)


class DrawingOut(ORMModel):
    id: str
    project_id: str
    revision_id: str
    filename: str
    storage_path: str
    drawing_type: str = "part"
    sheet: str = "1/1"
    width_px: int = 0
    height_px: int = 0
    image_url: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RevisionOut(ORMModel):
    id: str
    project_id: str
    name: str
    label: str = ""
    sequence: int = 0
    status: str = "released"
    parent_revision_id: str | None = None
    released_by: str = ""
    notes: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    drawings: list[DrawingOut] = Field(default_factory=list)


# ---- Components / dependencies -------------------------------------------- #
class ComponentOut(ORMModel):
    id: str
    project_id: str
    name: str
    code: str = ""
    type: str = "part"
    subsystem: str = ""
    material: str = ""
    weight_g: float = 0.0
    status: str = "active"
    description: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    revision_id: str | None = None
    finding_count: int = 0


class DependencyEdge(BaseModel):
    id: str = ""
    source_component_id: str
    target_component_id: str
    relationship_type: str
    description: str = ""
    criticality: str = "normal"


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = "component"
    subsystem: str = ""
    material: str = ""
    depth: int = 0
    direction: Literal["root", "upstream", "downstream", "spec", "assembly"] = "root"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DependencyGraphOut(BaseModel):
    root_component_id: str
    depth: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    upstream: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
    specifications: list[str] = Field(default_factory=list)
    store: str = "sql"
    truncated: bool = False


class ComponentRevisionOut(ORMModel):
    id: str
    component_id: str
    revision_id: str
    properties_json: dict[str, Any] = Field(default_factory=dict)
    changed_from_parent: bool = False


# ---- Documents / requirements --------------------------------------------- #
class DocumentOut(ORMModel):
    id: str
    project_id: str | None = None
    title: str
    document_type: str = "specification"
    source: str = ""
    doc_revision: str = ""
    authority: str = "synthetic"
    pages: int = 0
    path: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    chunk_count: int = 0


class RequirementOut(ORMModel):
    id: str
    document_id: str | None = None
    code: str = ""
    title: str = ""
    section: str = ""
    page: int = 1
    text: str = ""
    requirement_type: str = "design"
    normative: bool = True
    applies_to_json: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    document_title: str = ""


# ---- Findings -------------------------------------------------------------- #
class FindingEvidenceIn(BaseModel):
    evidence_type: str = "document"
    document_id: str | None = None
    document_name: str = ""
    chunk_id: str | None = None
    page: int | None = None
    section: str = ""
    bbox: BoundingBox | None = None
    excerpt: str = ""
    score: float = 0.0


class FindingEvidenceOut(FindingEvidenceIn):
    id: str = ""


class FindingCreate(BaseModel):
    project_id: str
    revision_id: str | None = None
    component_id: str | None = None
    analysis_run_id: str | None = None
    change_id: str | None = None
    title: str = Field(min_length=4, max_length=300)
    severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    description: str = ""
    recommendation: str = ""
    status: FindingStatus = FindingStatus.OPEN
    source: str = "manual"
    affected_component_ids: list[str] = Field(default_factory=list)
    evidence: list[FindingEvidenceIn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingUpdate(BaseModel):
    status: FindingStatus | None = None
    severity: Severity | None = None
    resolution_note: str | None = None
    title: str | None = None
    description: str | None = None
    recommendation: str | None = None


class FindingOut(ORMModel):
    id: str
    project_id: str
    revision_id: str | None = None
    component_id: str | None = None
    analysis_run_id: str | None = None
    change_id: str | None = None
    title: str
    severity: str = "medium"
    confidence: float = 0.0
    description: str = ""
    recommendation: str = ""
    status: str = "open"
    source: str = "manual"
    created_by: str = ""
    reviewed_by: str | None = None
    resolution_note: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    evidence: list[FindingEvidenceOut] = Field(default_factory=list)
    affected_component_ids: list[str] = Field(default_factory=list)
    component_name: str = ""


class FindingCounts(BaseModel):
    open: int = 0
    needs_review: int = 0
    accepted: int = 0
    rejected: int = 0
    resolved: int = 0
    total: int = 0
