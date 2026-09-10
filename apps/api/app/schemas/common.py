"""Shared enums + primitive schemas (single source of truth for change types)."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeType(str, Enum):
    GEOMETRIC_CHANGE = "GEOMETRIC_CHANGE"
    DIMENSION_CHANGE = "DIMENSION_CHANGE"
    TOLERANCE_CHANGE = "TOLERANCE_CHANGE"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    COMPONENT_ADDED = "COMPONENT_ADDED"
    COMPONENT_REMOVED = "COMPONENT_REMOVED"
    FEATURE_ADDED = "FEATURE_ADDED"
    FEATURE_REMOVED = "FEATURE_REMOVED"
    ANNOTATION_CHANGE = "ANNOTATION_CHANGE"
    METADATA_CHANGE = "METADATA_CHANGE"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ChangeClassification(str, Enum):
    CONSEQUENTIAL = "consequential"
    COSMETIC = "cosmetic"
    METADATA = "metadata"


class FindingStatus(str, Enum):
    OPEN = "open"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class AnalysisStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RelationshipType(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    USES = "USES"
    MATES_WITH = "MATES_WITH"
    PART_OF = "PART_OF"
    GOVERNED_BY = "GOVERNED_BY"
    REFERENCES = "REFERENCES"
    SUPPLIES = "SUPPLIES"
    ASSEMBLED_INTO = "ASSEMBLED_INTO"


class DetectionMethod(str, Enum):
    STRUCTURED = "structured"      # drawing manifest diff (deterministic)
    CV_DIFF = "cv_diff"            # OpenCV registration + differencing
    VLM = "vlm"                    # vision-language interpretation
    HYBRID = "hybrid"              # CV candidates confirmed by VLM


class BoundingBox(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    page: int = 1
    sheet: str = "1/1"
    normalized: bool = False

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.width, self.height)


class Confidence(BaseModel):
    """Confidence is always accompanied by *why*, never a bare float."""

    model_config = ConfigDict(extra="allow")

    value: float = Field(ge=0.0, le=1.0)
    basis: str = "unknown"
    factors: dict[str, float] = Field(default_factory=dict)


class EvidenceRef(BaseModel):
    """Provenance record — no evidence without a source."""

    model_config = ConfigDict(extra="allow")

    evidence_id: str = ""
    evidence_type: str = "document"  # document | drawing | structured | graph
    document_id: str | None = None
    document_name: str = ""
    chunk_id: str | None = None
    page: int | None = None
    section: str = ""
    bbox: BoundingBox | None = None
    excerpt: str = ""
    score: float = 0.0
    component_id: str | None = None
    revision: str | None = None
    authority: str = "synthetic"
    retrieval_strategy: str = ""


class ToolCallRecord(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    transport: str = "in-process"
    latency_ms: float = 0.0
    mutating: bool = False
    result_summary: str = ""
    error: str | None = None
    execution_id: str = ""


class Page(BaseModel):
    page: int = 1
    page_size: int = 50
    total: int = 0
