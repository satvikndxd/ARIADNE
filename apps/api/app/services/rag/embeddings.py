"""Embedding providers behind one protocol.

* ``OpenAICompatibleEmbeddings`` — any endpoint exposing ``POST /embeddings``.
* ``HashingEmbeddings``          — deterministic, offline, no model.  A hashed
  bag-of-words projection (word + char-n-gram features, sublinear tf, L2
  norm).  It is *not* semantic; it is lexical-overlap similarity, and the code
  says so.  It exists so retrieval is fully functional and testable with zero
  infrastructure, exactly like the rest of DEMO_MODE.
"""
from __future__ import annotations

import hashlib
import os
import math
import re
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from app.core.config import settings
from app.core.errors import EmbeddingError
from app.core.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")


def tokenize(text: str) -> list[str]:
    words = _TOKEN_RE.findall(text.lower())
    feats = list(words)
    for w in words:
        if len(w) > 4:
            feats += [w[i : i + 3] for i in range(len(w) - 2)]
    return feats


def _hf_cache_dir() -> Path:
    home = Path.home()
    return Path(os.environ.get("HF_HOME", home / ".cache" / "huggingface")) / "hub"


def model_in_hf_cache(model: str) -> bool:
    slug = "models--" + model.replace("/", "--")
    d = _hf_cache_dir() / slug
    if not d.is_dir():
        return False
    snaps = list((d / "snapshots").glob("*")) if (d / "snapshots").is_dir() else []
    return any(any(p.is_file() for p in snap.rglob("*")) for snap in snaps)


class LocalSemanticEmbeddings:
    """Real semantic embeddings via sentence-transformers (default BAAI/bge-m3).

    Loaded lazily; if the library or model is unavailable the factory falls
    back to the lexical embedder and says so in ``/system/status``.
    """

    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model = None

    @property
    def name(self) -> str:
        return f"sentence-transformers:{self.model_name}"

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # deferred heavy import

            log.info("semantic_embedding_load_start", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
            dim_fn = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
            self.dim = int(dim_fn())
            log.info("semantic_embedding_loaded", model=self.model_name, dim=self.dim)
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float64)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class HashingEmbeddings:
    name = "hashing"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embedding_dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float64)
        counts: dict[str, int] = {}
        for tok in tokenize(text):
            counts[tok] = counts.get(tok, 0) + 1
        for tok, n in counts.items():
            bucket = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16) % self.dim
            sign = 1.0 if bucket % 2 == 0 else -1.0
            v[bucket] += sign * (1.0 + math.log(n))
        norm = float(np.linalg.norm(v))
        return v / norm if norm > 0 else v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


class OpenAICompatibleEmbeddings:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def _call(self, texts: list[str]) -> np.ndarray:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                matrix = np.array([d["embedding"] for d in sorted(data, key=lambda d: d["index"])], dtype=np.float64)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return matrix / norms
        except Exception as exc:  # network/HTTP/shape
            log.error("embedding_provider_failed", error=str(exc), model=self.model)
            raise EmbeddingError(f"Embedding provider '{self.model}' failed.") from exc

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._call(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._call([text])[0]


_provider: EmbeddingProvider | None = None


def resolve_embedding_provider() -> tuple[EmbeddingProvider, str]:
    """Precedence: remote semantic → local semantic → lexical fallback.

    Returns (provider, reason) so startup logging and ``/system/status`` can
    explain *why* a backend is active.
    """
    if settings.embeddings_configured:
        base = settings.embedding_base_url or settings.llm_base_url
        key = settings.embedding_api_key or settings.llm_api_key
        return OpenAICompatibleEmbeddings(base, key, settings.embedding_model, settings.embedding_dim), \
            "remote endpoint configured"
    if settings.embedding_local_enabled:
        import importlib.util

        if importlib.util.find_spec("sentence_transformers") is None:
            return HashingEmbeddings(), "sentence-transformers not installed → lexical fallback"
        if not settings.embedding_allow_download and not model_in_hf_cache(settings.embedding_model):
            return HashingEmbeddings(), f"{settings.embedding_model} not in HF cache and downloads disabled"
        try:
            return LocalSemanticEmbeddings(settings.embedding_model, settings.embedding_dim), \
                f"local semantic model {settings.embedding_model}"
        except Exception as exc:  # pragma: no cover - environment dependent
            log.warning("semantic_embedding_unavailable", error=str(exc))
            return HashingEmbeddings(), f"semantic model failed to load ({exc}) → lexical fallback"
    return HashingEmbeddings(), "local semantic embeddings disabled"


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider, _reason = resolve_embedding_provider()
        log.info("embedding_backend", provider=_provider.name, reason=_reason)
    return _provider


def embedding_backend_report() -> dict:
    provider, reason = (_provider, "active") if _provider is not None else resolve_embedding_provider()
    semantic = not isinstance(provider, HashingEmbeddings)
    return {"provider": provider.name, "semantic": semantic, "reason": reason,
            "model": getattr(provider, "model_name", getattr(provider, "model", "hashing"))}


def reset_provider_cache() -> None:
    global _provider
    _provider = None
