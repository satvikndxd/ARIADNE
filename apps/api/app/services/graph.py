"""Knowledge-graph abstraction over engineering dependencies.

Two backends behind one protocol:

* ``SqlGraphStore``  — default; BFS over the ``dependencies`` table.  Works on
  SQLite and PostgreSQL with zero extra infrastructure.
* ``Neo4jGraphStore`` — used automatically when ``NEO4J_URI`` is configured and
  the ``neo4j`` driver is importable.  Falls back to SQL otherwise (the choice
  is *recorded* in the response payload, never silent).

Traversal is deterministic Python: the LLM never walks the graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Component, Dependency, Requirement
from app.schemas.common import RelationshipType
from app.schemas.domain import DependencyEdge, DependencyGraphOut, GraphNode

_UP = "upstream"
_DOWN = "downstream"

# Relationship types that imply "the target constrains / informs the source".
_SPEC_TYPES = {RelationshipType.GOVERNED_BY.value, RelationshipType.REFERENCES.value}


@dataclass
class TraversalHit:
    component_id: str
    direction: str
    hops: int
    path: list[str] = field(default_factory=list)
    via_type: str = ""


class GraphStore(Protocol):
    name: str

    def traverse(self, session: Session, root_id: str, depth: int) -> list[TraversalHit]: ...

    def graph_view(self, session: Session, root_id: str, depth: int) -> DependencyGraphOut: ...


class SqlGraphStore:
    name = "sql"

    def _edges(self, session: Session, project_id: str | None = None) -> list[Dependency]:
        stmt = select(Dependency)
        if project_id:
            stmt = stmt.where(Dependency.project_id == project_id)
        return list(session.scalars(stmt).all())

    def traverse(self, session: Session, root_id: str, depth: int) -> list[TraversalHit]:
        depth = max(0, min(depth, settings.graph_max_depth))
        edges = self._edges(session)
        down: dict[str, list[Dependency]] = {}
        up: dict[str, list[Dependency]] = {}
        for e in edges:
            down.setdefault(e.source_component_id, []).append(e)
            up.setdefault(e.target_component_id, []).append(e)

        hits: dict[str, TraversalHit] = {}

        def walk(node: str, direction: str, hops: int, path: list[str]) -> None:
            if hops > depth:
                return
            adjacency = down if direction == _DOWN else up
            for edge in adjacency.get(node, []):
                nxt = edge.target_component_id if direction == _DOWN else edge.source_component_id
                new_path = path + [f"{edge.relationship_type}:{nxt}"]
                prev = hits.get(nxt)
                if prev is None or prev.hops > hops:
                    hits[nxt] = TraversalHit(nxt, direction, hops, new_path, edge.relationship_type)
                if nxt not in path:
                    walk(nxt, direction, hops + 1, new_path)

        walk(root_id, _DOWN, 1, [root_id])
        walk(root_id, _UP, 1, [root_id])
        return sorted(hits.values(), key=lambda h: (h.hops, h.component_id))

    def graph_view(self, session: Session, root_id: str, depth: int) -> DependencyGraphOut:
        hits = self.traverse(session, root_id, depth)
        comp = session.get(Component, root_id)
        involved = {root_id} | {h.component_id for h in hits}
        edges = [
            DependencyEdge(
                id=e.id,
                source_component_id=e.source_component_id,
                target_component_id=e.target_component_id,
                relationship_type=e.relationship_type,
                description=e.description,
                criticality=e.criticality,
            )
            for e in self._edges(session, comp.project_id if comp else None)
            if e.source_component_id in involved and e.target_component_id in involved
        ]
        comps = {c.id: c for c in session.scalars(select(Component).where(Component.id.in_(involved))).all()}
        nodes: list[GraphNode] = []
        for cid in involved:
            c = comps.get(cid)
            direction = "root" if cid == root_id else next(
                (h.direction for h in hits if h.component_id == cid), "downstream"
            )
            nodes.append(
                GraphNode(
                    id=cid,
                    label=c.name if c else cid,
                    type=c.type if c else "component",
                    subsystem=c.subsystem if c else "",
                    material=c.material if c else "",
                    depth=0 if cid == root_id else next(h.hops for h in hits if h.component_id == cid),
                    direction=direction if direction in ("root", "upstream", "downstream") else "downstream",
                    metadata={"criticality": "normal"},
                )
            )
        # specification nodes derived from requirement applicability
        spec_nodes = [r.code or r.title for r in specifications_for_component(session, root_id)]
        return DependencyGraphOut(
            root_component_id=root_id,
            depth=depth,
            nodes=nodes,
            edges=edges,
            upstream=[h.component_id for h in hits if h.direction == _UP],
            downstream=[h.component_id for h in hits if h.direction == _DOWN],
            specifications=spec_nodes,
            store=self.name,
        )


class Neo4jGraphStore:
    """Optional backend.  Only instantiated when configured *and* importable."""

    name = "neo4j"

    def __init__(self) -> None:
        from neo4j import GraphDatabase  # deferred import

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )

    def traverse(self, session: Session, root_id: str, depth: int) -> list[TraversalHit]:
        depth = max(0, min(depth, settings.graph_max_depth))
        query = """
        MATCH p = (root:Component {uid: $root})-[r:DEPENDS_ON|USES|MATES_WITH|PART_OF|ASSEMBLED_INTO*1..%d]-(other:Component)
        RETURN other.uid AS uid, length(p) AS hops, [rel IN relationships(p) | type(rel)] AS types,
               [n IN nodes(p) | n.uid] AS path
        """ % depth
        hits: dict[str, TraversalHit] = {}
        with self._driver.session() as s:
            for rec in s.run(query, root=root_id):
                cid, hops, types, path = rec["uid"], rec["hops"], rec["types"], rec["path"]
                root_pos = path.index(root_id)
                direction = _DOWN if path[-1] == cid or root_pos == 0 else _UP
                hits.setdefault(
                    cid, TraversalHit(cid, direction, hops, [f"{t}:{n}" for t, n in zip(types, path[1:])])
                )
        return sorted(hits.values(), key=lambda h: (h.hops, h.component_id))

    def graph_view(self, session: Session, root_id: str, depth: int) -> DependencyGraphOut:
        view = SqlGraphStore().graph_view(session, root_id, depth)
        view.store = self.name
        return view

    def close(self) -> None:
        self._driver.close()


_store: GraphStore | None = None


def get_graph_store() -> GraphStore:
    global _store
    if _store is not None:
        return _store
    if settings.effective_graph_store == "neo4j":
        try:
            _store = Neo4jGraphStore()
            return _store
        except Exception as exc:  # pragma: no cover - depends on infra
            from app.core.logging import get_logger

            get_logger(__name__).warning("neo4j_unavailable_falling_back_to_sql", error=str(exc))
    _store = SqlGraphStore()
    return _store


def specifications_for_component(session: Session, component_id: str) -> list[Requirement]:
    """Requirements whose ``applies_to`` includes the component (deterministic)."""
    reqs = list(session.scalars(select(Requirement)).all())
    return [r for r in reqs if component_id in (r.applies_to_json or [])]
