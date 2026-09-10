"""End-to-end analysis pipeline over the seeded slice."""
from __future__ import annotations

import time


def _run_analysis(client) -> dict:
    r = client.post("/analysis", json={"project_id": "proj_t", "revision_a": "rev_a", "revision_b": "rev_b"})
    assert r.status_code == 202, r.text
    aid = r.json()["analysis_id"]
    for _ in range(60):
        st = client.get(f"/analysis/{aid}/status").json()
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert st["status"] == "completed", st
    return client.get(f"/analysis/{aid}").json()


def test_detects_the_known_changes(client):
    res = _run_analysis(client)
    semantics = {(c["metadata"] or {}).get("semantic") for c in res["changes"]}
    assert "flange_diameter" in semantics
    assert "bolt_hole_diameter" in semantics
    flange = next(c for c in res["changes"] if (c["metadata"] or {}).get("semantic") == "flange_diameter")
    assert flange["old_value"] == "48.0" and flange["new_value"] == "52.0"
    assert flange["confidence"] > 0.6
    assert flange["detection_method"] in ("hybrid", "structured", "cv_diff", "vlm")


def test_deterministic_clearance_failure_present(client):
    res = _run_analysis(client)
    codes = {c["requirement_code"]: c for c in res["deterministic_checks"]}
    assert codes["ORN-FS-017 §4.2"]["result"] == "fail"
    assert codes["ORN-FS-017 §4.2"]["inputs"]["clearance"] == 1.0


def test_affected_components_and_evidence(client):
    res = _run_analysis(client)
    names = {a["name"] for a in res["affected_components"]}
    assert "Chassis Interface" in names
    assert res["evidence"], "analysis must retrieve evidence"
    assert all(e["document_name"] or e["evidence_type"] != "document" for e in res["evidence"])


def test_insight_is_labelled_demo(client):
    res = _run_analysis(client)
    assert res["insight"]["mode"] == "demo"
    assert res["insight"]["grounded"] is True
    assert 0.0 <= res["confidence"] <= 1.0


def test_progress_events_cover_stages(client):
    r = client.post("/analysis", json={"project_id": "proj_t", "revision_a": "rev_a", "revision_b": "rev_b"})
    aid = r.json()["analysis_id"]
    for _ in range(60):
        st = client.get(f"/analysis/{aid}/status").json()
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    stages = {e["stage"] for e in st["events"]}
    assert {"loading_revisions", "detecting_changes", "retrieving_evidence"} <= stages
