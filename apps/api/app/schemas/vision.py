"""Strict VLM output contract.

Arbitrary prose never enters downstream analysis: the VLM response is parsed
into this model (or rejected → ``UNKNOWN``), and only these fields are stored,
cross-checked and displayed.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class VLMChangeType(str, Enum):
    DIMENSION_CHANGE = "DIMENSION_CHANGE"
    TOLERANCE_CHANGE = "TOLERANCE_CHANGE"
    GEOMETRIC_CHANGE = "GEOMETRIC_CHANGE"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    FEATURE_ADDED = "FEATURE_ADDED"
    FEATURE_REMOVED = "FEATURE_REMOVED"
    COMPONENT_ADDED = "COMPONENT_ADDED"
    COMPONENT_REMOVED = "COMPONENT_REMOVED"
    ANNOTATION_CHANGE = "ANNOTATION_CHANGE"
    METADATA_CHANGE = "METADATA_CHANGE"
    UNKNOWN = "UNKNOWN"


class VLMInterpretation(BaseModel):
    change_type: VLMChangeType = VLMChangeType.UNKNOWN
    old_value: str | None = None
    new_value: str | None = None
    feature: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""
    meaningful: bool | None = None
    visually_supported: bool = False
    error: str | None = None
    provider: str = ""
    latency_ms: float = 0.0

    @property
    def is_unknown(self) -> bool:
        return self.change_type == VLMChangeType.UNKNOWN or not self.visually_supported


VLM_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "change_type": {"type": "string", "enum": [t.value for t in VLMChangeType]},
        "old_value": {"type": ["string", "null"]},
        "new_value": {"type": ["string", "null"]},
        "feature": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "description": {"type": "string"},
        "meaningful": {"type": ["boolean", "null"]},
        "visually_supported": {"type": "boolean"},
    },
    "required": ["change_type", "confidence", "description", "visually_supported"],
}
