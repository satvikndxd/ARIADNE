"""The blind benchmark must stay blind: analyzer never sees ground truth."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.core.config import settings
from app.services.analysis import blind

BLIND_DIR = settings.data_dir / "evaluation" / "blind"


def test_blind_module_source_has_no_ground_truth_or_manifest_access():
    src = Path(blind.__file__).read_text()
    assert "ground_truth" not in src
    assert "manifest" not in src.lower()
    assert "DocumentChunk" not in src and "Session" not in src


def test_analyze_pair_signature_only_images_and_vision():
    params = list(inspect.signature(blind.analyze_pair).parameters)
    assert params[:2] == ["path_a", "path_b"]
    assert set(params) <= {"path_a", "path_b", "vision", "force_vlm"}


def test_case_directory_contract():
    index = json.loads((BLIND_DIR / "index.json").read_text())
    assert len(index) >= 20
    for case in index:
        files = sorted(p.name for p in (BLIND_DIR / case["case_id"]).iterdir())
        assert files == ["ground_truth.json", "rev_a.png", "rev_b.png"], files


def test_analyzer_runs_without_ground_truth():
    index = json.loads((BLIND_DIR / "index.json").read_text())
    case = next(c for c in index if c["label"] == "dim_large")
    result = blind.analyze_pair(BLIND_DIR / case["case_id"] / "rev_a.png",
                                BLIND_DIR / case["case_id"] / "rev_b.png")
    assert result.n_regions >= 1
    assert result.method == "cv-only"           # no VLM endpoint in tests
    assert all(d.change_type is None for d in result.detections)   # CV alone invents no types
    # ground truth is only readable here, in the evaluator role:
    gt = json.loads((BLIND_DIR / case["case_id"] / "ground_truth.json").read_text())
    assert gt["n_changes"] >= 2
