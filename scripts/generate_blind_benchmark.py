#!/usr/bin/env python3
"""Generate the BLIND revision benchmark.

    data/evaluation/blind/case_NNN/
        rev_a.png            ← all the analyzer is allowed to see
        rev_b.png            ←
        ground_truth.json    ← evaluator-only, loaded AFTER analysis

Separation is enforced at three levels:
  1. directory contract — cases contain exactly these three files (no manifests,
     no parameter dumps);
  2. module contract — ``app.services.analysis.blind`` accepts only two image
     paths and imports no manifest/ground-truth helper (guarded by a test);
  3. process contract — ``evaluation_service.run_blind_evaluation`` runs the
     analyzer first and opens ``ground_truth.json`` only afterwards.

Cases are deliberately hard: sub-millimetre deltas, tolerance-only text edits,
hole add/remove, annotation *moves* (same text, new position), material swaps,
multi-change revisions, speckle noise, title-block-only edits and
geometrically similar combinations.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OUT = REPO_ROOT / "data" / "evaluation" / "blind"

_spec = importlib.util.spec_from_file_location("gen_drawings", REPO_ROOT / "scripts" / "generate_drawings.py")
gd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gd)

from app.services.analysis.rules import severity_for_change  # noqa: E402  (expected-impact labels only)

BASE = gd.REV_A

# (label, overrides_b, extra_a, extra_b, difficulty, note)
CASES: list[tuple[str, dict, dict, dict, str, str]] = [
    ("dim_tiny", {"flange_dia": 48.5}, {}, {}, "hard", "0.5 mm flange delta"),
    ("dim_large", {"flange_dia": 52.0}, {}, {}, "easy", "4 mm flange delta"),
    ("tolerance_tight", {"flange_tol": 0.05}, {}, {}, "medium", "tolerance text only"),
    ("tolerance_loose", {"flange_tol": 0.15}, {}, {}, "medium", "tolerance text only"),
    ("hole_add", {"threaded_hole": {"size": "M6", "depth": 12.0}}, {}, {}, "medium", "new tapped hole"),
    ("hole_add_small", {"threaded_hole": {"size": "M4", "depth": 8.0}}, {}, {}, "hard", "small new hole"),
    ("hole_remove", {}, {"threaded_hole": {"size": "M6", "depth": 12.0}}, {}, "medium", "hole removed"),
    ("hole_resize", {"bolt_hole_dia": 10.5}, {}, {}, "medium", "bolt holes upsized"),
    ("annotation_move", {}, {}, {"notes_order": [2, 0, 1, 3, 4], "notes_dy": 10}, "hard",
     "same notes, moved positions"),
    ("material_swap", {"material": "AL-6061-T6"}, {}, {}, "medium", "material note content"),
    ("finish_swap", {"finish": "HARD ANODIZE 25µm PER ORN-MF-300 §6.3"}, {}, {}, "medium", "finish note"),
    ("multi_revb", {"flange_dia": 52.0, "flange_tol": 0.05, "bolt_hole_dia": 10.5,
                    "threaded_hole": {"size": "M6", "depth": 12.0}, "mass_g": 438.0}, {}, {}, "easy",
     "five simultaneous changes"),
    ("noise_only", {}, {"noise_seed": 7}, {"noise_seed": 9}, "trap", "no engineering change, speckle noise"),
    ("noise_plus_dim", {"flange_dia": 49.0}, {"noise_seed": 3}, {"noise_seed": 11}, "hard",
     "small delta under noise"),
    ("title_only", {"date": "2026-04-01", "mass_g": 415.0}, {}, {}, "trap", "title-block/metadata only"),
    ("channel_geom", {"cooling_channel": "serpentine"}, {}, {}, "medium", "cooling channel geometry"),
    ("pattern_shift", {"pattern_pitch": 68.0}, {}, {}, "medium", "hole pattern pitch"),
    ("plate_grow", {"plate_size": 94.0}, {}, {}, "medium", "plate outline"),
    ("bore_grow", {"bore_dia": 18.0}, {}, {}, "medium", "centre bore"),
    ("height_tiny", {"overall_height": 22.5}, {}, {}, "hard", "0.5 mm height delta"),
    ("similar_combo_a", {"flange_dia": 50.0, "bolt_hole_dia": 9.5}, {}, {}, "hard",
     "two similar-magnitude deltas"),
    ("similar_combo_b", {"plate_size": 92.0, "pattern_pitch": 66.0}, {}, {}, "hard",
     "outline vs pattern, similar scale"),
    ("mass_note_only", {"mass_g": 428.0}, {}, {}, "trap", "mass note + title block only"),
    ("move_plus_dim", {"flange_dia": 51.0}, {}, {"notes_order": [4, 3, 2, 1, 0], "notes_dy": -6}, "hard",
     "annotation move combined with dimension change"),
]

_TYPE_BY_KIND = {
    "dimension": "DIMENSION_CHANGE",
    "geometry": "GEOMETRIC_CHANGE",
    "feature": "FEATURE_ADDED",
    "annotation": "ANNOTATION_CHANGE",
    "metadata": "METADATA_CHANGE",
    "component": "COMPONENT_ADDED",
}


def _geometry_truth(rev_a: dict, rev_b: dict) -> list[dict]:
    """Ground truth for *geometric* pixel changes (rings, outlines, channels).

    Annotation boxes alone under-specify what visibly changed: resizing the
    flange moves the drawn circle, not just its dimension text.
    """
    FCX, FCY, MM = gd.FRONT_CX, gd.FRONT_CY, gd.MM
    SX, SY = gd.SIDE_X, gd.SIDE_Y
    out = []

    def ring(sem, dia_a, dia_b, ctype="GEOMETRIC_CHANGE"):
        r = max(dia_a, dia_b) / 2 * MM
        return {"semantic": f"{sem}_geometry", "change_type": ctype, "old_value": str(dia_a),
                "new_value": str(dia_b), "numeric_delta": round(dia_b - dia_a, 4),
                "bbox_b": [FCX - r, FCY - r, 2 * r, 2 * r], "component_id": "cmp_motor_mount",
                "expected_severity": "medium", "expected_classification": "consequential",
                "moved_only": False}

    for sem, key in (("flange", "flange_dia"), ("bore", "bore_dia")):
        if rev_a[key] != rev_b[key]:
            out.append(ring(sem, rev_a[key], rev_b[key]))
    if rev_a["bolt_hole_dia"] != rev_b["bolt_hole_dia"] or rev_a["pattern_pitch"] != rev_b["pattern_pitch"]:
        half = max(rev_a["pattern_pitch"], rev_b["pattern_pitch"]) / 2 * MM + \
            max(rev_a["bolt_hole_dia"], rev_b["bolt_hole_dia"]) / 2 * MM + 6
        out.append({"semantic": "bolt_holes_geometry", "change_type": "GEOMETRIC_CHANGE",
                    "old_value": str(rev_a["bolt_hole_dia"]), "new_value": str(rev_b["bolt_hole_dia"]),
                    "numeric_delta": round(rev_b["bolt_hole_dia"] - rev_a["bolt_hole_dia"], 4),
                    "bbox_b": [FCX - half, FCY - half, 2 * half, 2 * half],
                    "component_id": "cmp_motor_mount", "expected_severity": "medium",
                    "expected_classification": "consequential", "moved_only": False})
    if rev_a["plate_size"] != rev_b["plate_size"]:
        half = max(rev_a["plate_size"], rev_b["plate_size"]) / 2 * MM
        out.append({"semantic": "plate_geometry", "change_type": "GEOMETRIC_CHANGE",
                    "old_value": str(rev_a["plate_size"]), "new_value": str(rev_b["plate_size"]),
                    "numeric_delta": round(rev_b["plate_size"] - rev_a["plate_size"], 4),
                    "bbox_b": [FCX - half, FCY - half, 2 * half, 2 * half],
                    "component_id": "cmp_motor_mount", "expected_severity": "medium",
                    "expected_classification": "consequential", "moved_only": False})
    if rev_a["overall_height"] != rev_b["overall_height"] or rev_a["cooling_channel"] != rev_b["cooling_channel"]:
        hh = max(rev_a["overall_height"], rev_b["overall_height"]) * MM
        out.append({"semantic": "side_view_geometry", "change_type": "GEOMETRIC_CHANGE",
                    "old_value": rev_a["cooling_channel"], "new_value": rev_b["cooling_channel"],
                    "numeric_delta": round(rev_b["overall_height"] - rev_a["overall_height"], 4),
                    "bbox_b": [SX - 60, SY - 10, 2 * 130 + 80, hh + 40],
                    "component_id": "cmp_motor_mount", "expected_severity": "medium",
                    "expected_classification": "consequential", "moved_only": False})
    return out


def _diff_truth(items_a: dict, items_b: dict) -> list[dict]:
    truth = []
    for sem in sorted(set(items_a) | set(items_b)):
        ia, ib = items_a.get(sem), items_b.get(sem)
        if ia and ib:
            moved = abs(ia["bbox"][0] - ib["bbox"][0]) > 4 or abs(ia["bbox"][1] - ib["bbox"][1]) > 4
            changed = ia.get("value") != ib.get("value") or ia.get("label") != ib.get("label") \
                or ia.get("tolerance") != ib.get("tolerance")
            if not changed and not moved:
                continue
            ctype = "ANNOTATION_CHANGE" if (moved and not changed) else \
                ("TOLERANCE_CHANGE" if (not changed and ia.get("tolerance") != ib.get("tolerance"))
                 else _TYPE_BY_KIND.get(ib["kind"], "ANNOTATION_CHANGE"))
            if ib["kind"] == "annotation" and sem == "material_note" and changed:
                ctype = "MATERIAL_CHANGE"
            delta = None
            if isinstance(ia.get("value"), (int, float)) and isinstance(ib.get("value"), (int, float)):
                delta = round(ib["value"] - ia["value"], 4)
            sev, cls = severity_for_change(ctype, sem, delta_mm=delta, fails=[], flags=[])
            truth.append({
                "semantic": sem, "change_type": ctype, "old_value": str(ia.get("value")),
                "new_value": str(ib.get("value")), "numeric_delta": delta,
                "bbox_b": ib["bbox"], "component_id": "cmp_motor_mount",
                "expected_severity": sev, "expected_classification": cls,
                "moved_only": bool(moved and not changed),
            })
        elif ib:
            sev, cls = severity_for_change("FEATURE_ADDED", sem, delta_mm=None, fails=[], flags=[])
            truth.append({"semantic": sem, "change_type": "FEATURE_ADDED", "old_value": None,
                          "new_value": str(ib.get("value")), "numeric_delta": None, "bbox_b": ib["bbox"],
                          "component_id": "cmp_motor_mount", "expected_severity": sev,
                          "expected_classification": cls, "moved_only": False})
        elif ia:
            sev, cls = severity_for_change("FEATURE_REMOVED", sem, delta_mm=None, fails=[], flags=[])
            truth.append({"semantic": sem, "change_type": "FEATURE_REMOVED", "old_value": str(ia.get("value")),
                          "new_value": None, "numeric_delta": None, "bbox_b": ia["bbox"],
                          "component_id": "cmp_motor_mount", "expected_severity": sev,
                          "expected_classification": cls, "moved_only": False})
    return truth


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for n, (label, overrides, extra_a, extra_b, difficulty, note) in enumerate(CASES, start=1):
        case_dir = OUT / f"case_{n:03d}"
        case_dir.mkdir(parents=True, exist_ok=True)
        rev_a = copy.deepcopy(BASE)
        rev_a.update(copy.deepcopy(extra_a))
        rev_b = copy.deepcopy(rev_a)
        rev_b.update(copy.deepcopy(overrides))
        rev_b.update(copy.deepcopy(extra_b))
        rev_a.update({"label": "A", "name": "Rev A"})
        rev_b.update({"label": "B", "name": "Rev B"})

        a = gd.render_part_drawing(rev_a, case_dir)
        b = gd.render_part_drawing(rev_b, case_dir)
        (case_dir / a["file"]).rename(case_dir / "rev_a.png")
        (case_dir / b["file"]).rename(case_dir / "rev_b.png")

        items_a = {i["semantic"]: i for i in a["items"] if i.get("drawing", "part") == "part"}
        items_b = {i["semantic"]: i for i in b["items"] if i.get("drawing", "part") == "part"}
        truth = _diff_truth(items_a, items_b) + _geometry_truth(rev_a, rev_b)

        (case_dir / "ground_truth.json").write_text(json.dumps({
            "case_id": f"case_{n:03d}", "label": label, "difficulty": difficulty, "note": note,
            "changes": truth, "n_changes": len(truth),
            "expected_engineering_changes": len([t for t in truth if t["change_type"] != "METADATA_CHANGE"]),
        }, indent=2))
        index.append({
            "case_id": f"case_{n:03d}", "label": label, "difficulty": difficulty, "note": note,
            "path_a": str((case_dir / "rev_a.png").relative_to(REPO_ROOT)),
            "path_b": str((case_dir / "rev_b.png").relative_to(REPO_ROOT)),
            "ground_truth": str((case_dir / "ground_truth.json").relative_to(REPO_ROOT)),
            "n_changes": len(truth),
        })
        # directory contract: exactly three files
        assert sorted(p.name for p in case_dir.iterdir()) == ["ground_truth.json", "rev_a.png", "rev_b.png"]
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    hard = sum(1 for i in index if i["difficulty"] == "hard")
    traps = sum(1 for i in index if i["difficulty"] == "trap")
    print(f"  blind benchmark: {len(index)} cases ({hard} hard, {traps} traps) → "
          f"{OUT.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
