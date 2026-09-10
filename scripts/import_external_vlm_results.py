#!/usr/bin/env python3
"""Import externally measured VLM results (e.g. from the Colab notebook)
into ARIADNE's evaluation infrastructure.

    python scripts/import_external_vlm_results.py \
        [path/to/vlm_external_colab.json]

Creates a NEW EvaluationRun (name ``vlm:colab-external:<model>``) with the
metrics recorded by the notebook. It never modifies or overwrites existing
production evaluation runs; re-importing the same file creates another run row
(check ``evaluation_runs`` before comparing).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "evaluation"))

from app.core.ids import new_id  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import EvaluationMetric, EvaluationRun  # noqa: E402

DEFAULT = REPO_ROOT / "data" / "evaluation" / "results" / "vlm_external_colab.json"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"error: {path} not found — run the notebook first "
              "(notebooks/ariadne_vlm_evaluation.ipynb).")
        return 1
    payload = json.loads(path.read_text())
    if payload.get("suite") != "vlm" or payload.get("source") != "colab-external":
        print("error: file is not a colab-external VLM result bundle.")
        return 1
    if payload.get("dry_run"):
        print("error: this bundle was produced in DRY-RUN mode (no VLM inference); "
              "refusing to import unmeasured values.")
        return 1

    with SessionLocal() as session:
        run = EvaluationRun(
            id=new_id("evr"),
            name=f"vlm:colab-external:{payload.get('model', 'unknown')}",
            mode="external",
            config_json={"source": str(path), "quantization": payload.get("quantization"),
                         "benchmark_cases": payload.get("benchmark_cases"),
                         "notebook": payload.get("notebook"),
                         "created_by_notebook_at": payload.get("created_at")},
        )
        session.add(run)
        session.flush()
        for m in payload.get("metrics", []):
            session.add(EvaluationMetric(
                id=new_id("evm"), evaluation_run_id=run.id, subset=m.get("subset", "vlm"),
                metric=m.get("metric", "value"), value=float(m.get("value", 0.0)),
                n=int(m.get("n", 0)), detail_json=m.get("detail", {})))
        session.commit()
        run_id = run.id
    print(f"imported {len(payload.get('metrics', []))} metrics as evaluation run {run_id}")
    print("view: GET /evaluation/runs  or  make eval  (production suites are unaffected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
