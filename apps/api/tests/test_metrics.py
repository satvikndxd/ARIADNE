from __future__ import annotations

from ariadne_evaluation import metrics as M


def test_prf():
    assert M.precision_recall_f1(8, 2, 0) == {"precision": 0.8, "recall": 1.0, "f1": 0.8889, "tp": 8, "fp": 2, "fn": 0}


def test_ranking_metrics():
    rel = [False, True, False, True, False]
    assert M.recall_at_k(rel, 4) == 1.0
    assert M.mrr(rel) == 0.5
    assert 0.0 < M.ndcg_at_k(rel, 5) <= 1.0
    assert M.ndcg_at_k([True, True], 2) == 1.0
    assert M.mrr([False, False]) == 0.0
