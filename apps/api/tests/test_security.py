"""Authorization + human-in-the-loop enforcement (server-side, deterministic)."""
from __future__ import annotations

import pytest

from app.core.errors import AuthorizationError
from app.core.security import Permission, Role, authorize, authorize_tool


def test_role_matrix():
    authorize(Role.ENGINEER, Permission.CREATE_FINDING)
    with pytest.raises(AuthorizationError):
        authorize(Role.ENGINEER, Permission.UPDATE_FINDING)
    with pytest.raises(AuthorizationError):
        authorize(Role.VIEWER, Permission.RUN_ANALYSIS)
    authorize(Role.REVIEWER, Permission.UPDATE_FINDING)


def test_tool_policy():
    authorize_tool(Role.VIEWER, "get_dependencies")
    with pytest.raises(AuthorizationError):
        authorize_tool(Role.VIEWER, "create_review_finding")
    with pytest.raises(AuthorizationError):
        authorize_tool(Role.ADMIN, "no_such_tool")


def test_viewer_cannot_start_analysis(viewer_client):
    r = viewer_client.post("/analysis", json={"project_id": "proj_t", "revision_a": "rev_a", "revision_b": "rev_b"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "authorization_error"


def test_mutating_tool_requires_confirmation(client):
    r = client.post("/mcp-bridge/tools/create_review_finding/execute",
                    json={"args": {"finding": {"project_id": "proj_t", "title": "no confirmation"}},
                          "context": {"user_id": "u_engineer_1"}})
    assert r.status_code == 409
    assert r.json()["error_code"] == "confirmation_required"


def test_full_confirmation_flow(client, reviewer_client):
    chat = client.post("/chat", json={"message": "Create a review finding for the clearance conflict.",
                                      "project_id": "proj_t", "revision_a": "rev_a", "revision_b": "rev_b",
                                      "component_id": "cmp_motor_mount"})
    assert chat.status_code == 200, chat.text
    pending = chat.json()["pending_action"]
    assert pending is not None and pending["tool_name"] == "create_review_finding"

    before = len(client.get("/findings", params={"project_id": "proj_t"}).json())
    dec = reviewer_client.post(f"/confirmations/{pending['confirmation_id']}/decision", json={"approved": True})
    assert dec.status_code == 200, dec.text
    after = client.get("/findings", params={"project_id": "proj_t"}).json()
    assert len(after) == before + 1
    assert after[0]["source"] in ("agent", "manual")
    assert len(after[0]["evidence"]) >= 1


def test_rejection_creates_nothing(client, reviewer_client):
    chat = client.post("/chat", json={"message": "Create a review finding for the tolerance change.",
                                      "project_id": "proj_t", "component_id": "cmp_motor_mount"})
    pending = chat.json()["pending_action"]
    before = len(client.get("/findings", params={"project_id": "proj_t"}).json())
    dec = reviewer_client.post(f"/confirmations/{pending['confirmation_id']}/decision",
                               json={"approved": False, "note": "not now"})
    assert dec.status_code == 200 and dec.json()["status"] == "rejected"
    assert len(client.get("/findings", params={"project_id": "proj_t"}).json()) == before
