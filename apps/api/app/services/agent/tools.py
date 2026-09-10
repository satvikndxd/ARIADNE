"""Agent tool registry.

One registry, two transports: the in-process gateway executes these handlers
directly; the TypeScript MCP server exposes the same twelve tools over the
wire and calls back into the REST API (which runs the same services).  Every
tool has a typed input schema, a permission and a mutating flag consumed by
``core.security.TOOL_POLICY``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ToolArgumentError
from app.core.security import Principal, Permission
from app.db.models import Component, ComponentRevision, Finding, Project, Requirement, Revision
from app.schemas.domain import ComponentOut, DependencyGraphOut, FindingCreate, FindingOut, ProjectOut, RevisionOut
from app.schemas.rag import RetrievalFilters, SearchRequest
from app.services import findings as findings_svc
from app.services.analysis.revision_analyzer import get_revision_analyzer
from app.services.graph import get_graph_store
from app.services.rag import retriever


class ProjectIdArgs(BaseModel):
    project_id: str


class RevisionIdArgs(BaseModel):
    revision_id: str


class CompareArgs(BaseModel):
    revision_a: str
    revision_b: str


class ComponentArgs(BaseModel):
    component_id: str
    revision_id: str | None = None


class DependencyArgs(BaseModel):
    component_id: str
    depth: int = Field(default=2, ge=1, le=4)


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    project_id: str | None = None
    component_ids: list[str] = Field(default_factory=list)
    revision: str | None = None
    top_k: int = Field(default=6, ge=1, le=20)


class RequirementArgs(BaseModel):
    requirement_id: str


class HistoryArgs(BaseModel):
    component_id: str


class FindingsArgs(BaseModel):
    project_id: str
    status: str | None = None


class CreateFindingArgs(BaseModel):
    finding: FindingCreate


class UpdateStatusArgs(BaseModel):
    finding_id: str
    status: str
    note: str = ""


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    permission: Permission
    mutating: bool
    handler: Callable[..., dict[str, Any]]

    def input_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def validate(self, raw: dict[str, Any]) -> BaseModel:
        try:
            return self.args_model(**raw)
        except ValidationError as exc:
            raise ToolArgumentError(f"Invalid arguments for tool '{self.name}'.",
                                    detail=exc.errors(include_url=False)) from exc


# --------------------------------------------------------------------------- #
# Handlers (session, args, principal) -> JSON-able dict
# --------------------------------------------------------------------------- #
def h_get_project(session: Session, a: ProjectIdArgs, _p: Principal) -> dict:
    proj = session.get(Project, a.project_id)
    if proj is None:
        raise NotFoundError(f"Project '{a.project_id}' not found.")
    out = ProjectOut.model_validate(proj).model_dump()
    out["stats"] = {
        "revisions": len(session.scalars(select(Revision).where(Revision.project_id == proj.id)).all()),
        "components": len(session.scalars(select(Component).where(Component.project_id == proj.id)).all()),
        "findings": len(session.scalars(select(Finding).where(Finding.project_id == proj.id)).all()),
    }
    return out


def h_get_revision(session: Session, a: RevisionIdArgs, _p: Principal) -> dict:
    rev = session.get(Revision, a.revision_id)
    if rev is None:
        raise NotFoundError(f"Revision '{a.revision_id}' not found.")
    return RevisionOut.model_validate(rev).model_dump(mode="json")


def h_compare_revisions(session: Session, a: CompareArgs, _p: Principal) -> dict:
    rev_a, rev_b = session.get(Revision, a.revision_a), session.get(Revision, a.revision_b)
    if rev_a is None or rev_b is None:
        raise NotFoundError("One of the revisions was not found.")
    out = get_revision_analyzer().analyze(session, rev_a, rev_b)
    return {
        "revision_a": rev_a.name,
        "revision_b": rev_b.name,
        "method": out.method,
        "alignment": out.alignment,
        "changes": [
            {
                "change_type": c.change_type.value,
                "component_id": c.component_id,
                "title": c.title,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "unit": c.unit,
                "numeric_delta": c.numeric_delta,
                "location": c.location.model_dump(),
                "confidence": c.confidence,
                "detection_method": c.detection_method.value,
                "semantic": c.semantic,
            }
            for c in out.changes
        ],
    }


def h_get_component(session: Session, a: ComponentArgs, _p: Principal) -> dict:
    comp = session.get(Component, a.component_id)
    if comp is None:
        raise NotFoundError(f"Component '{a.component_id}' not found.")
    out = ComponentOut.model_validate(comp).model_dump()
    out["finding_count"] = len(
        session.scalars(select(Finding).where(Finding.component_id == comp.id)).all()
    )
    return out


def h_get_component_properties(session: Session, a: ComponentArgs, _p: Principal) -> dict:
    comp = session.get(Component, a.component_id)
    if comp is None:
        raise NotFoundError(f"Component '{a.component_id}' not found.")
    stmt = select(ComponentRevision).where(ComponentRevision.component_id == comp.id)
    if a.revision_id:
        stmt = stmt.where(ComponentRevision.revision_id == a.revision_id)
    rows = session.scalars(stmt).all()
    if not rows:
        raise NotFoundError(f"No property snapshot for component '{a.component_id}'.")
    return {
        "component_id": comp.id,
        "name": comp.name,
        "snapshots": [
            {"revision_id": r.revision_id, "changed_from_parent": r.changed_from_parent,
             "properties": r.properties_json}
            for r in rows
        ],
    }


def h_get_dependencies(session: Session, a: DependencyArgs, _p: Principal) -> dict:
    view = get_graph_store().graph_view(session, a.component_id, a.depth)
    return view.model_dump()


def h_search_requirements(session: Session, a: SearchArgs, _p: Principal) -> dict:
    req = SearchRequest(
        query=a.query, project_id=a.project_id, top_k=a.top_k, rerank_top_n=min(a.top_k, 5),
        strategy="revision_aware",
        filters=RetrievalFilters(project_id=a.project_id, component_ids=a.component_ids, revision=a.revision),
    )
    resp = retriever.search(session, req)
    return {
        "strategy": resp.strategy,
        "latency_ms": resp.latency_ms,
        "empty": resp.empty,
        "results": [
            {
                "document": r.document_name, "section": r.section, "page": r.page,
                "text": r.excerpt, "score": r.score, "chunk_id": r.chunk_id,
                "document_id": r.document_id, "authority": r.authority,
                "quarantined": bool(getattr(r, "quarantined", False)),
            }
            for r in resp.results
        ],
    }


def h_get_requirement(session: Session, a: RequirementArgs, _p: Principal) -> dict:
    req = session.get(Requirement, a.requirement_id)
    if req is None:
        req = session.scalars(select(Requirement).where(Requirement.code == a.requirement_id)).first()
    if req is None:
        raise NotFoundError(f"Requirement '{a.requirement_id}' not found.")
    return {
        "id": req.id, "code": req.code, "title": req.title, "section": req.section, "page": req.page,
        "text": req.text, "applies_to": req.applies_to_json,
        "rule": (req.metadata_json or {}).get("rule"),
        "document_id": req.document_id,
    }


def h_get_revision_history(session: Session, a: HistoryArgs, _p: Principal) -> dict:
    rows = session.scalars(
        select(ComponentRevision).where(ComponentRevision.component_id == a.component_id)
    ).all()
    ordered = sorted(rows, key=lambda r: r.revision_id)
    deltas = []
    for prev, cur in zip(ordered, ordered[1:]):
        changed = {
            k: {"old": prev.properties_json.get(k), "new": cur.properties_json.get(k)}
            for k in set(prev.properties_json) | set(cur.properties_json)
            if prev.properties_json.get(k) != cur.properties_json.get(k)
        }
        deltas.append({"revision_id": cur.revision_id, "changed_properties": changed})
    return {"component_id": a.component_id, "snapshots": len(ordered), "deltas": deltas}


def h_get_findings(session: Session, a: FindingsArgs, _p: Principal) -> dict:
    stmt = select(Finding).where(Finding.project_id == a.project_id)
    if a.status:
        stmt = stmt.where(Finding.status == a.status)
    rows = session.scalars(stmt).all()
    return {"count": len(rows), "findings": [findings_svc.to_out(session, f).model_dump(mode="json") for f in rows]}


def h_create_review_finding(session: Session, a: CreateFindingArgs, principal: Principal) -> dict:
    finding = findings_svc.create_finding(session, a.finding, principal, source=a.finding.source or "agent")
    return findings_svc.to_out(session, finding).model_dump(mode="json")


def h_update_finding_status(session: Session, a: UpdateStatusArgs, principal: Principal) -> dict:
    finding = findings_svc.update_status(session, a.finding_id, a.status, principal, note=a.note)
    return findings_svc.to_out(session, finding).model_dump(mode="json")


# --------------------------------------------------------------------------- #
TOOLS: list[ToolSpec] = [
    ToolSpec("get_project", "Return project metadata plus revision/component/finding counts.",
             ProjectIdArgs, Permission.READ_PROJECT_DATA, False, h_get_project),
    ToolSpec("get_revision", "Return a single revision with its drawings.",
             RevisionIdArgs, Permission.READ_PROJECT_DATA, False, h_get_revision),
    ToolSpec("compare_revisions", "Deterministically compare two revisions: aligned image diff plus "
             "structured change list with locations and confidences.",
             CompareArgs, Permission.READ_PROJECT_DATA, False, h_compare_revisions),
    ToolSpec("get_component", "Return component master data (material, mass, subsystem).",
             ComponentArgs, Permission.READ_PROJECT_DATA, False, h_get_component),
    ToolSpec("get_component_properties", "Return per-revision property snapshots of a component.",
             ComponentArgs, Permission.READ_PROJECT_DATA, False, h_get_component_properties),
    ToolSpec("get_dependencies", "Traverse the dependency graph from a component (upstream + downstream).",
             DependencyArgs, Permission.READ_PROJECT_DATA, False, h_get_dependencies),
    ToolSpec("search_requirements", "Revision-aware retrieval over the standards/specification corpus with "
             "provenance (document, section, page, bbox).",
             SearchArgs, Permission.SEARCH_KNOWLEDGE, False, h_search_requirements),
    ToolSpec("get_requirement", "Return one requirement by id or code, including its machine-readable rule.",
             RequirementArgs, Permission.SEARCH_KNOWLEDGE, False, h_get_requirement),
    ToolSpec("get_revision_history", "Return property deltas of a component across revisions.",
             HistoryArgs, Permission.READ_PROJECT_DATA, False, h_get_revision_history),
    ToolSpec("get_findings", "List findings of a project, optionally filtered by status.",
             FindingsArgs, Permission.READ_PROJECT_DATA, False, h_get_findings),
    ToolSpec("create_review_finding", "Create a review finding. MUTATING: requires an approved human "
             "confirmation; authorization and confirmation are enforced server-side.",
             CreateFindingArgs, Permission.CREATE_FINDING, True, h_create_review_finding),
    ToolSpec("update_finding_status", "Accept/reject/resolve a finding. MUTATING: reviewer role required.",
             UpdateStatusArgs, Permission.UPDATE_FINDING, True, h_update_finding_status),
]

TOOL_BY_NAME = {t.name: t for t in TOOLS}
