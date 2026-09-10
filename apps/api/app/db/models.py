"""ARIADNE relational schema.

Design notes
------------
* Portable column types only (``sa.JSON``, ``sa.LargeBinary``) so the *same*
  models run on SQLite (zero-infra dev) and PostgreSQL (docker compose).
* ``VectorRecord`` backs the numpy vector store; the pgvector store keeps its
  vectors in a dedicated table created at runtime (``services/rag/vector_store``).
* Every AI-derived artefact (change, evidence, finding, tool call) carries
  provenance columns so the audit trail can answer *"why did the system say
  that?"* without re-running the model.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import utcnow
from app.db.base import Base


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(16), default="VIEWER")
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Project structure
# --------------------------------------------------------------------------- #
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    code: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    active_revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revisions: Mapped[list["Revision"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    components: Mapped[list["Component"]] = relationship(back_populates="project")
    documents: Mapped[list["Document"]] = relationship(back_populates="project")


class Revision(Base):
    __tablename__ = "revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(32), index=True)  # "Rev A"
    label: Mapped[str] = mapped_column(String(64), default="")  # "A"
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="released")
    parent_revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    released_by: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="revisions")
    drawings: Mapped[list["Drawing"]] = relationship(back_populates="revision", cascade="all, delete-orphan")


class Drawing(Base):
    __tablename__ = "drawings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512))
    drawing_type: Mapped[str] = mapped_column(String(64), default="part")  # part | assembly | schematic
    sheet: Mapped[str] = mapped_column(String(32), default="1/1")
    width_px: Mapped[int] = mapped_column(Integer, default=0)
    height_px: Mapped[int] = mapped_column(Integer, default=0)
    manifest_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision: Mapped[Revision] = relationship(back_populates="drawings")


class Component(Base):
    __tablename__ = "components"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    code: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(64), default="part")
    subsystem: Mapped[str] = mapped_column(String(64), default="")
    material: Mapped[str] = mapped_column(String(120), default="")
    weight_g: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="components")
    revisions: Mapped[list["ComponentRevision"]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )


class ComponentRevision(Base):
    """Snapshot of a component's engineering properties at one revision."""

    __tablename__ = "component_revisions"
    __table_args__ = (UniqueConstraint("component_id", "revision_id", name="uq_component_revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"), index=True)
    properties_json: Mapped[dict] = mapped_column(JSON, default=dict)
    changed_from_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    component: Mapped[Component] = relationship(back_populates="revisions")


class Dependency(Base):
    """Directed engineering relationship: source ──relationship──▶ target."""

    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint("source_component_id", "target_component_id", "relationship_type", name="uq_dep"),
        Index("ix_dep_target", "target_component_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_component_id: Mapped[str] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    target_component_id: Mapped[str] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    relationship_type: Mapped[str] = mapped_column(String(48))  # DEPENDS_ON | USES | MATES_WITH | PART_OF ...
    description: Mapped[str] = mapped_column(Text, default="")
    criticality: Mapped[str] = mapped_column(String(16), default="normal")  # normal | critical
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# Knowledge
# --------------------------------------------------------------------------- #
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    document_type: Mapped[str] = mapped_column(String(64), default="specification")
    source: Mapped[str] = mapped_column(String(300), default="")
    doc_revision: Mapped[str] = mapped_column(String(32), default="")
    path: Mapped[str] = mapped_column(String(512), default="")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    authority: Mapped[str] = mapped_column(String(64), default="synthetic")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project | None] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    """Retrieval unit.  Provenance is mandatory — no chunk without a source."""

    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_chunk_doc_component", "document_id", "component_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(64), default="")
    document_type: Mapped[str] = mapped_column(String(64), default="")
    component_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), default="", index=True)  # e.g. FS-4.2
    title: Mapped[str] = mapped_column(String(300), default="")
    section: Mapped[str] = mapped_column(String(64), default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, default="")
    requirement_type: Mapped[str] = mapped_column(String(48), default="design")
    applies_to_json: Mapped[list] = mapped_column(JSON, default=list)  # component ids
    normative: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped[Document | None] = relationship(back_populates="requirements")


class VectorRecord(Base):
    """Persistence for the numpy-backed vector store (store_name namespaces it)."""

    __tablename__ = "vector_records"
    __table_args__ = (Index("ix_vector_store_ref", "store_name", "ref_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_name: Mapped[str] = mapped_column(String(64), default="default", index=True)
    ref_id: Mapped[str] = mapped_column(String(64), index=True)
    ref_type: Mapped[str] = mapped_column(String(32), default="chunk")
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    revision_a_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_b_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(16), default="demo")  # demo | live
    requested_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)

    changes: Mapped[list["Change"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    events: Mapped[list["AnalysisEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AnalysisEvent.seq"
    )
    tool_executions: Mapped[list["ToolExecution"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class AnalysisEvent(Base):
    """Progress stream consumed by the UI (stage 1…9 of the pipeline)."""

    __tablename__ = "analysis_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(400), default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[AnalysisRun] = relationship(back_populates="events")


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (Index("ix_change_run_component", "analysis_run_id", "component_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_a_id: Mapped[str] = mapped_column(String(64))
    revision_b_id: Mapped[str] = mapped_column(String(64))
    component_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    drawing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_type: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    old_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    unit: Mapped[str] = mapped_column(String(24), default="")
    location_json: Mapped[dict] = mapped_column(JSON, default=dict)  # {x,y,width,height,page,sheet}
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="low")  # high | medium | low
    classification: Mapped[str] = mapped_column(String(32), default="cosmetic")  # consequential | cosmetic
    detection_method: Mapped[str] = mapped_column(String(48), default="structured")
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[AnalysisRun] = relationship(back_populates="changes")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chat_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | denied | pending
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transport: Mapped[str] = mapped_column(String(32), default="in-process")  # mcp-http | in-process-fallback
    mutating: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    run: Mapped[AnalysisRun | None] = relationship(back_populates="tool_executions")


class Confirmation(Base):
    """Human-in-the-loop gate for every state-changing action."""

    __tablename__ = "confirmations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    action_label: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|rejected|expired
    requested_by: Mapped[str] = mapped_column(String(64), default="")
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    component_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    change_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | analysis | agent
    created_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    evidence: Mapped[list["FindingEvidence"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="FindingEvidence.id"
    )
    affected_components: Mapped[list["FindingComponent"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), default="document")  # document | drawing | structured
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str] = mapped_column(String(64), default="")
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    finding: Mapped[Finding] = relationship(back_populates="evidence")


class FindingComponent(Base):
    __tablename__ = "finding_components"
    __table_args__ = (UniqueConstraint("finding_id", "component_id", name="uq_finding_component"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="affected")  # affected | root_cause | downstream

    finding: Mapped[Finding] = relationship(back_populates="affected_components")


# --------------------------------------------------------------------------- #
# Conversation
# --------------------------------------------------------------------------- #
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, default="")
    structured_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_calls_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    pending_confirmation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="demo")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


# --------------------------------------------------------------------------- #
# Audit + evaluation
# --------------------------------------------------------------------------- #
class AuditEvent(Base):
    """Append-only trail: who did what, with which tool, arguments and result."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(48), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    analysis_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arguments_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str] = mapped_column(String(64), default="")
    llm_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(16), default="demo")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    report_path: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    metrics: Mapped[list["EvaluationMetric"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EvaluationMetric.id"
    )


class EvaluationMetric(Base):
    __tablename__ = "evaluation_metrics"
    __table_args__ = (Index("ix_eval_metric", "evaluation_run_id", "subset", "metric"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    subset: Mapped[str] = mapped_column(String(64), default="overall")  # baseline_a | baseline_b | proposed
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float, default=0.0)
    n: Mapped[int] = mapped_column(Integer, default=0)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[EvaluationRun] = relationship(back_populates="metrics")
