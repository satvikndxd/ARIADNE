"""BLIND revision analyzer — vision signals only.

Contract (enforced by ``tests/test_blind_separation.py``):

* this module accepts **two image paths** and nothing else;
* it imports no project-structure loader, no truth file helper, no database
  model — the guard test greps this source for the forbidden tokens;
* the evaluator (``services/evaluation_service.run_blind_evaluation``) opens
  the case truth file only *after* ``analyze_pair`` returned.

Pipeline: OpenCV registration → differencing → candidate regions → optional
VLM interpretation of each crop pair (+ difference overlay) → three-signal
consensus (CV presence vs VLM; structured signal is absent by design in blind
mode) → deterministic severity policy applied to VLM-reported values when
present.  The VLM never touches rules, permissions or state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.analysis.consensus import Signal, combine
from app.services.analysis.rules import severity_for_change
from app.services.vision import differencing, registration
from app.services.vision.providers import (
    VisionProvider,
    crop_region,
    diff_overlay,
    get_vision_provider,
)

log = get_logger(__name__)


@dataclass
class BlindDetection:
    bbox: dict[str, float]
    area: int
    mean_delta: float
    change_type: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    feature: str | None = None
    confidence: float = 0.0
    consensus: dict[str, Any] = field(default_factory=dict)
    vlm: dict[str, Any] | None = None
    predicted_severity: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "bbox": self.bbox,
            "area": self.area,
            "mean_delta": round(self.mean_delta, 2),
            "change_type": self.change_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "feature": self.feature,
            "confidence": round(self.confidence, 3),
            "consensus": self.consensus,
            "vlm": self.vlm,
            "predicted_severity": self.predicted_severity,
        }


@dataclass
class BlindResult:
    path_a: str
    path_b: str
    n_regions: int
    detections: list[BlindDetection] = field(default_factory=list)
    alignment: dict[str, Any] = field(default_factory=dict)
    vlm_active: bool = False
    method: str = "cv-only"
    latency_ms: float = 0.0


def _first_number(value: str | None) -> float | None:
    if not value:
        return None
    import re

    m = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(m.group(0)) if m else None


def analyze_pair(
    path_a: str | Path,
    path_b: str | Path,
    vision: VisionProvider | None = None,
    *,
    force_vlm: bool | None = None,
) -> BlindResult:
    """Analyze two revision images without any project/ground-truth knowledge."""
    import time

    t0 = time.perf_counter()
    provider = vision if vision is not None else get_vision_provider()
    vlm_active = provider.available() if force_vlm is None else bool(force_vlm and provider.available())
    pair = registration.load_pair(Path(path_a), Path(path_b))
    diff = differencing.diff_regions(pair.gray_a, pair.aligned_b, despeckle=True)

    result = BlindResult(
        path_a=str(path_a), path_b=str(path_b), n_regions=len(diff.regions),
        alignment={**pair.alignment.__dict__, "changed_pixel_fraction": diff.changed_pixel_fraction},
        vlm_active=vlm_active,
        method="cv+vlm" if vlm_active else "cv-only",
    )

    for region in diff.regions:
        bbox = {"x": float(region.x), "y": float(region.y),
                "width": float(region.width), "height": float(region.height)}
        cv_conf = round(min(0.9, 0.45 + 0.45 * min(1.0, region.mean_delta / 120.0)), 3)
        cv_signal = Signal("cv", True, None, None, None, cv_conf,
                           f"pixel-diff region area={region.area} mean_delta={region.mean_delta:.1f}")
        vlm_signal: Signal | None = None
        vlm_payload: dict[str, Any] | None = None
        if vlm_active:
            crop_a = crop_region(pair.img_a, bbox)
            crop_b = crop_region(pair.img_b, bbox)
            overlay = diff_overlay(pair.gray_a, pair.aligned_b, bbox)
            interp = provider.extract_structured_change(crop_a, crop_b, overlay)
            vlm_payload = interp.model_dump()
            if not interp.is_unknown:
                vlm_signal = Signal("vlm", True, interp.change_type.value, interp.old_value,
                                    interp.new_value, interp.confidence,
                                    interp.feature or interp.description)
        consensus = combine(
            None,
            cv_signal,
            vlm_signal if vlm_signal is not None else (
                Signal("vlm", False, detail=(vlm_payload or {}).get("description", "VLM not run"))
                if vlm_active else None
            ),
        )
        pred_type = vlm_signal.change_type if vlm_signal else None
        delta = None
        if vlm_signal:
            old_n, new_n = _first_number(vlm_signal.old_value), _first_number(vlm_signal.new_value)
            if old_n is not None and new_n is not None:
                delta = round(new_n - old_n, 4)
        severity = None
        if pred_type:
            severity, _cls = severity_for_change(pred_type, (vlm_signal.feature or "").lower(),
                                                 delta_mm=delta, fails=[], flags=[])
        result.detections.append(
            BlindDetection(
                bbox=bbox, area=region.area, mean_delta=region.mean_delta,
                change_type=pred_type, old_value=vlm_signal.old_value if vlm_signal else None,
                new_value=vlm_signal.new_value if vlm_signal else None,
                feature=vlm_signal.feature if vlm_signal else None,
                confidence=consensus.confidence, consensus=consensus.as_dict(),
                vlm=vlm_payload, predicted_severity=severity,
            )
        )
    result.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    return result
