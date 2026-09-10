"""Vector stores.

``NumpyVectorStore`` (default on SQLite): vectors in memory, persisted to the
``vector_records`` table so restarts don't re-embed.

``PgVectorStore`` (default when DATABASE_URL is PostgreSQL and ``pgvector`` is
importable): real ``vector`` column with a HNSW-free exact cosine index —
correct first, fast later.

Both expose ``search(store, query, top_k, predicate)`` where ``predicate`` is a
Python callable over the payload (metadata filtering happens *before* ranking
cuts, never silently after).
"""
from __future__ import annotations

import json
from typing import Callable, Protocol

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.db.models import VectorRecord

log = get_logger(__name__)

CHUNK_STORE = "chunks"


class VectorStore(Protocol):
    name: str

    def upsert(self, store: str, records: list[dict]) -> int: ...

    def search(
        self,
        session: Session,
        store: str,
        query: np.ndarray,
        top_k: int,
        predicate: Callable[[dict], bool] | None = None,
    ) -> list[tuple[str, dict, float]]: ...

    def count(self, session: Session, store: str) -> int: ...


class NumpyVectorStore:
    name = "numpy"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[np.ndarray, list[dict]]] = {}

    def _load(self, session: Session, store: str) -> tuple[np.ndarray, list[dict]]:
        if store in self._cache:
            return self._cache[store]
        rows = list(session.scalars(select(VectorRecord).where(VectorRecord.store_name == store)).all())
        if not rows:
            empty = (np.zeros((0, settings.embedding_dim)), [])
            self._cache[store] = empty
            return empty
        matrix = np.vstack([np.frombuffer(r.vector, dtype=np.float32) for r in rows]).astype(np.float64)
        payloads = [r.payload_json for r in rows]
        self._cache[store] = (matrix, payloads)
        return self._cache[store]

    def upsert(self, store: str, records: list[dict]) -> int:
        from app.db.base import session_scope

        for rec in records:
            rec.setdefault("payload", {})["ref_id"] = rec["ref_id"]
        with session_scope() as session:
            session.execute(delete(VectorRecord).where(VectorRecord.store_name == store))
            for rec in records:
                vec = np.asarray(rec["vector"], dtype=np.float64).astype(np.float32)
                session.add(
                    VectorRecord(
                        id=new_id("vec"),
                        store_name=store,
                        ref_id=rec["ref_id"],
                        ref_type=rec.get("ref_type", "chunk"),
                        dim=int(vec.shape[0]),
                        vector=vec.tobytes(),
                        payload_json=rec.get("payload", {}),
                    )
                )
        self._cache.pop(store, None)
        return len(records)

    def search(
        self,
        session: Session,
        store: str,
        query: np.ndarray,
        top_k: int,
        predicate: Callable[[dict], bool] | None = None,
    ) -> list[tuple[str, dict, float]]:
        matrix, payloads = self._load(session, store)
        if matrix.shape[0] == 0:
            return []
        sims = matrix @ query.astype(np.float64)
        order = np.argsort(-sims)
        out: list[tuple[str, dict, float]] = []
        for idx in order:
            payload = payloads[int(idx)]
            if predicate and not predicate(payload):
                continue
            out.append((payload.get("ref_id") or payload.get("chunk_id") or "", payload,
                        float(sims[int(idx)])))
            if len(out) >= top_k:
                break
        return out

    def count(self, session: Session, store: str) -> int:
        return self._load(session, store)[0].shape[0]


class PgVectorStore:
    name = "pgvector"

    TABLE = "vector_index_pg"

    def __init__(self) -> None:
        from pgvector.sqlalchemy import Vector  # noqa: F401  (import check)

        self._vector_type = Vector

    def _ensure(self, session: Session) -> None:
        dim = settings.embedding_dim
        session.execute(
            __import__("sqlalchemy").text(
                f"CREATE TABLE IF NOT EXISTS {self.TABLE} ("
                " id TEXT PRIMARY KEY, store TEXT NOT NULL, ref_id TEXT NOT NULL,"
                f" payload JSONB NOT NULL DEFAULT '{{}}', embedding vector({dim}) NOT NULL)"
            )
        )
        session.execute(
            __import__("sqlalchemy").text(f"CREATE INDEX IF NOT EXISTS ix_{self.TABLE}_store ON {self.TABLE}(store)")
        )

    def upsert(self, store: str, records: list[dict]) -> int:
        from sqlalchemy import text

        from app.db.base import session_scope

        with session_scope() as session:
            self._ensure(session)
            session.execute(text(f"DELETE FROM {self.TABLE} WHERE store = :s"), {"s": store})
            for rec in records:
                session.execute(
                    text(
                        f"INSERT INTO {self.TABLE} (id, store, ref_id, payload, embedding) "
                        "VALUES (:id, :store, :ref, CAST(:payload AS jsonb), :emb)"
                    ),
                    {
                        "id": new_id("vec"),
                        "store": store,
                        "ref": rec["ref_id"],
                        "payload": json.dumps(rec.get("payload", {})),
                        "emb": str([float(x) for x in rec["vector"]]),
                    },
                )
        return len(records)

    def search(self, session, store, query, top_k, predicate=None):
        from sqlalchemy import text

        self._ensure(session)
        rows = session.execute(
            text(
                f"SELECT ref_id, payload, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM {self.TABLE} "
                "WHERE store = :s ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
            ),
            {"q": str([float(x) for x in query]), "s": store, "k": max(top_k * 4, 20)},
        ).all()
        out = []
        for ref_id, payload, sim in rows:
            payload = payload if isinstance(payload, dict) else json.loads(payload)
            if predicate and not predicate(payload):
                continue
            out.append((ref_id, payload, float(sim)))
            if len(out) >= top_k:
                break
        return out

    def count(self, session, store: str) -> int:
        from sqlalchemy import text

        self._ensure(session)
        return int(session.execute(text(f"SELECT COUNT(*) FROM {self.TABLE} WHERE store = :s"), {"s": store}).scalar() or 0)


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is not None:
        return _store
    if settings.effective_vector_store == "pgvector":
        try:
            _store = PgVectorStore()
            return _store
        except Exception as exc:  # pragma: no cover
            log.warning("pgvector_unavailable_falling_back_to_numpy", error=str(exc))
    _store = NumpyVectorStore()
    return _store


def reset_store_cache() -> None:
    global _store
    _store = None
