"""Pure metric functions.  Unit-testable, dependency-free."""
from __future__ import annotations

import math
from typing import Sequence


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn}


def recall_at_k(relevance: Sequence[bool], k: int) -> float:
    top = list(relevance)[:k]
    total = sum(relevance)
    return (sum(top) / total) if total else 0.0


def mrr(relevance: Sequence[bool]) -> float:
    for i, rel in enumerate(relevance):
        if rel:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevance: Sequence[bool], k: int) -> float:
    gains = [1.0 if r else 0.0 for r in list(relevance)[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(relevance, reverse=True)[:k]
    idcg = sum(1.0 / math.log2(i + 2) for i, r in enumerate(ideal) if r)
    return dcg / idcg if idcg else 0.0


def accuracy(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 0.0


def mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0
