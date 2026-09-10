"""Candidate changed-region extraction (stages 3–5).

absdiff → adaptive threshold → morphological close → connected components.
Regions below an area floor are dropped (scan noise); overlapping boxes are
merged.  Output is a *candidate* list: interpretation happens later (VLM or
manifest), never here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int
    area: int
    mean_delta: float
    label: str = ""

    def iou(self, other: "Region") -> float:
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2, y2 = min(self.x + self.width, other.x + other.width), min(self.y + self.height, other.y + other.height)
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        union = self.area + other.area - inter
        return inter / union if union else 0.0

    def contains(self, x: float, y: float, pad: float = 6.0) -> bool:
        return (self.x - pad) <= x <= (self.x + self.width + pad) and (
            self.y - pad) <= y <= (self.y + self.height + pad)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "area": self.area, "mean_delta": round(self.mean_delta, 2)}


@dataclass
class DiffResult:
    regions: list[Region] = field(default_factory=list)
    changed_pixel_fraction: float = 0.0
    threshold: int = 0
    method: str = "absdiff_morphology_ccomponents"


def diff_regions(gray_a: np.ndarray, gray_b: np.ndarray, *, min_area: int = 90, dilate: int = 5) -> DiffResult:
    diff = cv2.absdiff(gray_a, gray_b)
    _, thresh = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate, dilate))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    closed = cv2.dilate(closed, kernel, iterations=1)
    count, _labels, stats, _cent = cv2.connectedComponentsWithStats(closed, connectivity=8)
    regions: list[Region] = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < min_area or w * h < min_area:
            continue
        mask = closed[y : y + h, x : x + w] > 0
        mean_delta = float(diff[y : y + h, x : x + w][mask].mean()) if mask.any() else 0.0
        regions.append(Region(int(x), int(y), int(w), int(h), int(area), mean_delta))
    regions = _merge(regions)
    changed = float((closed > 0).sum()) / float(closed.size)
    return DiffResult(regions=regions, changed_pixel_fraction=round(changed, 5), threshold=28)


def _merge(regions: list[Region], iou_floor: float = 0.02) -> list[Region]:
    merged: list[Region] = []
    for r in sorted(regions, key=lambda r: -r.area):
        hit = None
        for m in merged:
            if r.iou(m) > iou_floor or _near(r, m):
                hit = m
                break
        if hit is None:
            merged.append(r)
        else:
            x1, y1 = min(hit.x, r.x), min(hit.y, r.y)
            x2 = max(hit.x + hit.width, r.x + r.width)
            y2 = max(hit.y + hit.height, r.y + r.height)
            hit.x, hit.y, hit.width, hit.height = x1, y1, x2 - x1, y2 - y1
            hit.area += r.area
            hit.mean_delta = max(hit.mean_delta, r.mean_delta)
    return sorted(merged, key=lambda r: (r.y, r.x))


def _near(a: Region, b: Region, pad: int = 18) -> bool:
    return (
        a.x - pad < b.x + b.width
        and b.x - pad < a.x + a.width
        and a.y - pad < b.y + b.height
        and b.y - pad < a.y + a.height
    )
