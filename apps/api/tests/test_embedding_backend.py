"""Embedding backend resolution is explicit and never silent."""
from __future__ import annotations

from app.services.rag.embeddings import HashingEmbeddings, embedding_backend_report, get_embedding_provider


def test_report_structure():
    rep = embedding_backend_report()
    assert {"provider", "semantic", "reason", "model"} <= set(rep)
    assert isinstance(rep["semantic"], bool)
    assert rep["semantic"] == (rep["provider"] != "hashing")


def test_provider_protocol():
    prov = get_embedding_provider()
    vec = prov.embed_query("radial clearance for M10 fasteners")
    assert vec.shape == (prov.dim,)
    docs = prov.embed_documents(["a", "b"])
    assert docs.shape == (2, prov.dim)
    if isinstance(prov, HashingEmbeddings):
        # lexical fallback is deterministic
        assert (prov.embed_query("x y") == prov.embed_query("x y")).all()
