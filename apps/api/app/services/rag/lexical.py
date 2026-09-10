"""BM25 lexical retrieval — the deterministic half of hybrid search."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from app.services.rag.embeddings import tokenize


@dataclass
class BM25Index:
    k1: float = 1.5
    b: float = 0.75
    docs: list[tuple[str, dict]] = field(default_factory=list)
    _tf: list[Counter] = field(default_factory=list)
    _df: Counter = field(default_factory=Counter)
    _len: list[int] = field(default_factory=list)
    _avg: float = 0.0

    def build(self, docs: list[tuple[str, dict, str]]) -> "BM25Index":
        self.docs = [(ref, payload) for ref, payload, _ in docs]
        self._tf, self._df, self._len = [], Counter(), []
        for _, _, text in docs:
            toks = tokenize(text)
            tf = Counter(toks)
            self._tf.append(tf)
            self._len.append(len(toks))
            for tok in tf:
                self._df[tok] += 1
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        return self

    def score(self, query: str) -> list[tuple[str, float]]:
        if not self.docs:
            return []
        q = tokenize(query)
        n = len(self.docs)
        scores: list[float] = [0.0] * n
        for tok in set(q):
            df = self._df.get(tok, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(self._tf):
                f = tf.get(tok, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self._len[i] / (self._avg or 1.0))
                scores[i] += idf * f * (self.k1 + 1) / denom
        ranked = sorted(
            ((self.docs[i][0], s) for i, s in enumerate(scores) if s > 0), key=lambda t: -t[1]
        )
        return ranked
