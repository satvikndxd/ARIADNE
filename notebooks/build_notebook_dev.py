#!/usr/bin/env python3
"""DEV-ONLY generator for notebooks/ariadne_vlm_evaluation.ipynb.

The notebook itself is the shipped artefact; this builder exists so the
notebook JSON can be regenerated/validated without ever executing model
inference. Running it performs no downloads and no GPU work.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks" / "ariadne_vlm_evaluation.ipynb"

cells = []


def md(src):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)})


def code(src):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                  "outputs": [], "source": src.splitlines(keepends=True)})


# ---------------------------------------------------------------- 1
md("""# ARIADNE — VLM Evaluation (Colab / CUDA)

**Question:** *Does adding Qwen2.5-VL candidate-region interpretation improve
engineering revision-change interpretation on ARIADNE's blind benchmark?*

This notebook **measures**; it does not assume the answer is yes.

## Hard rules enforced here
* **INFERENCE** cells may read only `rev_a.png` and `rev_b.png` per case.
* **EVALUATION** cells load `ground_truth.json` strictly *after* inference.
* A runtime assertion fails the run if any ground-truth path is touched during inference.
* The VLM is a perception signal only: rules, authorization and state remain
  deterministic/server-side in ARIADNE. Consensus (`AGREED/CONFLICT/UNCERTAIN`)
  reuses `app/services/analysis/consensus.py`; matching semantics reuse
  `packages/evaluation/ariadne_evaluation/matching.py`.
* If the model cannot load, the notebook **stops the VLM arm** and reports why.
  It never fabricates numbers. `DRY_RUN=True` validates dataset/crops/prompts/
  schema **without claiming VLM inference occurred**.

## Outputs (written only when you run this)
`data/evaluation/results/`: `vlm_evaluation_results.json`, `vlm_case_results.csv`,
`vlm_failure_analysis.csv`, `vlm_summary.json`, `vlm_external_colab.json`
(import into ARIADNE with `python scripts/import_external_vlm_results.py`).
""")

# ---------------------------------------------------------------- 2
md("""## 2 · Experiment configuration""")
code("""import os, random, sys, time, json, inspect
import numpy as np

CONFIG = {
    "MODEL_ID": "Qwen/Qwen2.5-VL-7B-Instruct",
    "QUANTIZATION": None,          # None | "4bit" (bitsandbytes); optional, not mandatory
    "MAX_NEW_TOKENS": 256,
    "BATCH_SIZE": 1,               # region-by-region perception; batching reserved
    "DRY_RUN": False,              # True = validate pipeline without VLM inference
    "SEED": 1337,
    "REPO_ROOT": os.environ.get("ARIADNE_ROOT", ""),   # auto-discovered below if empty
}

random.seed(CONFIG["SEED"]); np.random.seed(CONFIG["SEED"])
try:
    import torch
    torch.manual_seed(CONFIG["SEED"])
except Exception:
    torch = None

print("config:", json.dumps(CONFIG, indent=1))
print("NOTE: all result values in this notebook are measured only after you run it.")""")

# ---------------------------------------------------------------- 3
md("""## 3 · GPU / environment check

Model weights are downloaded **only after** this cell passes and only when
`DRY_RUN=False`.""")
code("""import platform
print("python:", platform.python_version())
try:
    import torch
    print("torch:", torch.__version__, "| cuda available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("cuda version:", torch.version.cuda)
        print("gpu:", torch.cuda.get_device_name(0))
        free, total = torch.cuda.mem_get_info(0)
        print(f"vram: {free/1e9:.1f} GB free / {total/1e9:.1f} GB total")
        print("bf16 supported:", torch.cuda.is_bf16_supported())
except Exception as e:
    print("torch not importable:", e)
try:
    import transformers
    print("transformers:", transformers.__version__)
except Exception as e:
    print("transformers not importable:", e)

import importlib.util as iu
NEED = {"numpy": "numpy", "pillow": "PIL", "opencv-python-headless": "cv2",
        "pydantic": "pydantic", "pydantic-settings": "pydantic_settings", "httpx": "httpx"}
missing = [pkg for pkg, mod in NEED.items() if iu.find_spec(mod) is None]
import subprocess
if missing:
    print("installing:", missing)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing], check=True)
if not CONFIG["DRY_RUN"] and iu.find_spec("transformers") is None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers", "accelerate"],
                   check=True)
    if CONFIG["QUANTIZATION"] == "4bit":
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "bitsandbytes"], check=True)
print("environment check complete")""")

# ---------------------------------------------------------------- 4
md("""## 4 · Repository / benchmark discovery""")
code("""from pathlib import Path

def discover_repo() -> Path:
    cands = []
    if CONFIG["REPO_ROOT"]:
        cands.append(Path(CONFIG["REPO_ROOT"]))
    cands.append(Path("/content/ARIADNE"))
    try:
        start = Path(os.getcwd())
    except Exception:
        start = Path.cwd()
    cands += [start, *start.parents]
    for base in cands:
        if (base / "data" / "evaluation" / "blind" / "index.json").exists():
            return base
    raise SystemExit("ARIADNE repo with data/evaluation/blind/index.json not found. "
                     "Clone the repo (e.g. git clone <repo> /content/ARIADNE) or set "
                     "CONFIG['REPO_ROOT'] / env ARIADNE_ROOT.")

REPO = discover_repo()
BLIND = REPO / "data" / "evaluation" / "blind"
INDEX = json.loads((BLIND / "index.json").read_text())
RESULTS_DIR = REPO / "data" / "evaluation" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
print("repo:", REPO)
print("blind benchmark cases:", len(INDEX))
print("index fields:", sorted(INDEX[0].keys()))

for p in (str(REPO / "apps" / "api"), str(REPO / "packages" / "evaluation"), str(REPO / "notebooks")):
    if p not in sys.path:
        sys.path.insert(0, p)""")

# ---------------------------------------------------------------- 5
md("""## 5 · Benchmark integrity check (blindness contract)""")
code("""# (a) directory contract: exactly three files per case
for case in INDEX:
    files = sorted(p.name for p in (BLIND / case["case_id"]).iterdir())
    assert files == ["ground_truth.json", "rev_a.png", "rev_b.png"], (case["case_id"], files)

# (b) module contract: the blind analyzer must not reference truth/manifests
from app.services.analysis import blind
src = inspect.getsource(blind)
assert "ground_truth" not in src and "manifest" not in src.lower()

# (c) runtime contract: log every path handed to inference, assert afterwards
INFERENCE_PATHS = []
def case_image_paths(case):
    pa = REPO / case["path_a"]; pb = REPO / case["path_b"]
    assert pa.name == "rev_a.png" and pb.name == "rev_b.png"
    INFERENCE_PATHS.extend([str(pa), str(pb)])
    return pa, pb

print("integrity ok:", len(INDEX), "cases; inference restricted to rev_a.png/rev_b.png")""")

# ---------------------------------------------------------------- 6
md("""## 6 · Load ARIADNE utilities (CV pipeline, consensus, matching, schema)""")
code("""from app.services.analysis import blind as ariadne_blind
from app.services.analysis.consensus import combine, normalize_value, Signal
from app.services.vision.providers import crop_region, diff_overlay
from app.services.vision import registration, differencing
from app.schemas.vision import VLMInterpretation, VLMChangeType
from ariadne_evaluation import matching
from local_vlm_provider import LocalTransformersVision, load_model, prompt_preview, schema_selftest

print("blind analyzer module:", ariadne_blind.__name__)
print("canonical matching module:", matching.__file__)
print("schema/prompt dry self-test:", schema_selftest())""")

# ---------------------------------------------------------------- 7
md("""## 7 · Load Qwen2.5-VL (after environment check)

Failure here **stops the VLM arm** with an explanation; it never fabricates.""")
code("""VLM = None
VLM_ERROR = None
if CONFIG["DRY_RUN"]:
    print("DRY_RUN=True → skipping model load. No VLM inference will occur.")
    print("--- prompt the model would receive (first 900 chars) ---")
    print(prompt_preview({"component_id": "cmp_motor_mount"})[:900])
else:
    try:
        assert torch is not None and torch.cuda.is_available(), "CUDA required for the VLM arm"
        model, processor, dtype = load_model(CONFIG["MODEL_ID"], CONFIG["QUANTIZATION"])
        VLM = LocalTransformersVision(CONFIG["MODEL_ID"], model, processor,
                                      dtype=dtype, max_new_tokens=CONFIG["MAX_NEW_TOKENS"])
        print("loaded:", VLM.name, "| dtype:", dtype, "| device:", model.device)
    except Exception as e:
        VLM_ERROR = str(e)
        print("VLM LOAD FAILED — the VLM experiment stops here (no fabricated results).")
        print("Likely causes: (1) runtime has no CUDA GPU; (2) VRAM too small "
              "(~16 GB fp16/bf16, ~8-10 GB 4-bit for a 7B VLM); (3) missing packages "
              "(transformers/accelerate/bitsandbytes); (4) Hugging Face download blocked.")
        print("Detail:", VLM_ERROR[:500])""")

# ---------------------------------------------------------------- 8
md("""## 8 · EXPERIMENT A — CV-only baseline (inference; no ground truth)""")
code("""CV_RESULTS = {}
t0 = time.perf_counter()
for case in INDEX:
    pa, pb = case_image_paths(case)
    t1 = time.perf_counter()
    res = ariadne_blind.analyze_pair(pa, pb)          # no vision provider → cv-only
    CV_RESULTS[case["case_id"]] = {
        "detections": [d.as_dict() for d in res.detections],
        "n_regions": res.n_regions,
        "latency_ms": res.latency_ms,
        "method": res.method,
        "wall_ms": round((time.perf_counter() - t1) * 1000, 2),
    }
cv_wall = round((time.perf_counter() - t0) / 1000, 2)
assert all(p.endswith(("rev_a.png", "rev_b.png")) for p in INFERENCE_PATHS), \\
    "blindness violation: non-image path passed to inference"
print(f"CV-only done: {len(CV_RESULTS)} cases in {cv_wall}s; total regions "
      f"{sum(r['n_regions'] for r in CV_RESULTS.values())}")""")

# ---------------------------------------------------------------- 9
md("""## 9 · EXPERIMENT B — CV + Qwen2.5-VL (inference; no ground truth)

Each CV candidate region is cropped from both revisions with a difference
overlay and interpreted through the repository's strict schema + prompt policy
(`services/vision/prompts.py`, `schemas/vision.py`).""")
code("""VLM_RESULTS = {}
if VLM is None:
    print("VLM arm NOT RUN:", VLM_ERROR or "DRY_RUN / model unavailable")
else:
    t0 = time.perf_counter()
    for case in INDEX:
        pa, pb = case_image_paths(case)
        t1 = time.perf_counter()
        res = ariadne_blind.analyze_pair(pa, pb, vision=VLM, force_vlm=True)
        VLM_RESULTS[case["case_id"]] = {
            "detections": [d.as_dict() for d in res.detections],
            "n_regions": res.n_regions,
            "latency_ms": res.latency_ms,
            "method": res.method,
            "wall_ms": round((time.perf_counter() - t1) * 1000, 2),
        }
    vlm_wall = round((time.perf_counter() - t0) / 1000, 2)
    assert all(p.endswith(("rev_a.png", "rev_b.png")) for p in INFERENCE_PATHS), \\
        "blindness violation: non-image path passed to inference"
    print(f"CV+VLM done: {len(VLM_RESULTS)} cases in {vlm_wall}s; VLM calls: {VLM.call_count}")
    sample = next((d for r in VLM_RESULTS.values() for d in r["detections"]), None)
    if sample is not None:
        print("sample VLM interpretation:", json.dumps(sample.get("vlm"), indent=1)[:600])
    else:
        print("no candidate regions were produced on any case (CV found nothing).")""")

# ---------------------------------------------------------------- 10
md("""## 10 · Consensus analysis (structured vs CV vs VLM)

Disagreements are reported, never silently merged.""")
code("""from collections import Counter
consensus_counts = Counter()
disagreements = []
for cid, r in VLM_RESULTS.items():
    for d in r["detections"]:
        st = (d.get("consensus") or {}).get("status", "n/a")
        consensus_counts[st] += 1
        if st == "CONFLICT":
            disagreements.append({"case": cid, "signals": d["consensus"]["signals"],
                                  "notes": d["consensus"]["notes"]})
print("consensus distribution:", dict(consensus_counts))
print("conflicts:", len(disagreements))
for dg in disagreements[:5]:
    print(" ", dg["case"], json.dumps(dg["signals"])[:220])""")

# ---------------------------------------------------------------- 11
md("""## 11 · EVALUATION (ground truth loaded NOW, after all inference)""")
code("""import pandas as pd

GT = {case["case_id"]: json.loads((BLIND / case["case_id"] / "ground_truth.json").read_text())
      for case in INDEX}   # ← evaluator-only, post-inference

def evaluate_arm(results):
    tp = fp = fn = 0
    type_ok = type_n = old_ok = new_ok = val_n = comp_ok = comp_n = 0
    unknown = calls = agreed = conflicted = 0
    per_case = {}
    for cid, r in results.items():
        entries = GT[cid]["changes"]
        dets = [d["bbox"] for d in r["detections"]]
        matched, fp_idx, fn_idx = matching.match_detections(dets, entries)
        tp += len(matched); fp += len(fp_idx); fn += len(fn_idx)
        case_type_ok = len(matched) > 0
        for gi, di in matched:
            e, d = entries[gi], r["detections"][di]
            calls += 1
            if d.get("change_type") is None:
                unknown += 1            # this arm abstains on type
                case_type_ok = False
            else:
                type_n += 1
                ok = d["change_type"] == e["change_type"]
                type_ok += ok
                case_type_ok = case_type_ok and ok
            if e.get("old_value") not in (None, "None") and d.get("old_value"):
                val_n += 1
                old_ok += int(normalize_value(d["old_value"]) == normalize_value(e["old_value"]))
                new_ok += int(normalize_value(d.get("new_value")) == normalize_value(e["new_value"]))
            comp_n += 1
            feat = (d.get("feature") or "").lower()
            comp_ok += int(any(k in feat for k in e["semantic"].split("_") if len(k) > 3))
            st = (d.get("consensus") or {}).get("status")
            agreed += st == "AGREED"
            conflicted += st == "CONFLICT"
        per_case[cid] = {"tp": len(matched), "fp": len(fp_idx), "fn": len(fn_idx),
                         "gt": len(entries), "type_ok": case_type_ok}
    p_ = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    f_ = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
    acc = lambda a, b: (round(a / b, 4) if b else None)
    return {"precision": round(p_, 4), "recall": round(r_, 4), "f1": round(f_, 4),
            "tp": tp, "fp": fp, "fn": fn,
            "type_accuracy": acc(type_ok, type_n),
            "old_value_accuracy": acc(old_ok, val_n),
            "new_value_accuracy": acc(new_ok, val_n),
            "component_accuracy": acc(comp_ok, comp_n),
            "unknown_rate": acc(unknown, calls),
            "agreement_rate": acc(agreed, calls), "conflict_rate": acc(conflicted, calls),
            "per_case": per_case, "calls": calls}

CV_METRICS = evaluate_arm(CV_RESULTS)
VLM_METRICS = evaluate_arm(VLM_RESULTS) if VLM_RESULTS else None
print("CV-only :", {k: v for k, v in CV_METRICS.items() if k != "per_case"})
print("CV+VLM  :", {k: v for k, v in (VLM_METRICS or {}).items() if k != "per_case"} or "NOT RUN")
print("note: CV-only emits no type/value hypothesis (abstains) — its type/value "
      "accuracies are None by design, not zero.")""")

md("""### Per-case results table""")
code("""def _matched(cid, ds):
    return matching.match_detections([d["bbox"] for d in ds], GT[cid]["changes"])

def type_correct(cid, ds):
    m, _, _ = _matched(cid, ds)
    if not m:
        return None
    return all(ds[di]["change_type"] == GT[cid]["changes"][gi]["change_type"] for gi, di in m)

def value_correct(cid, ds):
    m, _, _ = _matched(cid, ds)
    vals = [gi for gi, di in m if GT[cid]["changes"][gi].get("old_value") not in (None, "None")]
    if not vals:
        return None
    return all(normalize_value(ds[di].get("old_value")) ==
               normalize_value(GT[cid]["changes"][gi]["old_value"]) for gi, di in m if gi in vals)

def comp_correct(cid, ds):
    m, _, _ = _matched(cid, ds)
    if not m:
        return None
    return all(any(k in (ds[di].get("feature") or "").lower()
                   for k in GT[cid]["changes"][gi]["semantic"].split("_") if len(k) > 3)
               for gi, di in m)

rows = []
for case in INDEX:
    cid = case["case_id"]
    cv_dets = CV_RESULTS[cid]["detections"]
    vl_dets = VLM_RESULTS.get(cid, {"detections": []})["detections"]
    cv_p = CV_METRICS["per_case"][cid]
    vl_p = (VLM_METRICS or {"per_case": {}})["per_case"].get(cid)
    cons = Counter((d.get("consensus") or {}).get("status") for d in vl_dets)
    rows.append({
        "case_id": cid,
        "ground_truth_changes": len(GT[cid]["changes"]),
        "cv_changes": len(cv_dets),
        "vlm_changes": len(vl_dets),
        "cv_correct": cv_p["fn"] == 0,
        "vlm_correct": (vl_p["fn"] == 0) if vl_p else None,
        "cv_type_correct": None,
        "vlm_type_correct": type_correct(cid, vl_dets),
        "cv_value_correct": None,
        "vlm_value_correct": value_correct(cid, vl_dets),
        "cv_component_correct": None,
        "vlm_component_correct": comp_correct(cid, vl_dets),
        "consensus": cons.most_common(1)[0][0] if cons else "n/a",
        "failure_category": "",
    })
CASE_DF = pd.DataFrame(rows)
CASE_DF""")

# ---------------------------------------------------------------- 12
md("""## 12 · Failure analysis""")
code("""fail_rows = []
for case in INDEX:
    cid = case["case_id"]
    gt = GT[cid]["changes"]
    for arm, results in (("cv_only", CV_RESULTS), ("cv_vlm", VLM_RESULTS)):
        if not results:
            continue
        dets = results[cid]["detections"]
        matched, fp_idx, fn_idx = matching.match_detections([d["bbox"] for d in dets], gt)
        for gi in fn_idx:
            e = gt[gi]
            cat = ("visual ambiguity" if e.get("moved_only") else
                   "annotation noise" if e["change_type"] == "METADATA_CHANGE" else
                   "CV localization")
            fail_rows.append({"case_id": cid, "arm": arm, "expected": e["change_type"],
                              "predicted": None, "component": e["component_id"],
                              "stage": "detection", "category": cat,
                              "reason": f"gt not covered: {e['bbox_b']}"})
        for di in fp_idx:
            d = dets[di]
            fail_rows.append({"case_id": cid, "arm": arm, "expected": None,
                              "predicted": d.get("change_type"), "component": "cmp_motor_mount",
                              "stage": "detection",
                              "category": "annotation noise" if case["difficulty"] == "trap"
                              else "CV localization",
                              "reason": f"spurious region {d['bbox']}"})
        counts = Counter(di for _, di in matched)
        for di, n in counts.items():
            if n > 1:
                fail_rows.append({"case_id": cid, "arm": arm, "expected": "multiple",
                                  "predicted": "merged region", "component": "cmp_motor_mount",
                                  "stage": "detection", "category": "multiple changes merged",
                                  "reason": "one CV region covered several gt entries"})
        for gi, di in matched:
            e, d = gt[gi], dets[di]
            if arm != "cv_vlm":
                continue
            if d.get("change_type") is None:
                fail_rows.append({"case_id": cid, "arm": arm, "expected": e["change_type"],
                                  "predicted": "UNKNOWN", "component": e["component_id"],
                                  "stage": "interpretation", "category": "unknown/abstention",
                                  "reason": (d.get("vlm") or {}).get("error") or "model abstained"})
            elif d["change_type"] != e["change_type"]:
                fail_rows.append({"case_id": cid, "arm": arm, "expected": e["change_type"],
                                  "predicted": d["change_type"], "component": e["component_id"],
                                  "stage": "interpretation", "category": "wrong change type",
                                  "reason": "VLM type disagreement with ground truth"})
            if normalize_value(d.get("old_value")) not in (None, normalize_value(e.get("old_value"))):
                fail_rows.append({"case_id": cid, "arm": arm, "expected": e.get("old_value"),
                                  "predicted": d.get("old_value"), "component": e["component_id"],
                                  "stage": "interpretation", "category": "wrong value",
                                  "reason": "normalized old-value mismatch"})
            if (d.get("consensus") or {}).get("status") == "CONFLICT":
                fail_rows.append({"case_id": cid, "arm": arm, "expected": e["change_type"],
                                  "predicted": d.get("change_type"), "component": e["component_id"],
                                  "stage": "cross-check", "category": "VLM interpretation",
                                  "reason": "; ".join((d.get("consensus") or {}).get("notes", []))})
FAIL_DF = pd.DataFrame(fail_rows)
cat_by_case = FAIL_DF.groupby("case_id").category.apply(lambda s: "; ".join(sorted(set(s)))) \\
    if len(FAIL_DF) else pd.Series(dtype=str)
CASE_DF["failure_category"] = CASE_DF.case_id.map(cat_by_case).fillna("")
print(FAIL_DF.category.value_counts() if len(FAIL_DF) else "no failures recorded")
CASE_DF.to_csv(RESULTS_DIR / "vlm_case_results.csv", index=False)
FAIL_DF.to_csv(RESULTS_DIR / "vlm_failure_analysis.csv", index=False)
CASE_DF""")

# ---------------------------------------------------------------- 13
md("""## 13 · Visual examples (ground truth shown to HUMANS only, post-inference)""")
code("""import matplotlib.pyplot as plt
import cv2

def crops_for(cid, det_bbox):
    entry = next(c for c in INDEX if c["case_id"] == cid)
    pa, pb = REPO / entry["path_a"], REPO / entry["path_b"]
    ga = registration.normalize(registration.load_grayscale(pa))
    gb = registration.normalize(registration.load_grayscale(pb))
    ia, ib = cv2.imread(str(pa)), cv2.imread(str(pb))
    return (crop_region(ia, det_bbox), crop_region(ib, det_bbox), diff_overlay(ga, gb, det_bbox))

def pick(pred):
    for cid, r in VLM_RESULTS.items():
        for d in r["detections"]:
            if pred(cid, d):
                return cid, d
    return None, None

groups = {
    "VLM improvement (correct type)": lambda c, d: d.get("change_type") and any(
        d["change_type"] == g["change_type"] and matching.match_score(d["bbox"], g["bbox_b"]) >= 0.5
        for g in GT[c]["changes"]),
    "VLM regression (wrong type)": lambda c, d: d.get("change_type") and any(
        d["change_type"] != g["change_type"] and matching.match_score(d["bbox"], g["bbox_b"]) >= 0.5
        for g in GT[c]["changes"]),
    "VLM disagreement (CONFLICT)": lambda c, d: (d.get("consensus") or {}).get("status") == "CONFLICT",
    "VLM uncertain (UNKNOWN)": lambda c, d: d.get("change_type") is None,
}
fig, axes = plt.subplots(len(groups), 3, figsize=(11, 3.0 * len(groups)))
if VLM_RESULTS:
    for row, (title, pred) in enumerate(groups.items()):
        cid, d = pick(pred)
        if cid is None:
            for col in range(3):
                axes[row, col].axis("off")
                axes[row, col].set_title(f"{title}: no example", fontsize=8)
            continue
        ca, cb, dv = crops_for(cid, d["bbox"])
        gt_entry = next((g for g in GT[cid]["changes"]
                         if matching.match_score(d["bbox"], g["bbox_b"]) >= 0.5), None)
        for col, (img, name) in enumerate((("Rev A crop", ca), ("Rev B crop", cb), ("diff overlay", dv))):
            axes[row, col].imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            axes[row, col].set_title(f"{title} — {name} · {cid}", fontsize=8)
            axes[row, col].axis("off")
        print(f"{title}: case {cid} | CV: region only | VLM: {d.get('change_type')} "
              f"({d.get('old_value')} → {d.get('new_value')}) | GT: "
              f"{gt_entry['change_type'] if gt_entry else 'unmatched'}")
else:
    for row in range(len(groups)):
        for col in range(3):
            axes[row, col].axis("off")
    print("VLM arm not run — gallery unavailable (nothing fabricated).")
plt.tight_layout()
plt.show()""")

# ---------------------------------------------------------------- 14
md("""## 14 · Latency / resource analysis""")
code("""cv_lat = [r["wall_ms"] for r in CV_RESULTS.values()]
vlm_lat = [r["wall_ms"] for r in VLM_RESULTS.values()] if VLM_RESULTS else []
vlm_call_ms = [d["vlm"]["latency_ms"] for r in VLM_RESULTS.values()
               for d in r["detections"] if (d.get("vlm") or {}).get("latency_ms")] if VLM_RESULTS else []
LATENCY = {
    "cv_only_s_per_case": round(sum(cv_lat) / 1000 / max(1, len(cv_lat)), 3),
    "cv_vlm_s_per_case": round(sum(vlm_lat) / 1000 / max(1, len(vlm_lat)), 3) if vlm_lat else None,
    "vlm_s_per_region": round(sum(vlm_call_ms) / 1000 / max(1, len(vlm_call_ms)), 3) if vlm_call_ms else None,
    "vlm_calls": VLM.call_count if VLM is not None else 0,
    "gpu_peak_memory_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)
    if (torch is not None and torch.cuda.is_available()) else None,
}
LATENCY["vlm_overhead_s_per_case"] = (
    round(LATENCY["cv_vlm_s_per_case"] - LATENCY["cv_only_s_per_case"], 3)
    if LATENCY["cv_vlm_s_per_case"] is not None else None)
print(json.dumps(LATENCY, indent=1))""")

# ---------------------------------------------------------------- 15
md("""## 15 · Results summary + visualizations""")
code("""import matplotlib.pyplot as plt

m2 = VLM_METRICS or {}
arms = ["CV-only", "CV+VLM"]
fig, axes = plt.subplots(2, 3, figsize=(15, 8))
def bar(ax, vals, title):
    x = np.arange(len(vals))
    ax.bar(x, [v if v is not None else 0.0 for v in vals], color=["#4d8fd1", "#e0762a"])
    ax.set_xticks(x); ax.set_xticklabels(arms, fontsize=8)
    ax.set_title(title, fontsize=9); ax.set_ylim(0, 1)
bar(axes[0, 0], [CV_METRICS["precision"], m2.get("precision")], "precision")
bar(axes[0, 1], [CV_METRICS["recall"], m2.get("recall")], "recall")
bar(axes[0, 2], [CV_METRICS["f1"], m2.get("f1")], "F1")
bar(axes[1, 0], [CV_METRICS["type_accuracy"], m2.get("type_accuracy")], "change-type accuracy")
bar(axes[1, 1], [CV_METRICS["old_value_accuracy"], m2.get("old_value_accuracy")], "old-value accuracy")
bar(axes[1, 2], [CV_METRICS["new_value_accuracy"], m2.get("new_value_accuracy")], "new-value accuracy")
plt.tight_layout(); plt.show()

if VLM_RESULTS:
    pairs = []
    for cid, r in VLM_RESULTS.items():
        m, _, _ = matching.match_detections([d["bbox"] for d in r["detections"]], GT[cid]["changes"])
        for gi, di in m:
            pairs.append((GT[cid]["changes"][gi]["change_type"],
                          r["detections"][di]["change_type"] or "UNKNOWN"))
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    M = np.zeros((len(labels), len(labels)), dtype=int)
    for g, p in pairs:
        M[labels.index(g), labels.index(p)] += 1
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.imshow(M, cmap="Blues")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("VLM predicted"); ax.set_ylabel("ground truth")
    for i in range(len(labels)):
        for j in range(len(labels)):
            if M[i, j]:
                ax.text(j, i, M[i, j], ha="center", va="center", fontsize=8)
    ax.set_title("VLM change-type confusion matrix")
    plt.tight_layout(); plt.show()

if len(FAIL_DF):
    vc = FAIL_DF.category.value_counts()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(vc.index, vc.values, color="#c9a227")
    ax.set_title("failure categories")
    plt.tight_layout(); plt.show()

both = cv_only_ok = vlm_only_ok = neither = 0
for cid in CV_METRICS["per_case"]:
    c_ok = CV_METRICS["per_case"][cid]["fn"] == 0
    v_ok = bool(VLM_METRICS and VLM_METRICS["per_case"][cid]["fn"] == 0
                and VLM_METRICS["per_case"][cid]["type_ok"])
    both += int(c_ok and v_ok); cv_only_ok += int(c_ok and not v_ok)
    vlm_only_ok += int((not c_ok) and v_ok); neither += int((not c_ok) and (not v_ok))
print("paired cases — both correct:", both, "| CV only:", cv_only_ok,
      "| VLM only:", vlm_only_ok, "| neither:", neither)
if VLM_METRICS and len(INDEX) >= 20:
    disc = cv_only_ok + vlm_only_ok
    print(f"discordant pairs: {disc} (McNemar applicable when >0; exact p from "
          f"binomial({min(cv_only_ok, vlm_only_ok)}, {disc}, 0.5) if you wish — "
          "not claimed automatically on this synthetic benchmark)")

delta = {}
if VLM_METRICS:
    delta = {k: round(VLM_METRICS[k] - CV_METRICS[k], 4) for k in ("precision", "recall", "f1")}
    if delta["f1"] > 0:
        print(f"VLM improved F1 on this benchmark ({CV_METRICS['f1']} → {VLM_METRICS['f1']}). "
              "No claim is made beyond this benchmark.")
    elif delta["f1"] < 0:
        print(f"VLM performed worse on this benchmark ({CV_METRICS['f1']} → {VLM_METRICS['f1']}); "
              "documented honestly.")
    else:
        print("No F1 difference on this benchmark.")
else:
    print("VLM arm not run — no comparison possible; nothing is claimed.")""")

# ---------------------------------------------------------------- 16
md("""## 16 · Export results

Values below exist **only because you executed the notebook**. If the VLM arm
did not run, the bundle is marked `dry_run` and the ARIADNE importer refuses it.""")
code("""import datetime as dt

created = dt.datetime.now(dt.timezone.utc).isoformat()
summary = {
    "model": CONFIG["MODEL_ID"] if VLM is not None else None,
    "quantization": CONFIG["QUANTIZATION"],
    "benchmark_cases": len(INDEX),
    "cv_only": {k: CV_METRICS[k] for k in ("precision", "recall", "f1")},
    "cv_plus_vlm": ({k: VLM_METRICS[k] for k in ("precision", "recall", "f1")} if VLM_METRICS else None),
    "improvement": delta if VLM_METRICS else None,
    "v_accuracy": (VLM_METRICS or {}).get("type_accuracy"),
    "unknown_rate": (VLM_METRICS or {}).get("unknown_rate"),
    "latency": LATENCY,
    "dry_run": bool(CONFIG["DRY_RUN"]) or VLM is None,
    "created_at": created,
}
(RESULTS_DIR / "vlm_summary.json").write_text(json.dumps(summary, indent=2))
(RESULTS_DIR / "vlm_evaluation_results.json").write_text(json.dumps({
    "suite": "vlm-external", "created_at": created, "config": CONFIG,
    "cv_only": CV_METRICS, "cv_plus_vlm": VLM_METRICS,
    "consensus": dict(consensus_counts), "latency": LATENCY,
    "per_case": CASE_DF.to_dict(orient="records"),
    "failures": FAIL_DF.to_dict(orient="records"),
}, indent=2, default=str))

metrics = []
for subset, m in [("blind:cv_only", CV_METRICS)] + ([("blind:cv_vlm", VLM_METRICS)] if VLM_METRICS else []):
    for key in ("precision", "recall", "f1", "type_accuracy", "old_value_accuracy",
                "new_value_accuracy", "component_accuracy", "unknown_rate",
                "agreement_rate", "conflict_rate"):
        if m.get(key) is not None:
            metrics.append({"subset": subset, "metric": key, "value": m[key],
                            "n": m.get("calls", len(INDEX)), "detail": {}})
if len(FAIL_DF):
    for cat, cnt in FAIL_DF.category.value_counts().items():
        metrics.append({"subset": f"failure:{cat}", "metric": "count", "value": float(cnt),
                        "n": len(FAIL_DF), "detail": {}})
bundle = {"suite": "vlm", "source": "colab-external", "model": summary["model"],
          "quantization": summary["quantization"], "benchmark_cases": len(INDEX),
          "notebook": "notebooks/ariadne_vlm_evaluation.ipynb", "created_at": created,
          "dry_run": summary["dry_run"], "metrics": metrics, "summary": summary}
(RESULTS_DIR / "vlm_external_colab.json").write_text(json.dumps(bundle, indent=2))
for name in ("vlm_summary.json", "vlm_evaluation_results.json", "vlm_case_results.csv",
             "vlm_failure_analysis.csv", "vlm_external_colab.json"):
    print("written:", RESULTS_DIR / name)
print()
print("Import measured values into ARIADNE (creates a NEW evaluation run;")
print("production records are never overwritten):")
print("    python scripts/import_external_vlm_results.py")""")

# ---------------------------------------------------------------- 17
md("""## 17 · Reproducibility notes

* Seeds fixed in §2; greedy decoding (`do_sample=False`); dtype/quantization and
  model id recorded in every export.
* Matching semantics identical to production: `ariadne_evaluation.matching`
  (forward containment ≥ 0.5, reverse ≥ 0.7; one detection may cover several
  ground-truth entries). The benchmark, its traps and thresholds are untouched.
* Blindness: inference touched only `rev_a.png` / `rev_b.png` (asserted in
  §5, §8, §9); ground truth entered the process only in §11.
* Expected GPU: ~16 GB VRAM (fp16/bf16) for Qwen2.5-VL-7B-Instruct; ~8–10 GB
  with `QUANTIZATION="4bit"` (bitsandbytes). CPU-only is unsupported for the VLM
  arm: the notebook stops with an explanation instead of fabricating.
* Import measured values with `python scripts/import_external_vlm_results.py`;
  it creates a new `EvaluationRun` named `vlm:colab-external:<model>` and
  refuses dry-run bundles.
* Until this notebook is executed on a GPU, ARIADNE makes **no VLM accuracy
  claim** anywhere in its documentation or dashboards.
""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
NB.write_text(json.dumps(nb, indent=1))
print("notebook written:", NB, "| cells:", len(cells))
