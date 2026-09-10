"""Three-signal cross-check behaviour (structured vs CV vs VLM)."""
from __future__ import annotations

from app.services.analysis.consensus import Signal, combine, normalize_value


def test_value_normalization():
    assert normalize_value("Ø48.0 ±0.10 mm") == normalize_value("48.0")
    assert normalize_value("52.0 mm") != normalize_value("58.0")
    assert normalize_value(None) is None


def test_agreed_when_all_signals_match():
    c = combine(
        Signal("structured", True, "DIMENSION_CHANGE", "48.0", "52.0", 0.95, "manifest"),
        Signal("cv", True, None, None, None, 0.8, "region confirmed"),
        Signal("vlm", True, "DIMENSION_CHANGE", "48.0 mm", "52.0 mm", 0.92, "flange larger"),
    )
    assert c.status == "AGREED"
    assert c.agreement["change_type"] == "DIMENSION_CHANGE"
    assert c.confidence > 0.85


def test_conflict_is_surfaced_not_merged():
    c = combine(
        Signal("structured", True, "DIMENSION_CHANGE", "48.0", "52.0", 0.95, "manifest"),
        Signal("cv", True, None, None, None, 0.8, "region"),
        Signal("vlm", True, "DIMENSION_CHANGE", "48.0", "58.0", 0.9, "misread"),
    )
    assert c.status == "CONFLICT"
    assert any("new value disagreement" in n for n in c.notes)
    assert c.signals["vlm"]["new_value"] == "58.0"      # disagreement stays inspectable
    assert c.signals["structured"]["new_value"] == "52.0"
    assert c.confidence < 0.85                            # conflict lowers confidence


def test_uncertain_with_single_signal():
    c = combine(None, Signal("cv", True, None, None, None, 0.7, "region"), None)
    assert c.status == "UNCERTAIN"


def test_unknown_vlm_does_not_vote():
    c = combine(
        Signal("structured", True, "TOLERANCE_CHANGE", "±0.10", "±0.05", 0.9, "manifest"),
        Signal("cv", True, None, None, None, 0.75, "region"),
        Signal("vlm", False, detail="UNKNOWN"),
    )
    assert c.status == "AGREED"          # structured+cv agree; VLM abstains
    assert c.signals["vlm"]["present"] is False


def test_no_signal():
    assert combine(None, None, None).status == "NO_SIGNAL"
