#!/usr/bin/env python3
"""Generate the ARIADNE evaluation datasets.

  data/evaluation/pairs/pair_NNN/   rendered revision pairs + ground truth
  data/evaluation/pairs.json        index of 32 pairs with known changed regions
  data/evaluation/retrieval_qrels.json
  data/evaluation/tool_cases.json

Ground truth is produced *by construction*: we perturb known parameters, render
both revisions and record exactly what changed (semantic, type, values, bbox,
affected component, expected impact class).  No metric in this project is ever
taken from this file — metrics are computed by running the real pipeline and
comparing against it.
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

OUT = REPO_ROOT / "data" / "evaluation"

_spec = importlib.util.spec_from_file_location("gen_drawings", REPO_ROOT / "scripts" / "generate_drawings.py")
gd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gd)

from app.services.analysis.rules import severity_for_change  # noqa: E402
from app.schemas.common import ChangeType  # noqa: E402

BASE = gd.REV_A

PERTURBATIONS: list[tuple[str, dict, str, str]] = [
    # (label, param overrides, semantic, change_type)
    ("flange_plus_1", {"flange_dia": 49.0}, "flange_diameter", "DIMENSION_CHANGE"),
    ("flange_plus_4", {"flange_dia": 52.0}, "flange_diameter", "DIMENSION_CHANGE"),
    ("flange_minus_2", {"flange_dia": 46.0}, "flange_diameter", "DIMENSION_CHANGE"),
    ("flange_tol_tight", {"flange_tol": 0.05}, "flange_diameter", "TOLERANCE_CHANGE"),
    ("holes_plus_2", {"bolt_hole_dia": 10.5}, "bolt_hole_diameter", "DIMENSION_CHANGE"),
    ("holes_minus_1", {"bolt_hole_dia": 7.5}, "bolt_hole_diameter", "DIMENSION_CHANGE"),
    ("pattern_plus_4", {"pattern_pitch": 68.0}, "hole_pattern", "DIMENSION_CHANGE"),
    ("plate_plus_6", {"plate_size": 96.0}, "plate_size", "GEOMETRIC_CHANGE"),
    ("height_plus_1", {"overall_height": 23.0}, "overall_height", "DIMENSION_CHANGE"),
    ("threaded_hole_add", {"threaded_hole": {"size": "M6", "depth": 12.0}}, "threaded_hole", "FEATURE_ADDED"),
    ("material_swap", {"material": "AL-6061-T6"}, "material_note", "MATERIAL_CHANGE"),
    ("finish_swap", {"finish": "HARD ANODIZE 25µm PER ORN-MF-300 §6.3"}, "finish_note", "ANNOTATION_CHANGE"),
    ("fastener_up", {"fastener_size": "M12", "bolt_hole_dia": 12.5}, "fastener_callout", "ANNOTATION_CHANGE"),
    ("channel_serp", {"cooling_channel": "serpentine"}, "cooling_channel", "GEOMETRIC_CHANGE"),
    ("mass_up", {"mass_g": 448.0}, "mass_note", "METADATA_CHANGE"),
    ("bore_plus_1", {"bore_dia": 18.0}, "bore_diameter", "DIMENSION_CHANGE"),
]


def _truth_entry(semantic: str, ctype: str, a_items: dict, b_items: dict) -> dict:
    ia, ib = a_items.get(semantic), b_items.get(semantic)
    old = str(ia.get("value")) if ia else None
    new = str(ib.get("value")) if ib else None
    delta = None
    if isinstance((ia or {}).get("value"), (int, float)) and isinstance((ib or {}).get("value"), (int, float)):
        delta = round(ib["value"] - ia["value"], 4)
    sev, cls = severity_for_change(ctype, semantic, delta_mm=delta, fails=[], flags=[])
    bbox = (ib or ia or {}).get("bbox", [0, 0, 0, 0])
    return {
        "semantic": semantic, "change_type": ctype, "old_value": old, "new_value": new,
        "numeric_delta": delta, "component_id": "cmp_motor_mount",
        "bbox_b": bbox, "expected_severity": sev, "expected_classification": cls,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pairs_dir = OUT / "pairs"
    index = []
    n = 0
    combos = PERTURBATIONS + [
        ("combo_flange_holes", {"flange_dia": 52.0, "bolt_hole_dia": 10.5}, "flange_diameter", "DIMENSION_CHANGE"),
        ("combo_material_channel", {"material": "AL-6061-T6", "cooling_channel": "serpentine"},
         "material_note", "MATERIAL_CHANGE"),
        ("combo_full_revB", {"flange_dia": 52.0, "flange_tol": 0.05, "bolt_hole_dia": 10.5,
                             "threaded_hole": {"size": "M6", "depth": 12.0}, "mass_g": 438.0},
         "flange_diameter", "DIMENSION_CHANGE"),
        ("combo_fastener_plate", {"fastener_size": "M12", "bolt_hole_dia": 12.5, "plate_size": 96.0},
         "fastener_callout", "ANNOTATION_CHANGE"),
        ("flange_plus_0_5", {"flange_dia": 48.5}, "flange_diameter", "DIMENSION_CHANGE"),
        ("flange_tol_loose", {"flange_tol": 0.15}, "flange_diameter", "TOLERANCE_CHANGE"),
        ("holes_plus_4", {"bolt_hole_dia": 12.5}, "bolt_hole_diameter", "DIMENSION_CHANGE"),
        ("pattern_minus_4", {"pattern_pitch": 60.0}, "hole_pattern", "DIMENSION_CHANGE"),
        ("plate_minus_4", {"plate_size": 86.0}, "plate_size", "GEOMETRIC_CHANGE"),
        ("height_minus_1", {"overall_height": 21.0}, "overall_height", "DIMENSION_CHANGE"),
        ("bore_minus_2", {"bore_dia": 15.0}, "bore_diameter", "DIMENSION_CHANGE"),
        ("mass_down", {"mass_g": 398.0}, "mass_note", "METADATA_CHANGE"),
        ("threaded_hole_m8", {"threaded_hole": {"size": "M8", "depth": 16.0}}, "threaded_hole", "FEATURE_ADDED"),
        ("material_6082", {"material": "AL-6082-T6"}, "material_note", "MATERIAL_CHANGE"),
        ("channel_and_mass", {"cooling_channel": "serpentine", "mass_g": 445.0}, "cooling_channel", "GEOMETRIC_CHANGE"),
        ("triple_rev_c_like", {"material": "AL-6061-T6", "cooling_channel": "serpentine",
                               "fastener_size": "M12", "bolt_hole_dia": 12.5}, "material_note", "MATERIAL_CHANGE"),
    ]
    for label, overrides, primary_semantic, primary_type in combos:
        n += 1
        pair_id = f"pair_{n:03d}"
        pdir = pairs_dir / pair_id
        pdir.mkdir(parents=True, exist_ok=True)
        rev_a = copy.deepcopy(BASE)
        rev_b = copy.deepcopy(BASE)
        rev_b.update(copy.deepcopy(overrides))
        rev_a["label"], rev_b["label"] = "A", "B"
        rev_a["name"], rev_b["name"] = "Rev A", f"Rev B ({pair_id})"

        a = gd.render_part_drawing(rev_a, pdir)
        b = gd.render_part_drawing(rev_b, pdir)
        items_a = {it["semantic"]: it for it in a["items"]}
        items_b = {it["semantic"]: it for it in b["items"]}

        truths = []
        for semantic in sorted(set(items_a) | set(items_b)):
            ia, ib = items_a.get(semantic), items_b.get(semantic)
            if ia and ib:
                if ia.get("value") != ib.get("value") or ia.get("label") != ib.get("label"):
                    ctype = primary_type if semantic == primary_semantic else _type_for(semantic, ia, ib)
                    truths.append(_truth_entry(semantic, ctype, items_a, items_b))
                elif ia.get("tolerance") != ib.get("tolerance"):
                    truths.append(_truth_entry(semantic, "TOLERANCE_CHANGE", items_a, items_b))
            elif ib:
                truths.append(_truth_entry(semantic, "FEATURE_ADDED", items_a, items_b))
            elif ia:
                truths.append(_truth_entry(semantic, "FEATURE_REMOVED", items_a, items_b))

        (pdir / "manifest_a.json").write_text(json.dumps(
            {"items": a["items"], "parameters": {k: v for k, v in rev_a.items()}}, indent=2))
        (pdir / "manifest_b.json").write_text(json.dumps(
            {"items": b["items"], "parameters": {k: v for k, v in rev_b.items()}}, indent=2))
        (pdir / "ground_truth.json").write_text(json.dumps({
            "pair_id": pair_id, "label": label, "overrides": overrides,
            "file_a": a["file"], "file_b": b["file"], "changes": truths,
        }, indent=2))
        index.append({
            "pair_id": pair_id, "label": label,
            "path_a": str((pdir / a["file"]).relative_to(REPO_ROOT)),
            "path_b": str((pdir / b["file"]).relative_to(REPO_ROOT)),
            "ground_truth": str((pdir / "ground_truth.json").relative_to(REPO_ROOT)),
            "n_changes": len(truths),
            "expected_impact": truths[0]["expected_severity"] if truths else "low",
        })
    (OUT / "pairs.json").write_text(json.dumps(index, indent=2))

    qrels = [
        {"query": "radial clearance requirement for M10 structural fasteners to adjacent structure",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-FS-017 §4.2", "ORN-FS-017 §4.3"]},
        {"query": "flange boss diameter limits and tolerance class",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-MM-042 §3.1", "ORN-MM-042 §3.2"]},
        {"query": "hole pattern and clearance hole diameter for structural fasteners",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-MM-042 §3.4", "Orion EV Fastener Guidelines§3"]},
        {"query": "mass budget allocation for the motor mount",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-AG-200 §5.1", "ORN-AG-200 §5.2", "ORN-MM-042 §4.1"]},
        {"query": "approved plate materials and material substitution rules",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev C",
         "relevant": ["ORN-MF-300 §4.1", "ORN-TH-100 §2.3"]},
        {"query": "cooling channel geometry re-analysis requirement",
         "component_ids": ["cmp_cooling_bracket"], "revision": "Rev C",
         "relevant": ["ORN-TH-100 §2.2", "ORN-TH-100 §2.1"]},
        {"query": "what changed in revision B of the motor mount",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["Revision Notes — Motor Mount B§1"]},
        {"query": "fixture re-qualification threshold for dimensional changes",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-MF-300 §7.1"]},
        {"query": "impact review scope when a mating interface dimension changes",
         "component_ids": ["cmp_chassis_interface"], "revision": "Rev B",
         "relevant": ["ORN-DS-001 §2.2", "ORN-DS-001 §2.3"]},
        {"query": "tool access requirement on the driving side of bolted joints",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev B",
         "relevant": ["ORN-FS-017 §4.1"]},
        {"query": "thermal capability of the mount flange face",
         "component_ids": ["cmp_motor_mount"], "revision": "Rev C",
         "relevant": ["ORN-MM-042 §4.2", "Thermal Management Requirements§1"]},
        {"query": "torque values for M12 class 10.9 fasteners",
         "component_ids": ["cmp_fastener_m10"], "revision": "Rev C",
         "relevant": ["Orion EV Fastener Guidelines§5"]},
    ]
    (OUT / "retrieval_qrels.json").write_text(json.dumps(qrels, indent=2))

    tool_cases = [
        {"message": "What changed in Rev B?", "expected": ["compare_revisions"]},
        {"message": "Compare Rev A and Rev B and list the differences", "expected": ["compare_revisions"]},
        {"message": "Which components are potentially affected by the flange change?", "expected": ["get_dependencies"]},
        {"message": "Show me the dependency graph of the motor mount", "expected": ["get_dependencies"]},
        {"message": "Why is Motor Mount classified as high impact?", "expected": ["get_component_properties", "search_requirements"]},
        {"message": "Show me the evidence for the clearance issue", "expected": ["search_requirements"]},
        {"message": "Which requirements apply to this component?", "expected": ["search_requirements"]},
        {"message": "What does the fastener standard say about radial clearance?", "expected": ["search_requirements"]},
        {"message": "What is the revision history of the motor mount?", "expected": ["get_revision_history"]},
        {"message": "Create a review finding for the possible clearance conflict", "expected": ["search_requirements"]},
        {"message": "List open findings for this project", "expected": ["get_findings"]},
        {"message": "Accept finding fd_seed_002", "expected": ["get_findings"]},
        {"message": "Give me an overview of the Orion EV project", "expected": ["get_project"]},
        {"message": "How do the upstream and downstream dependencies propagate?", "expected": ["get_dependencies"]},
    ]
    (OUT / "tool_cases.json").write_text(json.dumps(tool_cases, indent=2))
    print(f"  benchmark: {len(index)} revision pairs, {len(qrels)} retrieval qrels, {len(tool_cases)} tool cases")
    print(f"  → {OUT.relative_to(REPO_ROOT)}/")


def _type_for(semantic: str, ia: dict, ib: dict) -> str:
    kind = ib.get("kind", ia.get("kind", ""))
    mapping = {"dimension": "DIMENSION_CHANGE", "geometry": "GEOMETRIC_CHANGE",
               "annotation": "MATERIAL_CHANGE" if semantic == "material_note" else "ANNOTATION_CHANGE",
               "metadata": "METADATA_CHANGE", "feature": "FEATURE_ADDED", "component": "COMPONENT_ADDED"}
    return mapping.get(kind, "ANNOTATION_CHANGE")


if __name__ == "__main__":
    main()
