# Benchmarks — construction, separation, metrics, limitations

## 1. Non-blind pairs benchmark (`data/evaluation/pairs/`)
32 rendered revision pairs **with** manifests alongside the images. Used to
score the production pipeline (manifest diff + CV confirmation + extraction).
Ground truth is generated *by construction*: parameters are perturbed, both
revisions rendered, and the changed items recorded with bbox/values/severity.

**Honest caveat:** precision/recall of 1.0 on this set measures pipeline
plumbing and CV agreement, not an independently trained detector.

## 2. Blind benchmark (`data/evaluation/blind/`)
24 cases; each directory contains exactly:

```
case_NNN/rev_a.png   ← analyzer input
case_NNN/rev_b.png   ← analyzer input
case_NNN/ground_truth.json   ← evaluator-only
```

Separation is enforced at three levels:
1. **directory contract** — generator asserts the 3-file layout; a pytest
   (`test_blind_separation.py`) re-checks every case directory;
2. **module contract** — `services/analysis/blind.py` accepts only two image
   paths (+ optional vision provider); a test greps its source for the
   forbidden tokens and inspects its signature;
3. **process contract** — `run_blind_evaluation` calls `analyze_pair` first
   and opens the truth file only afterwards.

Case mix: sub-millimetre deltas, tolerance-only text edits, hole add/remove,
annotation *moves*, material/finish swaps, five-change revisions, speckle
noise (trap cases with zero engineering changes), title-block-only edits and
geometrically similar combinations. Ground truth covers **annotation boxes and
geometry regions** (rings/outlines), because annotation boxes alone
under-specify visible change.

## 3. Matching criterion
Region-level detectors localize *clusters*. A detection matches a ground-truth
entry when the detected region **contains ≥50 % of the gt box**, or the
detection lies **≥70 % inside** the gt box (character-level text edits produce
tiny diffs inside a larger label). Documented in
`evaluation_service._containment` / `_reverse_containment`.

## 4. Metrics
* detection: precision / recall / F1 (all-gt and engineering-only views),
* interpretation (CV+VLM arm): type / old-value / new-value accuracy,
  component attribution, impact-category accuracy,
* consensus distribution (AGREED / CONFLICT / UNCERTAIN),
* retrieval: Recall@5, MRR, nDCG@5 per strategy,
* failure analysis: per-case records with categories
  (`detection_miss`, `localization_weak`, `spurious_detection`,
  `irrelevant_noise_fp`, `type_error`, `value_error`, `visual_ambiguity`,
  `vlm_disagreement`, `retrieval_failure`) and top-category summary.

## 5. Train/test separation
No model is trained in this project (baseline-first principle). "Separation"
here means: generation parameters → ground truth are never readable by the
analyzer; the analyzer's only inputs are pixels (blind) or pixels + project
data (production).

## 6. Limitations
* Synthetic drawings from one renderer family; real scanned/CAD rasters will
  stress registration more than this set does.
* Blind CV-only precision is bounded by noise traps *by design* — they exist
  to expose false-positive behaviour, not to be passed silently.
* VLM-arm metrics require a vision endpoint; until configured they are
  reported as not-run, never estimated.
