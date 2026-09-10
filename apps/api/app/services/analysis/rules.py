"""Deterministic engineering checks.

The LLM never does arithmetic here.  Every rule is plain Python over structured
component properties and retrieved requirement metadata, and every result
records its inputs so a reviewer can re-derive it by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FASTENER_MM = {"M4": 4.0, "M5": 5.0, "M6": 6.0, "M8": 8.0, "M10": 10.0, "M12": 12.0, "M14": 14.0, "M16": 16.0}


@dataclass
class CheckContext:
    props_a: dict[str, Any] = field(default_factory=dict)
    props_b: dict[str, Any] = field(default_factory=dict)
    related: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_fields: set[str] = field(default_factory=set)


@dataclass
class CheckResult:
    requirement_code: str
    rule: str
    description: str
    result: str  # pass | fail | flag | n/a
    margin: float | None = None
    unit: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    field: str = ""
    severity: str = "info"

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_code": self.requirement_code,
            "rule": self.rule,
            "description": self.description,
            "result": self.result,
            "margin": self.margin,
            "unit": self.unit,
            "inputs": self.inputs,
            "field": self.field,
            "severity": self.severity,
            "evaluated_deterministically": True,
        }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_rule(code: str, rule: dict, ctx: CheckContext) -> CheckResult:
    kind = rule.get("rule", "")
    a, b, rel = ctx.props_a, ctx.props_b, ctx.related

    def base(result: str, margin: float | None = None, unit: str = "", **inputs: Any) -> CheckResult:
        return CheckResult(
            requirement_code=code, rule=kind, description=rule.get("description", kind),
            result=result, margin=None if margin is None else round(margin, 3), unit=unit,
            inputs={k: v for k, v in inputs.items() if v is not None},
            field=rule.get("field", ""),
            severity="high" if result == "fail" else ("medium" if result == "flag" else "info"),
        )

    if kind == "numeric_range":
        v = _num(b.get(rule["field"]))
        if v is None:
            return base("n/a")
        lo, hi = float(rule["min"]), float(rule["max"])
        ok = lo <= v <= hi
        return base("pass" if ok else "fail", min(v - lo, hi - v), "mm", value=v, min=lo, max=hi)

    if kind == "tolerance_class":
        v, tol = _num(b.get(rule["field"])), _num(b.get(rule["tol_field"]))
        if v is None or tol is None:
            return base("n/a")
        expected = float(rule["below"] if v <= float(rule["threshold"]) else rule["above"])
        ok = abs(tol - expected) < 1e-9
        return base("pass" if ok else "fail", abs(tol - expected), "mm", value=v, stated_tolerance=tol,
                    required_tolerance=expected)

    if kind == "hole_clearance":
        hole = _num(b.get(rule["field"]))
        size = b.get(rule["fastener_field"])
        nominal = FASTENER_MM.get(str(size))
        if hole is None or nominal is None:
            return base("n/a")
        expected = nominal + float(rule["nominal_clearance_mm"])
        dev = hole - expected
        ok = abs(dev) <= float(rule["tolerance_mm"])
        return base("pass" if ok else "fail", abs(dev), "mm", hole_diameter=hole, fastener=size,
                    expected_hole=expected)

    if kind == "numeric_limit":
        v = _num(b.get(rule["field"]))
        limit = float(rule["limit"])
        if v is None:
            return base("n/a")
        ok = v <= limit if rule["op"] == "<=" else v >= limit
        margin = (limit - v) if rule["op"] == "<=" else (v - limit)
        return base("pass" if ok else "fail", margin, "", value=v, limit=limit, op=rule["op"])

    if kind == "min_radial_clearance":
        size = str(b.get("fastener_size", "M10"))
        if FASTENER_MM.get(size, 0.0) < FASTENER_MM.get(str(rule.get("applies_from_size", "M10")), 10.0):
            return base("n/a", fastener=size, note="rule applies from M10 upward")
        flange = _num(b.get("flange_dia"))
        aperture = None
        for props in rel.values():
            if "aperture_dia_mm" in props:
                aperture = _num(props["aperture_dia_mm"])
                break
        if flange is None or aperture is None:
            return base("n/a", note="aperture or flange diameter missing")
        clearance = (aperture - flange) / 2.0
        need = float(rule["min_clearance_mm"])
        return base("pass" if clearance >= need else "fail", clearance - need, "mm",
                    flange_diameter=flange, mating_aperture=aperture, clearance=round(clearance, 3),
                    required=need)

    if kind == "relative_increase":
        va, vb = _num(a.get(rule["field"])), _num(b.get(rule["field"]))
        if not va or vb is None:
            return base("n/a")
        pct = (vb - va) / va * 100.0
        ok = pct <= float(rule["max_pct"])
        return base("pass" if ok else "flag", float(rule["max_pct"]) - pct, "%",
                    rev_a=va, rev_b=vb, increase_pct=round(pct, 2))

    if kind == "delta_threshold":
        va, vb = _num(a.get(rule["field"])), _num(b.get(rule["field"]))
        if va is None or vb is None:
            return base("n/a")
        delta = abs(vb - va)
        ok = delta <= float(rule["threshold_mm"])
        return base("pass" if ok else "flag", float(rule["threshold_mm"]) - delta, "mm",
                    delta=round(delta, 2), threshold=rule["threshold_mm"])

    if kind == "enum":
        v = b.get(rule["field"])
        if v is None:
            return base("n/a")
        return base("pass" if v in rule["allowed"] else "fail", None, "", value=v, allowed=rule["allowed"])

    if kind == "channel_geometry_reanalysis":
        changed = a.get("cooling_channel") != b.get("cooling_channel")
        return base("flag" if changed else "pass", None, "",
                    rev_a=a.get("cooling_channel"), rev_b=b.get("cooling_channel"))

    if kind == "revision_fastener_reevaluation":
        changed = a.get("fastener_size") != b.get("fastener_size")
        return base("flag" if changed else "pass", None, "",
                    rev_a=a.get("fastener_size"), rev_b=b.get("fastener_size"))

    return base("n/a", note=f"rule '{kind}' is a process rule; not machine-evaluable")


def severity_for_change(change_type: str, semantic: str, *, delta_mm: float | None,
                        fails: list[CheckResult], flags: list[CheckResult]) -> tuple[str, str]:
    """Return (severity, classification) using deterministic policy."""
    if any(f.field and f.field == semantic for f in fails):
        return "high", "consequential"
    if change_type in ("MATERIAL_CHANGE",):
        return "medium", "consequential"
    if change_type in ("DIMENSION_CHANGE", "GEOMETRIC_CHANGE"):
        if delta_mm is not None and abs(delta_mm) >= 1.0:
            return "high", "consequential"
        return "medium", "consequential"
    if change_type in ("TOLERANCE_CHANGE", "FEATURE_ADDED", "FEATURE_REMOVED", "COMPONENT_ADDED"):
        return "medium", "consequential"
    if change_type == "ANNOTATION_CHANGE":
        if semantic in ("fastener_size", "fastener_callout"):
            return "high", "consequential"
        return "low", "cosmetic"
    if change_type in ("METADATA_CHANGE", "COMPONENT_REMOVED"):
        return "low", "metadata" if change_type == "METADATA_CHANGE" else "consequential"
    if flags:
        return "medium", "consequential"
    return "low", "cosmetic"
