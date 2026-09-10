"""Shared fixtures: isolated SQLite DB + seeded minimal Orion EV slice."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "evaluation"))

TEST_DB = REPO_ROOT / "data" / "test_ariadne.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["DEMO_MODE"] = "1"
os.environ["MCP_ENABLED"] = "0"
# tests stay deterministic and memory-bounded: lexical embeddings, no VLM.
# semantic/VLM arms are measured by the evaluation suites in their own process.
os.environ["EMBEDDING_LOCAL_ENABLED"] = "0"
os.environ["VISION_ENABLED"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.ids import stable_id  # noqa: E402
from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db import models as M  # noqa: E402
from app.main import app  # noqa: E402
from app.services.rag.ingestion import ingest_all  # noqa: E402


@pytest.fixture(scope="session")
def seeded_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()
    with SessionLocal() as s:
        s.add(M.Project(id="proj_t", name="Test Orion", code="T", metadata_json={"primary_component": "cmp_motor_mount"}))
        for label, seq in (("A", 1), ("B", 2)):
            s.add(M.Revision(id=f"rev_{label.lower()}", project_id="proj_t", name=f"Rev {label}", label=label,
                             sequence=seq, metadata_json={"date": "2026-01-01"}))
        s.flush()
        for label in ("a", "b"):
            manifest = REPO_ROOT / "data" / "drawings" / f"rev_{label}" / "manifest.json"
            info = __import__("json").loads(manifest.read_text())
            for kind in ("part", "assembly"):
                f = info["drawings"][kind]["file"]
                s.add(M.Drawing(id=stable_id("dwg", label, kind), project_id="proj_t", revision_id=f"rev_{label}",
                                filename=f, storage_path=str(REPO_ROOT / "data" / "drawings" / f"rev_{label}" / f),
                                drawing_type=kind, width_px=1600, height_px=1100, manifest_path=str(manifest),
                                metadata_json={"drawing_kind": kind}))
        for cid, name in (("cmp_motor_mount", "Motor Mount"), ("cmp_chassis_interface", "Chassis Interface"),
                          ("cmp_fastener_m10", "Fastener Set M10"), ("cmp_motor_assembly", "Assembly A-01")):
            s.add(M.Component(id=cid, project_id="proj_t", name=name))
        s.flush()
        for src, dst, rel in (("cmp_motor_mount", "cmp_chassis_interface", "MATES_WITH"),
                              ("cmp_motor_mount", "cmp_fastener_m10", "USES"),
                              ("cmp_motor_mount", "cmp_motor_assembly", "PART_OF")):
            s.add(M.Dependency(id=stable_id("dep", src, dst, rel), project_id="proj_t",
                               source_component_id=src, target_component_id=dst, relationship_type=rel))
        for rev, flange, hole in (("rev_a", 48.0, 8.5), ("rev_b", 52.0, 10.5)):
            s.add(M.ComponentRevision(id=stable_id("crev", "cmp_motor_mount", rev), component_id="cmp_motor_mount",
                                      revision_id=rev, properties_json={"flange_dia": flange, "flange_tol": 0.05,
                                                                        "bolt_hole_dia": hole, "mass_g": 438.0,
                                                                        "material": "AL-7075-T6",
                                                                        "fastener_size": "M10",
                                                                        "cooling_channel": "straight",
                                                                        "overall_height": 22.0,
                                                                        "max_operating_temp_c": 83.0,
                                                                        "cooling_capacity_w": 185.0}))
            s.add(M.ComponentRevision(id=stable_id("crev", "cmp_chassis_interface", rev),
                                      component_id="cmp_chassis_interface", revision_id=rev,
                                      properties_json={"aperture_dia_mm": 54.0}))
        s.commit()
        ingest_all(s, "proj_t")
        s.commit()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture()
def client(seeded_db):
    with TestClient(app) as c:
        c.headers.update({"X-ARIADNE-User": "u_engineer_1"})
        yield c


@pytest.fixture()
def reviewer_client(seeded_db):
    with TestClient(app) as c:
        c.headers.update({"X-ARIADNE-User": "u_reviewer_1"})
        yield c


@pytest.fixture()
def viewer_client(seeded_db):
    with TestClient(app) as c:
        c.headers.update({"X-ARIADNE-User": "u_viewer_1"})
        yield c


@pytest.fixture()
def session(seeded_db):
    with SessionLocal() as s:
        yield s
