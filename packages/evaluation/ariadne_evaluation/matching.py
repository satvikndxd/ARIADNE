"""Canonical detection↔ground-truth matching semantics.

Shared by the production blind evaluator (``apps/api/app/services/evaluation_service``)
and by external runners (``notebooks/ariadne_vlm_evaluation.ipynb``), so the
notebook can never drift into friendlier matching just to improve scores.

Region-level detectors localize *clusters* of changed pixels while ground truth
boxes are per-annotation, therefore:

* forward containment ≥ 0.5  — the detected region covers the true annotation;
* reverse containment ≥ 0.7  — a tiny detection (character-level text edit)
  lies inside the true annotation box;
* one detection may match several ground-truth entries (merged clusters).
"""
from __future__ import annotations

from typing import Any


def iou(a: dict, b: list) -> float:
    x1, y1 = max(a["x"], b[0]), max(a["y"], b[1])
    x2, y2 = min(a["x"] + a["width"], b[0] + b[2]), min(a["y"] + a["height"], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a["width"] * a["height"] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def containment(det: dict, gt_bbox: list) -> float:
    """Fraction of the ground-truth box inside the detected region."""
    x1, y1 = max(det["x"], gt_bbox[0]), max(det["y"], gt_bbox[1])
    x2, y2 = min(det["x"] + det["width"], gt_bbox[0] + gt_bbox[2]), \
        min(det["y"] + det["height"], gt_bbox[1] + gt_bbox[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    gt_area = gt_bbox[2] * gt_bbox[3]
    return inter / gt_area if gt_area > 0 else 0.0


def reverse_containment(det: dict, gt_bbox: list) -> float:
    """Fraction of the detected region inside the ground-truth box."""
    x1, y1 = max(det["x"], gt_bbox[0]), max(det["y"], gt_bbox[1])
    x2, y2 = min(det["x"] + det["width"], gt_bbox[0] + gt_bbox[2]), \
        min(det["y"] + det["height"], gt_bbox[1] + gt_bbox[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    det_area = det["width"] * det["height"]
    return inter / det_area if det_area > 0 else 0.0


def match_score(det: dict, gt_bbox: list) -> float:
    fwd = containment(det, gt_bbox)
    rev = reverse_containment(det, gt_bbox)
    score = max(fwd, 0.0 if fwd >= 0.5 else rev * 0.9)
    if fwd < 0.5 and rev >= 0.7:
        score = max(score, 0.5)
    return score


def match_detections(
    detections: list[dict], gt_entries: list[dict], threshold: float = 0.5
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy per-ground-truth matching (largest gt first).

    Returns ``(matched, fp_detection_idx, fn_gt_idx)`` where ``matched`` holds
    ``(gt_idx, detection_idx)`` pairs; a detection may serve several gt entries.
    """
    matched: list[tuple[int, int]] = []
    used_by: dict[int, int] = {}
    order = sorted(range(len(gt_entries)),
                   key=lambda i: -(gt_entries[i]["bbox_b"][2] * gt_entries[i]["bbox_b"][3]))
    for gi in order:
        gb = gt_entries[gi]["bbox_b"]
        best_i, best_s = -1, 0.0
        for di, det in enumerate(detections):
            s = match_score(det, gb)
            if s > best_s:
                best_i, best_s = di, s
        if best_i >= 0 and best_s >= threshold:
            used_by[best_i] = used_by.get(best_i, 0) + 1
            matched.append((gi, best_i))
        # fn recorded below
    matched_gt = {gi for gi, _ in matched}
    fn = [gi for gi in range(len(gt_entries)) if gi not in matched_gt]
    fp = [di for di in range(len(detections)) if di not in used_by]
    return matched, fp, fn


def weakly_localized(detections: list[dict], gt_bbox: list) -> bool:
    return any(0.0 < containment(d, gt_bbox) < 0.5 or 0.0 < reverse_containment(d, gt_bbox) < 0.7
               for d in detections)
