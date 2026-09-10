#!/usr/bin/env python3
"""Seed the ORION EV synthetic project end-to-end.

    python scripts/seed.py

Creates: users, project, 3 revisions, 6 drawings (part+assembly per revision),
9 components with per-revision property snapshots, dependency edges, the
document corpus (PDF parse → chunk → embed → index), requirement rows with
machine-readable rules, two seeded findings with evidence, and the evaluation
datasets (revision pairs, retrieval qrels, tool-selection cases).

Idempotent: re-running performs a full reset of application data first, so a
fresh developer always lands on a known-good state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import delete  # noqa: E402

from app.core.ids import stable_id, utcnow  # noqa: E402
from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db import models as M  # noqa: E402
from app.services.rag.ingestion import ingest_all  # noqa: E402

DRAWINGS = REPO_ROOT / "data" / "drawings"

PROJECT_ID = "proj_orion_ev"

REVISIONS = [
    ("rev_a", "Rev A", "A", 1, "2026-01-12", "Initial release for prototype build.", None),
    ("rev_b", "Rev B", "B", 2, "2026-03-04",
     "Flange enlarged, bolt holes upsized, M6 tapped hole added for sensor bracket.", "rev_a"),
    ("rev_c", "Rev C", "C", 3, "2026-06-18",
     "Material change to 6061-T6, serpentine cooling channel, M12 fasteners.", "rev_b"),
]

COMPONENTS = [
    ("cmp_motor_mount", "Motor Mount", "DWG-042", "part", "Powertrain", "AL-7075-T6", 412.0,
     "Structural mount transferring motor torque/reaction into the chassis cradle."),
    ("cmp_chassis_interface", "Chassis Interface", "DWG-051", "part", "Chassis", "AL-6061-T6", 890.0,
     "Machined cradle face receiving the motor mount flange."),
    ("cmp_cooling_bracket", "Cooling Bracket", "DWG-063", "part", "Thermal", "AL-6082-T6", 210.0,
     "Carries the cooling loop manifold across the mount rear face."),
    ("cmp_battery_housing", "Battery Housing", "DWG-088", "part", "Battery", "AL-5052-H32", 5400.0,
     "Enclosure; defines the rear clearance envelope for the mount."),
    ("cmp_fastener_m10", "Fastener Set M10", "ORN-FS-017", "fastener", "Powertrain", "Steel 10.9", 96.0,
     "Four structural fasteners per joint, class F2/F3."),
    ("cmp_thermal_system", "Thermal System T-02", "SYS-T-02", "system", "Thermal", "", 0.0,
     "Cooling loop supplying the mount channel."),
    ("cmp_motor_assembly", "Motor Mount Assembly A-01", "A-01", "assembly", "Powertrain", "", 2350.0,
     "Top-level assembly of DWG-042/051/063."),
    ("cmp_sensor_bracket", "Sensor Bracket", "DWG-071", "part", "Electrical", "AL-5052", 48.0,
     "Introduced at Rev B on the new M6 tapped hole."),
    ("cmp_harness_connector", "Harness Connector E-05", "E-05", "part", "Electrical", "PA66-GF30", 22.0,
     "Sensor harness connector mating the sensor bracket."),
]

DEPENDENCIES = [
    ("cmp_motor_mount", "cmp_chassis_interface", "MATES_WITH", "Flange face to cradle face, sealed joint", "critical"),
    ("cmp_motor_mount", "cmp_fastener_m10", "USES", "4 × structural fasteners, cross-torqued", "critical"),
    ("cmp_motor_mount", "cmp_motor_assembly", "PART_OF", "", "normal"),
    ("cmp_chassis_interface", "cmp_motor_assembly", "PART_OF", "", "normal"),
    ("cmp_cooling_bracket", "cmp_motor_mount", "MATES_WITH", "Rear face mounting", "normal"),
    ("cmp_cooling_bracket", "cmp_thermal_system", "PART_OF", "", "normal"),
    ("cmp_thermal_system", "cmp_cooling_bracket", "SUPPLIES", "Coolant supply/return", "normal"),
    ("cmp_motor_mount", "cmp_battery_housing", "DEPENDS_ON", "Rear clearance envelope", "normal"),
    ("cmp_sensor_bracket", "cmp_motor_mount", "USES", "M6 tapped hole introduced at Rev B", "normal"),
    ("cmp_harness_connector", "cmp_sensor_bracket", "MATES_WITH", "", "normal"),
]

# Extra structured properties that the deterministic checks need but that are
# not visible on the drawing (mating apertures, thermal capability, ...).
EXTRA_PROPERTIES: dict[str, dict[str, dict]] = {
    "cmp_chassis_interface": {
        "rev_a": {"aperture_dia_mm": 54.0, "material": "AL-6061-T6"},
        "rev_b": {"aperture_dia_mm": 54.0, "material": "AL-6061-T6"},
        "rev_c": {"aperture_dia_mm": 54.0, "material": "AL-6061-T6"},
    },
    "cmp_motor_mount": {
        "rev_a": {"max_operating_temp_c": 82.0, "cooling_capacity_w": 185.0},
        "rev_b": {"max_operating_temp_c": 83.0, "cooling_capacity_w": 185.0},
        "rev_c": {"max_operating_temp_c": 79.0, "cooling_capacity_w": 205.0},
    },
    "cmp_cooling_bracket": {
        "rev_a": {"material": "AL-6082-T6"}, "rev_b": {"material": "AL-6082-T6"},
        "rev_c": {"material": "AL-6082-T6"},
    },
    "cmp_fastener_m10": {
        "rev_a": {"size": "M10", "property_class": "10.9"},
        "rev_b": {"size": "M10", "property_class": "10.9"},
        "rev_c": {"size": "M12", "property_class": "10.9"},
    },
}


def wipe(session) -> None:
    for table in (
        M.EvaluationMetric, M.EvaluationRun, M.AuditEvent, M.ToolExecution, M.Confirmation,
        M.ChatMessage, M.ChatSession, M.FindingEvidence, M.FindingComponent, M.Finding,
        M.Change, M.AnalysisEvent, M.AnalysisRun, M.VectorRecord, M.DocumentChunk, M.Requirement,
        M.Document, M.Dependency, M.ComponentRevision, M.Component, M.Drawing, M.Revision,
        M.Project, M.User,
    ):
        session.execute(delete(table))
    session.commit()


def seed_users(session) -> None:
    from app.core.security import DEMO_USERS

    for uid, (name, role) in DEMO_USERS.items():
        session.add(M.User(id=uid, display_name=name, role=role.value, email=f"{uid}@orion-ev.example"))


def seed_project(session) -> dict:
    project = M.Project(
        id=PROJECT_ID, name="Orion EV", code="ORN",
        description="Synthetic EV programme dataset: powertrain, thermal, chassis, battery, electrical.",
        status="active", metadata_json={"subsystems": ["Powertrain", "Thermal", "Chassis", "Battery", "Electrical"],
                     "primary_component": "cmp_motor_mount"},
    )
    session.add(project)
    rev_ids = {}
    for key, name, label, seq, date, notes, parent in REVISIONS:
        rev = M.Revision(
            id=f"rev_{label.lower()}", project_id=PROJECT_ID, name=name, label=label, sequence=seq,
            status="released", parent_revision_id=rev_ids.get(parent) if parent else None,
            released_by="u_reviewer_1", notes=notes, metadata_json={"date": date},
        )
        rev_ids[key] = rev.id
        session.add(rev)
    project.active_revision_id = rev_ids["rev_c"]
    session.flush()

    for key, name, label, seq, date, notes, parent in REVISIONS:
        manifest_path = DRAWINGS / key / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for kind in ("part", "assembly"):
            info = manifest["drawings"][kind]
            storage = str(DRAWINGS / key / info["file"])
            session.add(
                M.Drawing(
                    id=stable_id("dwg", key, kind), project_id=PROJECT_ID, revision_id=rev_ids[key],
                    filename=info["file"], storage_path=storage, drawing_type=kind, sheet="1/1",
                    width_px=manifest["width_px"], height_px=manifest["height_px"],
                    manifest_path=str(manifest_path), checksum=info["checksum"],
                    metadata_json={"drawing_kind": kind, "drawing_number": manifest["parameters"].get("dwg_no", ""),
                                   "synthetic": True},
                )
            )
    return rev_ids


def seed_components(session, rev_ids: dict) -> None:
    manifests = {key: json.loads((DRAWINGS / key / "manifest.json").read_text()) for key, *_ in REVISIONS}
    for cid, name, code, ctype, subsystem, material, weight, desc in COMPONENTS:
        session.add(M.Component(id=cid, project_id=PROJECT_ID, name=name, code=code, type=ctype,
                                subsystem=subsystem, material=material, weight_g=weight, description=desc,
                                status="active"))
    session.flush()
    for key, _name, label, _seq, _date, _notes, _parent in REVISIONS:
        params = manifests[key]["parameters"]
        mm_props = {
            "flange_dia": params["flange_dia"], "flange_tol": params["flange_tol"],
            "plate_size": params["plate_size"], "bore_dia": params["bore_dia"],
            "bolt_hole_dia": params["bolt_hole_dia"], "pattern_pitch": params["pattern_pitch"],
            "overall_height": params["overall_height"], "material": params["material"],
            "mass_g": params["mass_g"], "finish": params["finish"],
            "cooling_channel": params["cooling_channel"], "fastener_size": params["fastener_size"],
        }
        props_by_component = {
            "cmp_motor_mount": {**mm_props, **EXTRA_PROPERTIES["cmp_motor_mount"][key]},
            "cmp_chassis_interface": EXTRA_PROPERTIES["cmp_chassis_interface"][key],
            "cmp_cooling_bracket": EXTRA_PROPERTIES["cmp_cooling_bracket"][key],
            "cmp_fastener_m10": EXTRA_PROPERTIES["cmp_fastener_m10"][key],
        }
        for comp_id, props in props_by_component.items():
            session.add(
                M.ComponentRevision(
                    id=stable_id("crev", comp_id, key), component_id=comp_id, revision_id=rev_ids[key],
                    properties_json=props, changed_from_parent=key != "rev_a",
                )
            )


def seed_dependencies(session) -> None:
    for src, dst, rel, desc, crit in DEPENDENCIES:
        session.add(M.Dependency(id=stable_id("dep", src, dst, rel), project_id=PROJECT_ID,
                                 source_component_id=src, target_component_id=dst, relationship_type=rel,
                                 description=desc, criticality=crit))


def seed_findings(session, rev_ids: dict) -> None:
    req_42 = session.scalars(
        __import__("sqlalchemy").select(M.Requirement).where(M.Requirement.code == "ORN-FS-017 §4.2")
    ).first()
    chunk_id = None
    if req_42:
        from sqlalchemy import select

        chunk = session.scalars(
            select(M.DocumentChunk).where(M.DocumentChunk.document_id == req_42.document_id)
        ).all()
        match = [c for c in chunk if (c.metadata_json or {}).get("requirement_code") == "ORN-FS-017 §4.2"]
        chunk_id = match[0].id if match else None

    f1 = M.Finding(
        id="fd_seed_001", project_id=PROJECT_ID, revision_id=rev_ids["rev_a"], component_id="cmp_motor_mount",
        title="Rev A release: flange tolerance class verified against ORN-MM-042 §3.1",
        severity="low", confidence=0.9, description="Tolerance class ±0.10 confirmed for Ø48.0 at release.",
        recommendation="None — closed at release review.", status="accepted", source="manual",
        created_by="u_reviewer_1", reviewed_by="u_reviewer_1",
    )
    f2 = M.Finding(
        id="fd_seed_002", project_id=PROJECT_ID, revision_id=rev_ids["rev_b"], component_id="cmp_motor_mount",
        title="Rev B: radial clearance to Chassis Interface below ORN-FS-017 §4.2 minimum",
        severity="high", confidence=0.91,
        description="Flange Ø52.0 against a 54.0 mm mating aperture leaves 1.0 mm radial clearance; "
                    "ORN-FS-017 §4.2 requires ≥3.0 mm for M10+ joints. Deterministic check, reviewer decision open.",
        recommendation="Verify mating geometry; consider aperture rework or documented exception.",
        status="needs_review", source="analysis", created_by="u_engineer_1",
    )
    session.add_all([f1, f2])
    session.flush()
    if req_42:
        session.add(M.FindingEvidence(
            id="fev_seed_002a", finding_id=f2.id, evidence_type="document", document_id=req_42.document_id,
            chunk_id=chunk_id, page=req_42.page, section=req_42.section, excerpt=req_42.text, score=0.93,
        ))
    session.add(M.FindingEvidence(
        id="fev_seed_002b", finding_id=f2.id, evidence_type="structured", excerpt=(
            "min_radial_clearance: flange_diameter=52.0, mating_aperture=54.0, clearance=1.0, required=3.0 → FAIL"),
        score=1.0,
    ))
    manifest = json.loads((DRAWINGS / "rev_b" / "manifest.json").read_text())
    flange = next(i for i in manifest["items"] if i["id"] == "flange_diameter")
    session.add(M.FindingEvidence(
        id="fev_seed_002c", finding_id=f2.id, evidence_type="drawing", page=1, section="front view",
        bbox_json={"x": flange["bbox"][0], "y": flange["bbox"][1], "width": flange["bbox"][2],
                   "height": flange["bbox"][3]},
        excerpt="DWG-042 Rev B, front view flange dimension region", score=1.0,
    ))
    for cid in ("cmp_motor_mount", "cmp_chassis_interface"):
        session.add(M.FindingComponent(id=stable_id("flk", f2.id, cid), finding_id=f2.id, component_id=cid,
                                       role="affected"))


def main() -> None:
    print("ARIADNE seed — synthetic ORION EV dataset")
    init_db()
    with SessionLocal() as session:
        wipe(session)
        seed_users(session)
        rev_ids = seed_project(session)
        seed_components(session, rev_ids)
        seed_dependencies(session)
        session.commit()
        print("  project + revisions + drawings + components + dependencies ok")

        docs = ingest_all(session, PROJECT_ID)
        session.commit()
        print(f"  ingested {len(docs)} documents → "
              f"{sum(d['chunks'] for d in docs)} chunks, {sum(d['requirements'] for d in docs)} requirements")

        seed_findings(session, rev_ids)
        session.commit()
        print("  seeded findings with evidence ok")

    from scripts.generate_benchmark import main as gen_bench

    gen_bench()
    print("\nSeed complete. Start the stack:  make dev   (or docker compose up)")


if __name__ == "__main__":
    main()
