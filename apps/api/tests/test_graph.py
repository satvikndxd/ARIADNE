from __future__ import annotations

from app.services.graph import get_graph_store


def test_traversal_finds_mates_and_uses(session):
    hits = get_graph_store().traverse(session, "cmp_motor_mount", 2)
    ids = {h.component_id for h in hits}
    assert {"cmp_chassis_interface", "cmp_fastener_m10", "cmp_motor_assembly"} <= ids
    chassis = next(h for h in hits if h.component_id == "cmp_chassis_interface")
    assert chassis.hops == 1 and chassis.via_type == "MATES_WITH"


def test_depth_limit_respected(session):
    shallow = {h.component_id for h in get_graph_store().traverse(session, "cmp_motor_mount", 1)}
    deep = {h.component_id for h in get_graph_store().traverse(session, "cmp_motor_mount", 4)}
    assert shallow <= deep


def test_graph_view_directions(session):
    view = get_graph_store().graph_view(session, "cmp_motor_mount", 2)
    assert view.root_component_id == "cmp_motor_mount"
    assert "cmp_chassis_interface" in view.downstream
    assert view.store in ("sql", "neo4j")
