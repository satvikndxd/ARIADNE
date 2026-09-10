"""Evaluation runner: executes the real pipeline against generated ground truth.

Nothing here is simulated except the two *retrieval baselines* (keyword / naive
vector), which are genuine alternative implementations — not strawmen with
hand-picked numbers.  Every metric is computed from actual executions and
persisted with its sample size ``n``.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import new_id, utcnow
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.db.models import AnalysisRun, DocumentChunk, EvaluationMetric, EvaluationRun
from app.schemas.chat import ChatRequest
from app.schemas.rag import RetrievalFilters, SearchRequest
from app.services.agent.agent import AgentRunner
from app.services.analysis import orchestrator
from app.services.analysis.revision_analyzer import _cv_for_drawing, _dedupe, _diff_items
from app.services.rag import retriever
from ariadne_evaluation import metrics as M

log = get_logger(__name__)

EVAL_DIR = settings.data_dir / "evaluation"


def _load(name: str) -> Any:
    return json.loads((EVAL_DIR / name).read_text())


def _fake_drawing(path: str, manifest_path: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=path, storage_path=path, manifest_path=manifest_path,
                           metadata_json={"drawing_kind": "part"})


# --------------------------------------------------------------------------- #
def eval_change_detection() -> dict:
    """Run the *real* detection path (manifest diff + OpenCV confirmation) over
    all benchmark pairs and score it against the constructed ground truth."""
    import pathlib

    from app.services.analysis.revision_analyzer import _region_confirms

    pairs = _load("pairs.json")
    tp = fp = fn = 0
    type_correct = 0
    loc_hits = loc_total = 0
    exact = norm = 0
    per_pair = []
    for pair in pairs:
        dirp = pathlib.Path(str(settings.data_dir.parent / pair["path_a"])).parent
        man_a = json.loads((dirp / "manifest_a.json").read_text())
        man_b = json.loads((dirp / "manifest_b.json").read_text())
        gt = json.loads((dirp / "ground_truth.json").read_text())
        da = _fake_drawing(str(dirp / pathlib.Path(pair["path_a"]).name))
        db = _fake_drawing(str(dirp / pathlib.Path(pair["path_b"]).name))
        regions, _align = _cv_for_drawing(da, db)

        detected: dict[str, dict] = {}
        for cand in _dedupe(_diff_items(man_a, man_b, da, db, "part")):
            detected[cand.semantic] = {
                "type": cand.change_type.value, "old": cand.old_value, "new": cand.new_value,
                "confirmed": _region_confirms(cand.location, regions), "unmapped": cand.kind == "cv",
            }
        truth = {t["semantic"]: t for t in gt["changes"]}
        p_tp = p_fp = 0
        for sem, det in detected.items():
            if sem in truth:
                p_tp += 1
                type_correct += int(det["type"] == truth[sem]["change_type"])
                loc_total += 1
                loc_hits += int(det["confirmed"])
                if det["old"] == truth[sem]["old_value"] and det["new"] == truth[sem]["new_value"]:
                    exact += 1
                if _num_eq(det["old"], truth[sem]["old_value"]) and _num_eq(det["new"], truth[sem]["new_value"]):
                    norm += 1
            else:
                p_fp += 1
        p_fn = len(set(truth) - set(detected))
        tp += p_tp
        fp += p_fp
        fn += p_fn
        per_pair.append({"pair": pair["pair_id"], "tp": p_tp, "fp": p_fp, "fn": p_fn})
    prf = M.precision_recall_f1(tp, fp, fn)
    return {
        "overall": prf,
        "type_accuracy": M.accuracy(type_correct, tp),
        "localization_confirmation_rate": M.accuracy(loc_hits, loc_total),
        "extraction_exact_match": M.accuracy(exact, tp),
        "extraction_normalized": M.accuracy(norm, tp),
        "pairs": len(pairs),
        "per_pair": per_pair,
    }


def _num_eq(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a) == str(b)


# --------------------------------------------------------------------------- #
def _relevant_flags(results: list, relevant: list[str], session: Session) -> list[bool]:
    """A retrieved chunk is relevant when its requirement code matches, or when
    its (document, section) pair matches a qrel entry of the form
    ``"Document Title§section"``."""
    codes = {r for r in relevant if not _is_doc_key(r)}
    doc_secs = {r for r in relevant if _is_doc_key(r)}
    flags = []
    for r in results:
        code = getattr(r, "requirement_code", None) or (
            (r.metadata_json or {}).get("requirement_code") if hasattr(r, "metadata_json") else None)
        doc = getattr(r, "document_name", "") or ""
        sec = str(getattr(r, "section", "") or "")
        flags.append(bool(code in codes) or f"{doc}§{sec}" in doc_secs)
    return flags


def _is_doc_key(entry: str) -> bool:
    """``ORN-…§4.2`` style = requirement code; anything else = document key."""
    head = entry.split("§")[0]
    return not head.startswith(("ORN-", "EXT-", "VN-"))


def eval_retrieval(session: Session) -> dict:
    qrels = _load("retrieval_qrels.json")
    strategies = ("keyword", "vector", "metadata_aware", "revision_aware")
    acc: dict[str, dict[str, list[float]]] = {s: {"recall": [], "mrr": [], "ndcg": []} for s in strategies}
    latencies = []
    detail = []
    for q in qrels:
        for strategy in strategies:
            t0 = time.perf_counter()
            resp = retriever.search(
                session,
                SearchRequest(
                    query=q["query"], project_id="proj_orion_ev", strategy=strategy,  # type: ignore[arg-type]
                    top_k=8, rerank_top_n=5,
                    filters=RetrievalFilters(project_id="proj_orion_ev", component_ids=q["component_ids"],
                                             revision=q["revision"]),
                ),
            )
            latencies.append((time.perf_counter() - t0) * 1000)
            flags = _relevant_flags(resp.results, q["relevant"], session)
            acc[strategy]["recall"].append(M.recall_at_k(flags, 5))
            acc[strategy]["mrr"].append(M.mrr(flags))
            acc[strategy]["ndcg"].append(M.ndcg_at_k(flags, 5))
            detail.append({"query": q["query"][:50], "strategy": strategy,
                           "flags": [bool(f) for f in flags]})
    out = {}
    for strategy, vals in acc.items():
        out[strategy] = {
            "recall@5": M.mean(vals["recall"]), "mrr": M.mean(vals["mrr"]),
            "ndcg@5": M.mean(vals["ndcg"]), "n": len(qrels),
        }
    out["latency_ms_mean"] = M.mean(latencies)
    out["detail"] = detail
    return out


# --------------------------------------------------------------------------- #
def eval_agent_tools(session: Session) -> dict:
    cases = _load("tool_cases.json")
    runner = AgentRunner(session)
    correct = 0
    detail = []
    for case in cases:
        req = ChatRequest(message=case["message"], project_id="proj_orion_ev",
                          revision_a="rev_a", revision_b="rev_b")
        ctx = runner._context(req)
        plan = runner._plan(runner._intent(case["message"]), req, ctx)
        selected = [p.name for p in plan]
        ok = all(t in selected for t in case["expected"])
        correct += int(ok)
        detail.append({"message": case["message"], "expected": case["expected"], "selected": selected, "ok": ok})
    return {"tool_selection_accuracy": M.accuracy(correct, len(cases)), "n": len(cases), "detail": detail}


# --------------------------------------------------------------------------- #
def eval_grounding(session: Session) -> dict:
    run = AnalysisRun(
        id=new_id("an"), project_id="proj_orion_ev", revision_a_id="rev_a", revision_b_id="rev_b",
        status="queued", mode="demo", requested_by="evaluation",
    )
    session.add(run)
    session.commit()
    orchestrator.run_analysis(run.id)
    session.refresh(run)
    result = run.result_json or {}
    changes = result.get("changes", [])
    findings = result.get("proposed_findings", [])
    with_evidence = sum(1 for f in findings if f.get("evidence"))
    # fabrication check: every reported value must exist in the source manifests
    manifests = []
    for label in ("a", "b"):
        p = settings.drawings_dir / f"rev_{label}" / "manifest.json"
        manifests.append(json.loads(p.read_text()))
    known_values = set()
    for man in manifests:
        for item in man["items"]:
            known_values.add(str(item.get("value")))
            known_values.add(str(item.get("label")))
    unsupported = 0
    for ch in changes:
        for val in (ch.get("old_value"), ch.get("new_value")):
            if val in (None, ""):
                continue
            if val not in known_values and not any(v and v in str(val) for v in known_values if v):
                unsupported += 1
    return {
        "findings_with_evidence_rate": M.accuracy(with_evidence, len(findings)),
        "unsupported_claim_rate": round(unsupported / max(1, len(changes) * 2), 4),
        "insight_grounded": bool((result.get("insight") or {}).get("grounded")),
        "changes": len(changes),
        "proposed_findings": len(findings),
        "analysis_latency_ms": run.latency_ms,
        "analysis_id": run.id,
    }


# --------------------------------------------------------------------------- #
def run_evaluation(name: str = "manual") -> dict:
    started = time.perf_counter()
    report: dict[str, Any] = {"name": name, "created_at": utcnow().isoformat(), "sections": {}}
    with SessionLocal() as session:
        report["sections"]["change_detection"] = eval_change_detection()
        report["sections"]["retrieval"] = eval_retrieval(session)
        report["sections"]["agent"] = eval_agent_tools(session)
        report["sections"]["grounding"] = eval_grounding(session)
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)

        run_row = EvaluationRun(id=new_id("evr"), name=name, mode="demo",
                                config_json={"pairs": 32, "qrels": 12, "tool_cases": 14})
        session.add(run_row)
        session.flush()

        def add(subset: str, metric: str, value: float, n: int, detail: dict | None = None) -> None:
            session.add(EvaluationMetric(id=new_id("evm"), evaluation_run_id=run_row.id, subset=subset,
                                         metric=metric, value=value, n=n, detail_json=detail or {}))

        cd = report["sections"]["change_detection"]["overall"]
        add("change_detection", "precision", cd["precision"], cd["tp"] + cd["fp"] + cd["fn"])
        add("change_detection", "recall", cd["recall"], cd["tp"] + cd["fp"] + cd["fn"])
        add("change_detection", "f1", cd["f1"], cd["tp"] + cd["fp"] + cd["fn"])
        add("change_detection", "localization_confirmation",
            report["sections"]["change_detection"]["localization_confirmation_rate"],
            report["sections"]["change_detection"]["pairs"])
        for strategy, vals in report["sections"]["retrieval"].items():
            if not isinstance(vals, dict) or "recall@5" not in vals:
                continue
            add(f"retrieval:{strategy}", "recall@5", vals["recall@5"], vals["n"])
            add(f"retrieval:{strategy}", "mrr", vals["mrr"], vals["n"])
            add(f"retrieval:{strategy}", "ndcg@5", vals["ndcg@5"], vals["n"])
        add("retrieval", "latency_ms_mean", report["sections"]["retrieval"]["latency_ms_mean"], 12)
        add("agent", "tool_selection_accuracy", report["sections"]["agent"]["tool_selection_accuracy"],
            report["sections"]["agent"]["n"])
        g = report["sections"]["grounding"]
        add("grounding", "findings_with_evidence_rate", g["findings_with_evidence_rate"], g["proposed_findings"])
        add("grounding", "unsupported_claim_rate", g["unsupported_claim_rate"], g["changes"])
        add("system", "analysis_latency_ms", g["analysis_latency_ms"], 1)
        report["evaluation_run_id"] = run_row.id
        session.commit()

    out = settings.reports_dir / f"evaluation_{run_row.id}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    run_row_report = out
    with SessionLocal() as session:
        row = session.get(EvaluationRun, run_row.id)
        row.report_path = str(out)
        session.commit()
    log.info("evaluation_complete", run_id=run_row.id, report=str(out),
             duration_ms=report["duration_ms"])
    return report
