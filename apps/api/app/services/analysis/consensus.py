"""Three-signal cross-check: structured project data vs CV vs VLM.

No signal silently overrides another.  The layer reports one of:

``AGREED``     ≥2 active signals match on change type and normalized values
               (a CV presence-confirmation counts as agreement on presence);
``CONFLICT``   ≥2 active signals disagree on type or on a normalized value;
``UNCERTAIN``  a single active signal, or the VLM returned UNKNOWN.

Every signal's raw values travel with the verdict so a reviewer can inspect
the disagreement instead of trusting a merged answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_value(value: str | None) -> str | None:
    """`Ø48.0 ±0.10 mm` and `48.0` normalize to the same primary numeric token.

    The first number is the engineering value; tolerance suffixes are handled
    by the change-type signal (TOLERANCE_CHANGE), not by value equality.
    """
    if value is None:
        return None
    nums = _NUM.findall(value.replace("±", " "))
    if nums:
        return f"{float(nums[0]):g}"
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return cleaned or None


@dataclass
class Signal:
    source: str                      # structured | cv | vlm
    present: bool
    change_type: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    confidence: float = 0.0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "present": self.present, "change_type": self.change_type,
            "old_value": self.old_value, "new_value": self.new_value,
            "confidence": round(self.confidence, 3), "detail": self.detail,
        }


@dataclass
class Consensus:
    status: str                      # AGREED | CONFLICT | UNCERTAIN | NO_SIGNAL
    signals: dict[str, Any] = field(default_factory=dict)
    agreement: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "signals": self.signals, "agreement": self.agreement,
            "confidence": round(self.confidence, 3), "notes": self.notes,
        }


def combine(structured: Signal | None, cv: Signal | None, vlm: Signal | None) -> Consensus:
    active = [s for s in (structured, cv, vlm) if s is not None and s.present]
    signals = {s.source: s.as_dict() for s in (structured, cv, vlm) if s is not None}
    if not active:
        return Consensus(status="NO_SIGNAL", signals=signals, confidence=0.0,
                         notes=["no signal reported a change in this region"])

    notes: list[str] = []
    typed = [s for s in active if s.change_type and s.change_type != "UNKNOWN"]
    valued = [s for s in active if normalize_value(s.old_value) or normalize_value(s.new_value)]

    types = {s.change_type for s in typed}
    old_vals = {normalize_value(s.old_value) for s in valued if normalize_value(s.old_value)}
    new_vals = {normalize_value(s.new_value) for s in valued if normalize_value(s.new_value)}

    conflicts = []
    if len(types) > 1:
        conflicts.append(f"change type disagreement: {sorted(types)}")
    if len(old_vals) > 1:
        conflicts.append(f"old value disagreement: {sorted(old_vals)}")
    if len(new_vals) > 1:
        conflicts.append(f"new value disagreement: {sorted(new_vals)}")

    if vlm is not None and vlm.present and vlm.change_type == "UNKNOWN":
        notes.append("VLM returned UNKNOWN (uncertain by design)")

    agreeing = len(typed) >= 2 or (len(valued) >= 2 and not conflicts) or (
        structured and cv and structured.present and cv.present and len(typed) <= 1)
    if conflicts:
        status = "CONFLICT"
        notes.extend(conflicts)
    elif len(active) == 1:
        status = "UNCERTAIN"
        notes.append(f"single active signal: {active[0].source}")
    elif agreeing:
        status = "AGREED"
    else:
        status = "UNCERTAIN"
        notes.append("signals present but not comparable (presence-only)")

    confidences = [s.confidence for s in active if s.confidence > 0]
    base = sum(confidences) / len(confidences) if confidences else 0.5
    bonus = 0.10 if status == "AGREED" else (-0.15 if status == "CONFLICT" else 0.0)
    confidence = max(0.0, min(0.98, base + bonus))

    agreement = {
        "change_type": next(iter(types)) if len(types) == 1 else None,
        "old_value": next(iter(old_vals)) if len(old_vals) == 1 else None,
        "new_value": next(iter(new_vals)) if len(new_vals) == 1 else None,
    }
    return Consensus(status=status, signals=signals, agreement=agreement,
                     confidence=confidence, notes=notes)
