"""Evaluation endpoints — measurements only, never manufactured numbers."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, current_principal
from app.db.base import get_session
from app.db.models import EvaluationMetric, EvaluationRun

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/runs")
def list_runs(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    rows = session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc())).all()
    return {"runs": [
        {"id": r.id, "name": r.name, "mode": r.mode, "created_at": r.created_at, "report_path": r.report_path,
         "metrics": [{"subset": m.subset, "metric": m.metric, "value": m.value, "n": m.n} for m in r.metrics]}
        for r in rows]}


@router.get("/evaluation/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session),
            principal: Principal = Depends(current_principal)):
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise NotFoundError(f"Evaluation run '{run_id}' not found.")
    return {
        "id": run.id, "name": run.name, "mode": run.mode, "created_at": run.created_at,
        "config": run.config_json, "report_path": run.report_path,
        "metrics": [{"subset": m.subset, "metric": m.metric, "value": m.value, "n": m.n, "detail": m.detail_json}
                    for m in run.metrics],
    }


SUITE_RUNNERS = {
    "full": "run_evaluation",
    "blind": "run_blind_evaluation",
    "rag": "run_rag_experiment",
    "vlm": "run_vlm_evaluation",
}


@router.post("/evaluation/run", status_code=202)
def start_run(name: str = "manual", suite: str = "full",
              session: Session = Depends(get_session),
              principal: Principal = Depends(current_principal)):
    import app.services.evaluation_service as evs

    fn = getattr(evs, SUITE_RUNNERS.get(suite, "run_evaluation"))

    def _bg() -> None:
        fn(name=name)

    threading.Thread(target=_bg, name=f"eval-{suite}-{name}", daemon=True).start()
    return {"status": "queued", "name": name, "suite": suite}
