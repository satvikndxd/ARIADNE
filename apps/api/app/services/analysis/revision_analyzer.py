"""RevisionAnalyzer — layered change detection.

    stage 1  normalisation            vision.registration.normalize
    stage 2  registration/alignment   vision.registration.align (ORB + RANSAC)
    stage 3  differencing             vision.differencing.diff_regions
    stage 4  candidate regions        connected components + merge
    stage 5  region extraction        manifest bboxes ∩ CV regions
    stage 6  interpretation           VLM (live) / manifest diff (deterministic)
    stage 7  structured output        ChangeCandidate list (strict schema)

The deterministic core is the *manifest diff*: the synthetic dataset ships a
ground-truth manifest per revision, so detection is exact and scoreable.  OpenCV
regions act as an independent second signal: a manifest change that CV also
sees gets high confidence and ``detection_method="hybrid"``; one CV sees but
the manifest does not know is reported as an *unmapped pixel difference*
(honest, low confidence) rather than being invented into a semantic change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import DrawingNotFoundError
from app.core.logging import Timer, get_logger
from app.db.models import Drawing, Revision
from app.schemas.common import BoundingBox, ChangeType, DetectionMethod
from app.services.analysis.consensus import Signal, combine
from app.services.vision import differencing, registration
from app.services.vision.providers import (
    VisionProvider,
    crop_region,
    diff_overlay,
    get_vision_provider,
    vision_active,
)

log = get_logger(__name__)

_KIND_TO_TYPE = {
    "dimension": ChangeType.DIMENSION_CHANGE,
    "geometry": ChangeType.GEOMETRIC_CHANGE,
    "feature": ChangeType.FEATURE_ADDED,
    "annotation": ChangeType.ANNOTATION_CHANGE,
    "metadata": ChangeType.METADATA_CHANGE,
    "component": ChangeType.COMPONENT_ADDED,
}


def _bb(bbox: list) -> BoundingBox:
    return BoundingBox(x=float(bbox[0]), y=float(bbox[1]), width=float(bbox[2]), height=float(bbox[3]))


@dataclass
class ChangeCandidate:
    change_type: ChangeType
    component_id: str | None
    title: str
    old_value: str | None = None
    new_value: str | None = None
    unit: str = ""
    numeric_delta: float | None = None
    location: BoundingBox = field(default_factory=BoundingBox)
    confidence: float = 0.0
    detection_method: DetectionMethod = DetectionMethod.STRUCTURED
    description: str = ""
    drawing_id: str | None = None
    semantic: str = ""
    kind: str = ""
    cv_confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyzerOutput:
    changes: list[ChangeCandidate] = field(default_factory=list)
    alignment: dict[str, Any] = field(default_factory=dict)
    cv_regions: list[dict] = field(default_factory=list)
    method: str = "structured"


class RevisionAnalyzer(Protocol):
    name: str

    def analyze(self, session: Session, rev_a: Revision, rev_b: Revision) -> AnalyzerOutput: ...


# --------------------------------------------------------------------------- #
def _load_manifest(drawing: Drawing) -> dict:
    path = Path(drawing.manifest_path) if drawing.manifest_path else None
    if path is None or not path.exists():
        raise DrawingNotFoundError(f"Manifest for drawing {drawing.id} is missing.")
    return json.loads(path.read_text())


def _diff_items(man_a: dict, man_b: dict, drawing_a: Drawing, drawing_b: Drawing, kind: str) -> list[ChangeCandidate]:
    kind_a = (drawing_a.metadata_json or {}).get("drawing_kind", "part")
    items_a = {it["id"]: it for it in man_a.get("items", []) if it.get("drawing", "part") == kind_a}
    items_b = {it["id"]: it for it in man_b.get("items", []) if it.get("drawing", "part") == kind_a}
    out: list[ChangeCandidate] = []

    for item_id in sorted(set(items_a) | set(items_b)):
        a, b = items_a.get(item_id), items_b.get(item_id)
        if a and b:
            tol_changed = a.get("tolerance") != b.get("tolerance")
            val_changed = a.get("value") != b.get("value") or a.get("label") != b.get("label")
            if not (tol_changed or val_changed):
                continue
            if val_changed and tol_changed:
                ctype = _KIND_TO_TYPE.get(b["kind"], ChangeType.ANNOTATION_CHANGE)
            elif tol_changed:
                ctype = ChangeType.TOLERANCE_CHANGE
            else:
                ctype = _KIND_TO_TYPE.get(b["kind"], ChangeType.ANNOTATION_CHANGE)
                if b["kind"] == "annotation" and b["semantic"] == "material_note":
                    ctype = ChangeType.MATERIAL_CHANGE
            delta = None
            va, vb = a.get("value"), b.get("value")
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                delta = round(float(vb) - float(va), 4)
            out.append(
                ChangeCandidate(
                    change_type=ctype,
                    component_id=b.get("component_id"),
                    title=f"{b['semantic'].replace('_', ' ')}: {a.get('label')} → {b.get('label')}",
                    old_value=str(a.get("value")),
                    new_value=str(b.get("value")),
                    unit=b.get("unit", ""),
                    numeric_delta=delta,
                    location=BoundingBox(x=b["bbox"][0], y=b["bbox"][1], width=b["bbox"][2], height=b["bbox"][3]),
                    description=f"{a.get('label')} → {b.get('label')}",
                    drawing_id=drawing_b.id,
                    semantic=b.get("semantic", b["id"]),
                    kind=b["kind"],
                    metadata={"tolerance_old": a.get("tolerance"), "tolerance_new": b.get("tolerance"),
                              "item_id": item_id},
                )
            )
        elif b:
            ctype = (ChangeType.COMPONENT_ADDED if b["kind"] == "component"
                     else ChangeType.FEATURE_ADDED if b["kind"] == "feature"
                     else ChangeType.ANNOTATION_CHANGE)
            if b["kind"] == "annotation" and b["semantic"] == "material_note":
                ctype = ChangeType.MATERIAL_CHANGE
            out.append(
                ChangeCandidate(
                    change_type=ctype, component_id=b.get("component_id"),
                    title=f"added: {b.get('label')}", old_value=None, new_value=str(b.get("value")),
                    unit=b.get("unit", ""), location=_bb(b["bbox"]),
                    description=f"New item at Rev B: {b.get('label')}",
                    drawing_id=drawing_b.id, semantic=b.get("semantic", b["id"]), kind=b["kind"],
                    metadata={"item_id": item_id},
                )
            )
        else:
            out.append(
                ChangeCandidate(
                    change_type=(ChangeType.COMPONENT_REMOVED if a["kind"] == "component"
                                 else ChangeType.FEATURE_REMOVED),
                    component_id=a.get("component_id"), title=f"removed: {a.get('label')}",
                    old_value=str(a.get("value")), new_value=None, unit=a.get("unit", ""),
                    location=_bb(a["bbox"]),
                    description=f"Item present at Rev A only: {a.get('label')}",
                    drawing_id=drawing_a.id, semantic=a.get("semantic", a["id"]), kind=a["kind"],
                    metadata={"item_id": item_id},
                )
            )
    return out


def _dedupe(cands: list[ChangeCandidate]) -> list[ChangeCandidate]:
    seen: set[tuple] = set()
    out: list[ChangeCandidate] = []
    for c in cands:
        key = (c.change_type.value, c.component_id, c.old_value, c.new_value, c.semantic)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _cv_for_drawing(drawing_a: Drawing, drawing_b: Drawing) -> tuple[list[differencing.Region], dict]:
    pa, pb = Path(drawing_a.storage_path), Path(drawing_b.storage_path)
    if not pa.exists() or not pb.exists():
        return [], {"ok": False, "note": "drawing files missing"}
    pair = registration.load_pair(pa, pb)
    res = differencing.diff_regions(pair.gray_a, pair.aligned_b)
    return res.regions, {**pair.alignment.__dict__, "changed_pixel_fraction": res.changed_pixel_fraction}


def _region_confirms(bbox: BoundingBox, regions: list[differencing.Region]) -> bool:
    target = differencing.Region(int(bbox.x), int(bbox.y), max(1, int(bbox.width)), max(1, int(bbox.height)),
                                 area=int(bbox.width * bbox.height), mean_delta=0.0)
    for r in regions:
        if r.iou(target) > 0.03 or r.contains(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2, pad=14):
            return True
    return False


class StructuredRevisionAnalyzer:
    """Deterministic manifest diff + OpenCV second signal + optional VLM third.

    The VLM is a perception signal only; its interpretation is cross-checked
    against structured and CV signals (``analysis/consensus.py``) and any
    disagreement is surfaced, never silently merged.
    """

    def __init__(self, vision: VisionProvider | None = None) -> None:
        self._vision = vision or get_vision_provider()
        self.name = "structured+cv+vlm" if vision_active() else "structured+cv"

    def analyze(self, session: Session, rev_a: Revision, rev_b: Revision) -> AnalyzerOutput:
        out = AnalyzerOutput(method=self.name)
        kinds = ("part", "assembly")
        for kind in kinds:
            da = next((d for d in rev_a.drawings if (d.metadata_json or {}).get("drawing_kind") == kind), None)
            db = next((d for d in rev_b.drawings if (d.metadata_json or {}).get("drawing_kind") == kind), None)
            if not da or not db:
                continue
            man_a, man_b = _load_manifest(da), _load_manifest(db)
            regions: list[differencing.Region] = []
            with Timer() as t_cv:
                regions, alignment = _cv_for_drawing(da, db)
            log.info("cv_diff", drawing_kind=kind, regions=len(regions), ms=t_cv.ms,
                     changed_fraction=alignment.get("changed_pixel_fraction"))
            if kind == "part":
                out.alignment = alignment
                out.cv_regions = [r.as_dict() for r in regions]
            for cand in _dedupe(_diff_items(man_a, man_b, da, db, kind)):
                if cand.drawing_id == db.id:
                    cand.cv_confirmed = _region_confirms(cand.location, regions)
                cand.confidence = 0.94 if cand.cv_confirmed else 0.71
                cand.detection_method = DetectionMethod.HYBRID if cand.cv_confirmed else DetectionMethod.STRUCTURED
                out.changes.append(cand)
            # CV regions the manifest knows nothing about
            known = [c.location for c in out.changes if c.drawing_id == db.id]
            for r in regions:
                if any(_region_confirms(BoundingBox(x=k.x, y=k.y, width=k.width, height=k.height), [r]) for k in known):
                    continue
                if r.area < 400:
                    continue
                out.changes.append(
                    ChangeCandidate(
                        change_type=ChangeType.ANNOTATION_CHANGE,
                        component_id=man_b.get("component_id"),
                        title="unmapped pixel difference (CV only)",
                        old_value=None, new_value=None,
                        location=BoundingBox(x=r.x, y=r.y, width=r.width, height=r.height),
                        confidence=0.35, detection_method=DetectionMethod.CV_DIFF,
                        description="OpenCV detected a pixel-level difference with no matching manifest item; "
                                    "reported for reviewer inspection, not interpreted.",
                        drawing_id=db.id, semantic="unmapped_cv_region", kind="cv",
                        metadata={"area": r.area, "mean_delta": r.mean_delta},
                    )
                )
        self._attach_vlm_signals(out, rev_a, rev_b)
        return out

    # ------------------------------------------------------------------ #
    def _attach_vlm_signals(self, out: AnalyzerOutput, rev_a: Revision, rev_b: Revision) -> None:
        if not vision_active():
            for cand in out.changes:
                cand.metadata.setdefault("signals", combine(
                    Signal("structured", True, cand.change_type.value, cand.old_value, cand.new_value,
                           0.95, "manifest diff"),
                    Signal("cv", cand.cv_confirmed, None, None, None,
                           0.8 if cand.cv_confirmed else 0.0,
                           "pixel-diff region confirmed" if cand.cv_confirmed else "no matching pixel-diff region"),
                    None,
                ).as_dict())
            return
        import cv2  # deferred: only needed when a VLM endpoint is configured

        da = next((d for d in rev_a.drawings if (d.metadata_json or {}).get("drawing_kind") == "part"), None)
        db = next((d for d in rev_b.drawings if (d.metadata_json or {}).get("drawing_kind") == "part"), None)
        if da is None or db is None:
            return
        img_a, img_b = cv2.imread(str(Path(da.storage_path))), cv2.imread(str(Path(db.storage_path)))
        gray_a = registration.normalize(registration.load_grayscale(Path(da.storage_path)))
        gray_b = registration.normalize(registration.load_grayscale(Path(db.storage_path)))
        for cand in out.changes:
            if cand.kind == "cv" or cand.drawing_id != db.id:
                continue
            bbox = {"x": cand.location.x, "y": cand.location.y,
                    "width": cand.location.width, "height": cand.location.height}
            crop_a, crop_b = crop_region(img_a, bbox), crop_region(img_b, bbox)
            overlay = diff_overlay(gray_a, gray_b, bbox)
            interp = self._vision.extract_structured_change(
                crop_a, crop_b, overlay,
                context={"component_id": cand.component_id, "candidate_change_type": cand.change_type.value},
            )
            cand.metadata["vlm"] = interp.model_dump()
            vlm_signal = None if interp.is_unknown else Signal(
                "vlm", True, interp.change_type.value, interp.old_value, interp.new_value,
                interp.confidence, interp.description,
            )
            cand.metadata["signals"] = combine(
                Signal("structured", True, cand.change_type.value, cand.old_value, cand.new_value,
                       0.95, "manifest diff"),
                Signal("cv", cand.cv_confirmed, None, None, None,
                       0.8 if cand.cv_confirmed else 0.0,
                       "pixel-diff region confirmed" if cand.cv_confirmed else "no matching pixel-diff region"),
                vlm_signal if vlm_signal else Signal("vlm", False, detail=interp.description or "UNKNOWN"),
            ).as_dict()
            if cand.metadata["signals"]["status"] == "CONFLICT":
                cand.confidence = round(min(cand.confidence, cand.metadata["signals"]["confidence"]), 3)


def get_revision_analyzer() -> RevisionAnalyzer:
    return StructuredRevisionAnalyzer(get_vision_provider())
