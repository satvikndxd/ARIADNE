"""Deterministic rule engine: the LLM never does arithmetic here."""
from __future__ import annotations

from app.services.analysis.rules import CheckContext, evaluate_rule, severity_for_change


def test_radial_clearance_fails_for_rev_b_geometry():
    ctx = CheckContext(
        props_a={"flange_dia": 48.0, "fastener_size": "M10"},
        props_b={"flange_dia": 52.0, "fastener_size": "M10"},
        related={"cmp_chassis_interface": {"aperture_dia_mm": 54.0}},
    )
    res = evaluate_rule("ORN-FS-017 §4.2",
                        {"rule": "min_radial_clearance", "applies_from_size": "M10", "min_clearance_mm": 3.0}, ctx)
    assert res.result == "fail"
    assert res.margin == -2.0
    assert res.inputs["clearance"] == 1.0


def test_radial_clearance_passes_for_rev_a_geometry():
    ctx = CheckContext(props_a={}, props_b={"flange_dia": 48.0, "fastener_size": "M10"},
                       related={"x": {"aperture_dia_mm": 54.0}})
    res = evaluate_rule("ORN-FS-017 §4.2",
                        {"rule": "min_radial_clearance", "applies_from_size": "M10", "min_clearance_mm": 3.0}, ctx)
    assert res.result == "pass"
    assert res.margin == 0.0


def test_tolerance_class_rule():
    ctx = CheckContext(props_b={"flange_dia": 52.0, "flange_tol": 0.10})
    res = evaluate_rule("ORN-MM-042 §3.2",
                        {"rule": "tolerance_class", "field": "flange_dia", "tol_field": "flange_tol",
                         "threshold": 50.0, "below": 0.10, "above": 0.05}, ctx)
    assert res.result == "fail"  # Ø52 requires ±0.05


def test_hole_clearance_and_enum_and_limit():
    ctx = CheckContext(props_b={"bolt_hole_dia": 10.5, "fastener_size": "M10"})
    assert evaluate_rule("c", {"rule": "hole_clearance", "field": "bolt_hole_dia",
                               "fastener_field": "fastener_size", "nominal_clearance_mm": 0.5,
                               "tolerance_mm": 0.2}, ctx).result == "pass"
    assert evaluate_rule("c", {"rule": "enum", "field": "material", "allowed": ["AL-7075-T6"]},
                         CheckContext(props_b={"material": "STEEL"})).result == "fail"
    assert evaluate_rule("c", {"rule": "numeric_limit", "field": "mass_g", "op": "<=", "limit": 450.0},
                         CheckContext(props_b={"mass_g": 438.0})).result == "pass"


def test_severity_policy():
    sev, cls = severity_for_change("DIMENSION_CHANGE", "flange_diameter", delta_mm=4.0, fails=[], flags=[])
    assert sev == "high" and cls == "consequential"
    sev, cls = severity_for_change("METADATA_CHANGE", "title_block.revision", delta_mm=None, fails=[], flags=[])
    assert sev == "low" and cls == "metadata"
    sev, _ = severity_for_change("ANNOTATION_CHANGE", "fastener_size", delta_mm=None, fails=[], flags=[])
    assert sev == "high"
