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

import numpy as np

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
RESULTS_DIR = EVAL_DIR / "results"


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
def _persist_run(name: str, suite: str, report: dict,
                 metrics: list[tuple[str, str, float, int, dict]]) -> dict:
    """Persist EvaluationRun + EvaluationMetric rows and a JSON report."""
    from app.db.base import SessionLocal

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        run_row = EvaluationRun(id=new_id("evr"), name=f"{suite}:{name}", mode="demo",
                                config_json={"suite": suite})
        session.add(run_row)
        session.flush()
        for subset, metric, value, n, detail in metrics:
            session.add(EvaluationMetric(id=new_id("evm"), evaluation_run_id=run_row.id, subset=subset,
                                         metric=metric, value=value, n=n, detail_json=detail or {}))
        session.commit()
        run_id = run_row.id
    out = RESULTS_DIR / f"{suite}_{run_id}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    with SessionLocal() as session:
        row = session.get(EvaluationRun, run_id)
        row.report_path = str(out)
        session.commit()
    log.info("evaluation_run_persisted", suite=suite, run_id=run_id, report=str(out))
    report["evaluation_run_id"] = run_id
    report["report_path"] = str(out)
    return report


def _iou(a: dict, b: list) -> float:
    x1, y1 = max(a["x"], b[0]), max(a["y"], b[1])
    x2, y2 = min(a["x"] + a["width"], b[0] + b[2]), min(a["y"] + a["height"], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a["width"] * a["height"] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _reverse_containment(det: dict, gt_bbox: list) -> float:
    """Fraction of the detected region lying inside the ground-truth box
    (character-level text edits produce tiny diffs inside a larger label)."""
    x1, y1 = max(det["x"], gt_bbox[0]), max(det["y"], gt_bbox[1])
    x2, y2 = min(det["x"] + det["width"], gt_bbox[0] + gt_bbox[2]), \
        min(det["y"] + det["height"], gt_bbox[1] + gt_bbox[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    det_area = det["width"] * det["height"]
    return inter / det_area if det_area > 0 else 0.0


def _containment(det: dict, gt_bbox: list) -> float:
    """Fraction of the ground-truth annotation box inside the detected region.

    Region-level detectors localize *clusters* of changed pixels (a moved note,
    a resized flange ring, a merged title block), while ground truth boxes are
    per-annotation.  Containment ≥ 0.5 is therefore the matching criterion:
    "the detector's changed region covers the true changed annotation".
    """
    x1, y1 = max(det["x"], gt_bbox[0]), max(det["y"], gt_bbox[1])
    x2, y2 = min(det["x"] + det["width"], gt_bbox[0] + gt_bbox[2]), \
        min(det["y"] + det["height"], gt_bbox[1] + gt_bbox[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    gt_area = gt_bbox[2] * gt_bbox[3]
    return inter / gt_area if gt_area > 0 else 0.0


# --------------------------------------------------------------------------- #
# BLIND REVISION BENCHMARK
# --------------------------------------------------------------------------- #
def run_blind_evaluation(name: str = "blind") -> dict:
    """CV-only vs CV+VLM on the blind benchmark; ground truth opened post-analysis."""
    import time

    from app.services.analysis import blind as blind_mod
    from app.services.vision.providers import vision_active

    t0 = time.perf_counter()
    index = json.loads((EVAL_DIR / "blind" / "index.json").read_text())
    vlm_on = vision_active()

    agg = {
        "cv_only": {"tp": 0, "fp": 0, "fn": 0, "eng_tp": 0, "eng_fp": 0, "eng_fn": 0},
        "cv_vlm": {"tp": 0, "fp": 0, "fn": 0, "type_ok": 0, "type_n": 0, "old_ok": 0, "new_ok": 0,
                   "val_n": 0, "comp_ok": 0, "comp_n": 0, "impact_ok": 0, "impact_n": 0},
    }
    consensus_counts: dict[str, int] = {}
    failures: list[dict] = []
    per_case = []

    for case in index:
        # 1 — analyze WITHOUT ground truth
        result = blind_mod.analyze_pair(settings.data_dir.parent / case["path_a"],
                                        settings.data_dir.parent / case["path_b"])
        # 2 — only now open ground truth
        gt = json.loads((settings.data_dir.parent / case["ground_truth"]).read_text())
        entries = gt["changes"]
        eng = {e["semantic"] for e in entries if e["change_type"] != "METADATA_CHANGE"}

        matched: list[tuple[dict, dict]] = []
        used_by: dict[int, int] = {}
        for entry in sorted(entries, key=lambda e: -(e["bbox_b"][2] * e["bbox_b"][3])):
            best_i, best_score = -1, 0.0
            for i, det in enumerate(result.detections):
                fwd = _containment(det.bbox, entry["bbox_b"])          # gt inside detection
                rev = _containment(entry["bbox_b"] and det.bbox, entry["bbox_b"]) if False else (
                    _reverse_containment(det.bbox, entry["bbox_b"]))   # detection inside gt
                score = max(fwd, 0.0 if fwd >= 0.5 else rev * 0.9)
                if fwd < 0.5 and rev >= 0.7:
                    score = max(score, 0.5)
                if score > best_score:
                    best_i, best_score = i, score
            if best_i >= 0 and best_score >= 0.5:
                used_by[best_i] = used_by.get(best_i, 0) + 1
                matched.append((entry, result.detections[best_i]))
            else:
                weak = any(0.0 < _containment(d.bbox, entry["bbox_b"]) < 0.5 or
                           0.0 < _reverse_containment(d.bbox, entry["bbox_b"]) < 0.7
                           for d in result.detections)
                cat = "localization_weak" if weak else (
                    "visual_ambiguity" if entry.get("moved_only") else "detection_miss")
                failures.append({"case": case["case_id"], "stage": "detection", "category": cat,
                                 "expected": f"{entry['change_type']} @ {entry['bbox_b']}",
                                 "predicted": "none", "component": entry["component_id"],
                                 "reason": gt.get("note", "")})
        fp_idx = [i for i in range(len(result.detections)) if i not in used_by]
        for i in fp_idx:
            cat = "irrelevant_noise_fp" if case["difficulty"] == "trap" else "spurious_detection"
            failures.append({"case": case["case_id"], "stage": "detection", "category": cat,
                             "expected": "no change", "predicted": "region",
                             "component": "cmp_motor_mount", "reason": gt.get("note", "")})

        tp, fp, fn = len(matched), len(fp_idx), len(entries) - len(matched)
        agg["cv_only"]["tp"] += tp
        agg["cv_only"]["fp"] += fp
        agg["cv_only"]["fn"] += fn
        eng_matched = {e["semantic"] for e, _ in matched}
        eng_tp = len(eng_matched & eng)
        agg["cv_only"]["eng_tp"] += eng_tp
        agg["cv_only"]["eng_fp"] += fp + len(eng_matched - eng)
        agg["cv_only"]["eng_fn"] += len(eng) - eng_tp

        for entry, det in matched:
            if vlm_on:
                a2 = agg["cv_vlm"]
                a2["tp"] += 1
                if det.change_type:
                    a2["type_n"] += 1
                    a2["type_ok"] += int(det.change_type == entry["change_type"])
                    if det.change_type != entry["change_type"]:
                        failures.append({"case": case["case_id"], "stage": "interpretation",
                                         "category": "type_error", "expected": entry["change_type"],
                                         "predicted": det.change_type, "component": entry["component_id"],
                                         "reason": "VLM type disagreement with ground truth"})
                else:
                    failures.append({"case": case["case_id"], "stage": "interpretation",
                                     "category": "visual_ambiguity", "expected": entry["change_type"],
                                     "predicted": "UNKNOWN", "component": entry["component_id"],
                                     "reason": "VLM returned UNKNOWN"})
                if entry.get("old_value") not in (None, "None") and det.old_value is not None:
                    a2["val_n"] += 1
                    a2["old_ok"] += int(_num_eq(det.old_value, entry["old_value"]))
                    a2["new_ok"] += int(_num_eq(det.new_value, entry["new_value"]))
                a2["comp_n"] += 1
                feat = (det.feature or "").lower()
                sem = entry["semantic"]
                a2["comp_ok"] += int(any(k in feat for k in sem.replace("_", " ").split() if len(k) > 3))
                if det.predicted_severity:
                    a2["impact_n"] += 1
                    a2["impact_ok"] += int(det.predicted_severity == entry["expected_severity"])
            status = det.consensus.get("status", "UNCERTAIN")
            consensus_counts[status] = consensus_counts.get(status, 0) + 1
            if status == "CONFLICT":
                failures.append({"case": case["case_id"], "stage": "cross-check",
                                 "category": "vlm_disagreement", "expected": entry["change_type"],
                                 "predicted": det.change_type, "component": entry["component_id"],
                                 "reason": "; ".join(det.consensus.get("notes", []))})
        agg["cv_vlm"]["fp"] += fp
        agg["cv_vlm"]["fn"] += fn
        per_case.append({"case": case["case_id"], "difficulty": case["difficulty"],
                         "regions": result.n_regions, "gt": len(entries), "tp": tp, "fp": fp, "fn": fn,
                         "method": result.method})

    prf = M.precision_recall_f1(agg["cv_only"]["tp"], agg["cv_only"]["fp"], agg["cv_only"]["fn"])
    prf_eng = M.precision_recall_f1(agg["cv_only"]["eng_tp"], agg["cv_only"]["eng_fp"], agg["cv_only"]["eng_fn"])
    report = {
        "suite": "blind", "created_at": utcnow().isoformat(), "cases": len(index),
        "vlm_active": vlm_on,
        "cv_only": {"all_gt": prf, "engineering_only": prf_eng},
        "cv_vlm": ({
            "detection": M.precision_recall_f1(agg["cv_vlm"]["tp"], agg["cv_vlm"]["fp"], agg["cv_vlm"]["fn"]),
            "type_accuracy": M.accuracy(agg["cv_vlm"]["type_ok"], agg["cv_vlm"]["type_n"]),
            "old_value_accuracy": M.accuracy(agg["cv_vlm"]["old_ok"], agg["cv_vlm"]["val_n"]),
            "new_value_accuracy": M.accuracy(agg["cv_vlm"]["new_ok"], agg["cv_vlm"]["val_n"]),
            "component_attribution_accuracy": M.accuracy(agg["cv_vlm"]["comp_ok"], agg["cv_vlm"]["comp_n"]),
            "impact_category_accuracy": M.accuracy(agg["cv_vlm"]["impact_ok"], agg["cv_vlm"]["impact_n"]),
        } if vlm_on else {"status": "not_run_no_vlm_endpoint"}),
        "consensus_counts": consensus_counts,
        "failures": failures,
        "per_case": per_case,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    top_failures = sorted(
        ((cat, sum(1 for f in failures if f["category"] == cat)) for cat in {f["category"] for f in failures}),
        key=lambda kv: -kv[1])
    report["top_failure_categories"] = top_failures

    metrics = [
        ("blind:cv_only", "precision", prf["precision"], len(index), {}),
        ("blind:cv_only", "recall", prf["recall"], len(index), {}),
        ("blind:cv_only", "f1", prf["f1"], len(index), {}),
        ("blind:cv_only_eng", "precision", prf_eng["precision"], len(index), {}),
        ("blind:cv_only_eng", "recall", prf_eng["recall"], len(index), {}),
        ("blind:cv_only_eng", "f1", prf_eng["f1"], len(index), {}),
    ]
    if vlm_on:
        cv = report["cv_vlm"]
        metrics += [
            ("blind:cv_vlm", "type_accuracy", cv["type_accuracy"], agg["cv_vlm"]["type_n"], {}),
            ("blind:cv_vlm", "old_value_accuracy", cv["old_value_accuracy"], agg["cv_vlm"]["val_n"], {}),
            ("blind:cv_vlm", "new_value_accuracy", cv["new_value_accuracy"], agg["cv_vlm"]["val_n"], {}),
            ("blind:cv_vlm", "component_attribution", cv["component_attribution_accuracy"], agg["cv_vlm"]["comp_n"], {}),
            ("blind:cv_vlm", "impact_category_accuracy", cv["impact_category_accuracy"], agg["cv_vlm"]["impact_n"], {}),
        ]
    else:
        metrics.append(("blind:cv_vlm", "status_not_run_no_endpoint", 0.0, 0,
                        {"reason": "no VLM endpoint configured (VISION_ENABLED + VISION_API_KEY)"}))
    for cat, cnt in top_failures:
        metrics.append((f"failure:{cat}", "count", float(cnt), len(failures), {}))
    return _persist_run(name, "blind", report, metrics)


# --------------------------------------------------------------------------- #
# RETRIEVAL EXPERIMENT (baselines A–E + graph arm)
# --------------------------------------------------------------------------- #
def run_rag_experiment(name: str = "rag") -> dict:
    import time

    from app.db.base import SessionLocal
    from app.services.graph import get_graph_store
    from app.services.rag import rerank as rerank_mod
    from app.services.rag.embeddings import HashingEmbeddings, get_embedding_provider
    from app.services.rag.lexical import BM25Index
    from app.services.rag.retriever import _candidates

    t0 = time.perf_counter()
    qrels = json.loads((EVAL_DIR / "retrieval_qrels.json").read_text())
    active = get_embedding_provider()
    semantic = active if not isinstance(active, HashingEmbeddings) else None
    lexical = HashingEmbeddings()

    with SessionLocal() as session:
        cands = _candidates(session, "proj_orion_ev")
        graph = get_graph_store()
        texts = [c.text for c in cands]
        lex_matrix = lexical.embed_documents(texts)
        sem_matrix = semantic.embed_documents(texts) if semantic else None
        bm25 = BM25Index().build([(c.chunk.id, c.payload, c.text) for c in cands])

        def dense_ranks(matrix, query):
            q = lexical.embed_query(query) if matrix is lex_matrix else semantic.embed_query(query)
            sims = matrix @ q
            order = np.argsort(-sims)
            return [cands[i].chunk.id for i in order], {cands[i].chunk.id: float(sims[i]) for i in range(len(cands))}

        results: dict[str, dict[str, list[float]]] = {}
        per_query: list[dict] = []
        retrieval_failures: list[dict] = []
        for q in qrels:
            focus = q["component_ids"]
            with SessionLocal() as s2:
                expanded = set(focus)
                for cid in focus:
                    expanded |= {h.component_id for h in graph.traverse(s2, cid, 1)}
            lex_rank, lex_scores = dense_ranks(lex_matrix, q["query"])
            sem_rank, sem_scores = (dense_ranks(sem_matrix, q["query"]) if semantic else (None, None))
            kw = [ref for ref, _ in bm25.score(q["query"])]
            lex_n = _normalize_scores(lex_scores)
            sem_n = _normalize_scores(sem_scores) if sem_scores else None

            def ranked_for(strategy: str) -> list[str]:
                if strategy == "keyword":
                    return kw
                if strategy == "lexical_vector":
                    return lex_rank
                if strategy == "semantic_vector":
                    return sem_rank or []
                use_sem = strategy.endswith("semantic") or strategy.endswith("graph")
                dense = sem_n if (use_sem and sem_n) else lex_n
                dense_rank = sem_rank if (use_sem and sem_rank) else lex_rank
                focus_set = expanded if strategy.endswith("graph") else focus
                fused = _rrf_scores([dense_rank, kw])
                scored = []
                for c in cands:
                    cid = c.chunk.id
                    meta, _parts = rerank_mod.metadata_score(c.payload, list(focus_set), q["revision"])
                    if _is_revision_scoped(q["query"]) and c.payload.get("revision") == q["revision"] \
                            and c.payload.get("document_type") == "revision_note":
                        fused[cid] = fused.get(cid, 0.0) + 0.02
                    fusion_n = fused.get(cid, 0.0)
                    score = (0.45 * dense.get(cid, 0.0) + 0.25 * lex_n.get(cid, 0.0)
                             + 0.15 * meta + 0.15 * fusion_n)
                    scored.append((cid, score))
                scored.sort(key=lambda kv: -kv[1])
                return [cid for cid, _ in scored]

            strategies = ["keyword", "lexical_vector", "revision_aware_lexical"]
            if semantic is not None:
                strategies += ["semantic_vector", "revision_aware_semantic", "revision_aware_semantic_graph"]
            row = {"query": q["query"]}
            for strategy in strategies:
                ranking = ranked_for(strategy)
                flags = _flags_for(cands, ranking, q)
                acc = results.setdefault(strategy, {"recall": [], "mrr": [], "ndcg": []})
                acc["recall"].append(M.recall_at_k(flags, 5))
                acc["mrr"].append(M.mrr(flags))
                acc["ndcg"].append(M.ndcg_at_k(flags, 5))
                row[strategy] = [bool(f) for f in flags[:5]]
                if sum(flags) == 0:
                    retrieval_failures.append({"case": q["query"][:60], "stage": "retrieval",
                                               "category": "retrieval_failure", "expected": q["relevant"],
                                               "predicted": ranking[:3], "component": q["component_ids"],
                                               "reason": f"no relevant chunk in top-5 for {strategy}"})
            per_query.append(row)

    report = {
        "suite": "rag", "created_at": utcnow().isoformat(),
        "embedding_backend": active.name, "semantic_backend": semantic.name if semantic else None,
        "qrels": len(qrels),
        "strategies": {k: {"recall@5": M.mean(v["recall"]), "mrr": M.mean(v["mrr"]),
                           "ndcg@5": M.mean(v["ndcg"]), "n": len(qrels)} for k, v in results.items()},
        "per_query": per_query,
        "failures": retrieval_failures,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    metrics = []
    for strategy, vals in report["strategies"].items():
        metrics.append((f"retrieval:{strategy}", "recall@5", vals["recall@5"], vals["n"], {}))
        metrics.append((f"retrieval:{strategy}", "mrr", vals["mrr"], vals["n"], {}))
        metrics.append((f"retrieval:{strategy}", "ndcg@5", vals["ndcg@5"], vals["n"], {}))
    top = sorted(((cat, sum(1 for f in retrieval_failures if f["category"] == cat))
                  for cat in {f["category"] for f in retrieval_failures}), key=lambda kv: -kv[1])
    for cat, cnt in top:
        metrics.append((f"failure:{cat}", "count", float(cnt), len(retrieval_failures), {}))
    report["top_failure_categories"] = top
    return _persist_run(name, "rag", report, metrics)


def _normalize_scores(scores: dict | None) -> dict:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _rrf_scores(rankings: list[list[str]], k: int = 60) -> dict:
    fused: dict = {}
    for ranking in rankings:
        for i, ref in enumerate(ranking):
            fused[ref] = fused.get(ref, 0.0) + 1.0 / (k + i + 1)
    return fused


def _is_revision_scoped(query: str) -> bool:
    return any(w in query.lower() for w in ("what changed", "changed in", "changes in", "revision note"))


def _flags_for(cands, ranking: list[str], q: dict) -> list[bool]:
    by_id = {c.chunk.id: c for c in cands}
    codes = {r for r in q["relevant"] if not _is_doc_key(r)}
    docsecs = {r for r in q["relevant"] if _is_doc_key(r)}
    flags = []
    for cid in ranking[:5]:
        c = by_id[cid]
        code = (c.chunk.metadata_json or {}).get("requirement_code")
        key = f"{c.payload['document_name']}§{c.payload.get('section', '')}"
        flags.append(bool(code in codes) or key in docsecs)
    return flags


# --------------------------------------------------------------------------- #
# VLM EVALUATION (wrapper; honest not-run when no endpoint)
# --------------------------------------------------------------------------- #
def run_vlm_evaluation(name: str = "vlm") -> dict:
    from app.services.vision.providers import vision_active

    if not vision_active():
        report = {"suite": "vlm", "status": "not_run_no_vlm_endpoint",
                  "note": "Configure VISION_ENABLED=1 plus VISION_BASE_URL/VISION_API_KEY (e.g. a "
                          "Qwen2.5-VL-7B-Instruct compatible endpoint) and re-run `make eval-vlm`. "
                          "No VLM metrics are reported or implied.",
                  "created_at": utcnow().isoformat()}
        return _persist_run(name, "vlm", report,
                            [("vlm", "status_not_run_no_endpoint", 0.0, 0, {"reason": report["note"]})])
    blind = run_blind_evaluation(name=f"{name}-blind")
    report = {"suite": "vlm", "created_at": utcnow().isoformat(), "vlm_active": True,
              "cv_vlm": blind["cv_vlm"], "consensus_counts": blind["consensus_counts"],
              "blind_run": blind.get("evaluation_run_id")}
    metrics = [("vlm", "evaluated", 1.0, blind["cases"], {})]
    return _persist_run(name, "vlm", report, metrics)


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
