"""Document ingestion: parse → chunk → enrich → embed → index.

Provenance rules enforced here:
  * every chunk carries document_id, page, section and (when a layout sidecar
    exists) a bounding box measured in PDF points;
  * PDF text is re-extracted with pypdf and each layout block is *verified*
    against it; unverified blocks are flagged, never silently trusted;
  * requirement blocks additionally become structured ``Requirement`` rows so
    deterministic rule checks can run against them.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import CorruptFileError, DrawingNotFoundError
from app.core.ids import stable_id, utcnow
from app.core.logging import Timer, get_logger
from app.db.models import Component, Document, DocumentChunk, Requirement
from app.services.rag.embeddings import get_embedding_provider, tokenize
from app.services.rag.vector_store import get_vector_store

log = get_logger(__name__)

CHUNK_STORE = "chunks"
_REV_RE = re.compile(r"\bRev\s+([A-Z])\b")
_MAX_TOKENS = 220


@dataclass
class ChunkData:
    chunk_id: str
    document_id: str
    document_name: str
    document_type: str
    authority: str
    text: str
    page: int = 1
    section: str = ""
    bbox: dict | None = None
    component_ids: list[str] = field(default_factory=list)
    revision: str | None = None
    verified: bool = True
    requirement_code: str | None = None
    rule: dict | None = None

    @property
    def token_count(self) -> int:
        return len(tokenize(self.text))

    def payload(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "document_type": self.document_type,
            "authority": self.authority,
            "page": self.page,
            "section": self.section,
            "bbox": self.bbox,
            "component_ids": self.component_ids,
            "revision": self.revision,
            "verified": self.verified,
            "text": self.text,
        }


def _pdf_page_texts(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise CorruptFileError(f"Could not parse PDF '{path.name}'.") from exc


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _component_mentions(text: str, names: dict[str, str]) -> list[str]:
    low = text.lower()
    return [cid for cid, name in names.items() if name.lower() in low]


def build_chunks(
    slug: str,
    layout: dict,
    pdf_pages: list[str],
    component_names: dict[str, str],
    document_id: str,
) -> list[ChunkData]:
    doc_meta = layout.get("metadata", {})
    applies = doc_meta.get("applies_to", [])
    doc_type = layout.get("document_type", "specification")
    authority = layout.get("authority", "synthetic")
    doc_rev = layout.get("doc_revision", "") or None

    chunks: list[ChunkData] = []
    pending: list[dict] = []
    heading = ""

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        text = " ".join(b["text"] for b in pending)
        first = pending[0]
        if heading and not text.startswith(heading):
            text = f"{heading} — {text}"
        chunks.append(
            _make_chunk(
                slug, layout, document_id, doc_type, authority, text,
                page=first["page"], section=first.get("section", ""),
                bbox=first.get("bbox"), applies=applies, component_names=component_names,
                doc_rev=doc_rev, verified=all(b.get("verified", True) for b in pending),
            )
        )
        pending = []

    for block in layout.get("blocks", []):
        kind = block.get("kind")
        verified = _norm(block["text"][:60]) in _norm(
            pdf_pages[block["page"] - 1] if 0 < block["page"] <= len(pdf_pages) else ""
        )
        block = {**block, "verified": verified}
        if kind in ("heading",):
            flush()
            if block.get("section"):
                heading = block["text"]
            continue
        if kind == "requirement":
            flush()
            chunks.append(
                _make_chunk(
                    slug, layout, document_id, doc_type, authority,
                    (f"{heading} — {block['text']}" if heading and not block["text"].startswith(heading)
                     else block["text"]),
                    page=block["page"], section=block.get("section", ""), bbox=block.get("bbox"),
                    applies=applies, component_names=component_names, doc_rev=doc_rev,
                    verified=verified, requirement_code=block.get("code"), rule=block.get("rule"),
                )
            )
            continue
        if kind in ("table", "table_row", "table_body"):
            pending.append(block)
            if len(tokenize(" ".join(b["text"] for b in pending))) > _MAX_TOKENS:
                flush()
            continue
        # paragraph
        if pending and _norm(pending[-1].get("section", "")) != _norm(block.get("section", "")):
            flush()
        pending.append(block)
        if len(tokenize(" ".join(b["text"] for b in pending))) > _MAX_TOKENS:
            flush()
    flush()
    return chunks


def _make_chunk(
    slug: str,
    layout: dict,
    document_id: str,
    doc_type: str,
    authority: str,
    text: str,
    *,
    page: int,
    section: str,
    bbox: list | dict | None,
    applies: list[str],
    component_names: dict[str, str],
    doc_rev: str | None,
    verified: bool,
    requirement_code: str | None = None,
    rule: dict | None = None,
) -> ChunkData:
    m = _REV_RE.search(text)
    if m:
        revision = f"Rev {m.group(1)}"
    elif doc_type == "revision_note" and doc_rev:
        revision = doc_rev if str(doc_rev).startswith("Rev") else f"Rev {doc_rev}"
    else:
        revision = None
    comps = list(applies) + [c for c in _component_mentions(text, component_names) if c not in applies]
    bbox_dict = {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3], "unit": "pdf_pt"} if bbox else None
    return ChunkData(
        chunk_id=stable_id("chk", slug, page, section, hashlib.sha1(text.encode()).hexdigest()[:10]),
        document_id=document_id,
        document_name=layout.get("title", slug),
        document_type=doc_type,
        authority=authority,
        text=text,
        page=page,
        section=section,
        bbox=bbox_dict,
        component_ids=comps[:8],
        revision=revision,
        verified=verified,
        requirement_code=requirement_code,
        rule=rule,
    )


def ingest_document(session: Session, slug: str, project_id: str | None) -> dict:
    layout_path = settings.documents_dir / f"{slug}.layout.json"
    pdf_path = settings.documents_dir / f"{slug}.pdf"
    if not layout_path.exists():
        raise DrawingNotFoundError(f"No layout sidecar for document '{slug}'.")
    layout = json.loads(layout_path.read_text())
    pdf_pages = _pdf_page_texts(pdf_path) if pdf_path.exists() else []

    component_names = {
        c.id: c.name for c in session.scalars(select(Component)).all()
    } or {}
    document_id = stable_id("doc", slug)

    # idempotent re-ingest
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    session.execute(delete(Requirement).where(Requirement.document_id == document_id))
    existing = session.get(Document, document_id)
    if existing:
        session.delete(existing)
        session.flush()

    doc = Document(
        id=document_id,
        project_id=project_id,
        title=layout.get("title", slug),
        document_type=layout.get("document_type", "specification"),
        source=f"data/documents/{slug}.pdf",
        doc_revision=layout.get("doc_revision", ""),
        path=str(pdf_path.relative_to(settings.documents_dir.parent)) if pdf_path.exists() else "",
        checksum=hashlib.sha256(pdf_path.read_bytes()).hexdigest() if pdf_path.exists() else "",
        authority=layout.get("authority", "synthetic"),
        pages=layout.get("pages", len(pdf_pages) or 1),
        metadata_json=layout.get("metadata", {}),
    )
    session.add(doc)

    with Timer() as t_chunk:
        chunks = build_chunks(slug, layout, pdf_pages, component_names, document_id)
    for i, ch in enumerate(chunks):
        session.add(
            DocumentChunk(
                id=ch.chunk_id,
                document_id=document_id,
                chunk_index=i,
                text=ch.text,
                page=ch.page,
                section=ch.section,
                document_type=ch.document_type,
                component_id=ch.component_ids[0] if ch.component_ids else None,
                revision_id=None,
                bbox_json=ch.bbox,
                token_count=ch.token_count,
                content_hash=hashlib.sha256(ch.text.encode()).hexdigest(),
                metadata_json={
                    "component_ids": ch.component_ids,
                    "authority": ch.authority,
                    "verified_against_pdf": ch.verified,
                    "requirement_code": ch.requirement_code,
                    "rule": ch.rule,
                    "revision": ch.revision,
                },
            )
        )
        if ch.requirement_code:
            session.add(
                Requirement(
                    id=stable_id("req", slug, ch.requirement_code),
                    document_id=document_id,
                    project_id=project_id,
                    code=ch.requirement_code,
                    title=ch.text.split("—")[0].strip()[:200],
                    section=ch.section,
                    page=ch.page,
                    text=ch.text,
                    requirement_type="design",
                    applies_to_json=ch.component_ids,
                    metadata_json={"rule": ch.rule or {}, "authority": ch.authority},
                )
            )
    session.flush()

    session.commit()  # release the write txn before the vector store opens its own
    reindex_stats = reindex_all(session)

    unverified = sum(1 for c in chunks if not c.verified)
    log.info(
        "document_ingested", slug=slug, chunks=len(chunks), pages=doc.pages,
        unverified_blocks=unverified, chunk_ms=t_chunk.ms, provider=reindex_stats["provider"],
    )
    return {
        "document_id": document_id,
        "slug": slug,
        "chunks": len(chunks),
        "pages": doc.pages,
        "unverified_blocks": unverified,
        "requirements": sum(1 for c in chunks if c.requirement_code),
        "embedding_provider": reindex_stats["provider"],
        "index_size": reindex_stats["indexed"],
    }


def reindex_all(session: Session) -> dict:
    """Rebuild the whole vector index from the DocumentChunk rows visible in
    ``session`` (flushed rows included), so ingest → index stays atomic."""
    rows = list(session.scalars(select(DocumentChunk)).all())
    provider = get_embedding_provider()
    texts = [r.text for r in rows]
    vectors = provider.embed_documents(texts) if texts else None
    records = []
    for i, r in enumerate(rows):
        meta = r.metadata_json or {}
        records.append(
            {
                "ref_id": r.id,
                "ref_type": "chunk",
                "vector": vectors[i],
                "payload": {
                    "chunk_id": r.id,
                    "document_id": r.document_id,
                    "document_name": meta.get("document_name", ""),
                    "document_type": r.document_type or "",
                    "authority": meta.get("authority", "synthetic"),
                    "page": r.page,
                    "section": r.section,
                    "bbox": r.bbox_json,
                    "component_ids": meta.get("component_ids", []),
                    "revision": meta.get("revision"),
                    "verified": meta.get("verified_against_pdf", True),
                    "text": r.text,
                },
            }
        )
    n = get_vector_store().upsert(CHUNK_STORE, records)
    return {"indexed": n, "provider": provider.name, "chunks": len(rows)}


def ingest_all(session: Session, project_id: str | None) -> list[dict]:
    slugs = sorted(p.name.replace(".layout.json", "") for p in settings.documents_dir.glob("*.layout.json"))
    return [ingest_document(session, slug, project_id) for slug in slugs]
