#!/usr/bin/env python3
"""Generate the synthetic ORION EV drawing set (Rev A / Rev B / Rev C).

Outputs, per revision:
  data/drawings/<rev>/motor_mount_DWG-042_<rev>.png      part drawing
  data/drawings/<rev>/motor_mount_assy_A-01_<rev>.png    assembly drawing
  data/drawings/<rev>/manifest.json                      ground-truth structure

The manifest is *the* reason this project can be evaluated honestly: every
dimension, feature, annotation and title-block field has a known id, value and
bounding box, so change detection is scored against real ground truth instead
of a human eyeballing a picture.

Rendering is pure Pillow — deterministic, no network, no model.
Geometry is dimensionally consistent (bolt pattern fits inside the flange
plate, holes clear the boss, callouts never collide).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.fonts import resolve_font  # noqa: E402

OUT_ROOT = REPO_ROOT / "data" / "drawings"

W, H = 1600, 1100
MM = 4.0  # px per mm in the front view

INK = (20, 24, 30)
FAINT = (148, 156, 166)
CENTER = (150, 160, 172)
ACCENT = (176, 62, 32)
PAPER = (251, 251, 249)

FRONT_CX, FRONT_CY = 420, 430
SIDE_X, SIDE_Y = 950, 260

F_TITLE = resolve_font(30, bold=True)
F_LABEL = resolve_font(21, bold=True)
F_DIM = resolve_font(19)
F_SMALL = resolve_font(15)
F_BLOCK = resolve_font(18)
F_TINY = resolve_font(13)

# Assembly drawing layout
ASM_CX, ASM_CY = 520, 430


# --------------------------------------------------------------------------- #
# Revision definitions — the engineering truth for the Orion EV motor mount.
# --------------------------------------------------------------------------- #
REV_A: dict[str, Any] = {
    "label": "A",
    "name": "Rev A",
    "date": "2026-01-12",
    "flange_dia": 48.0,
    "flange_tol": 0.10,
    "plate_size": 90.0,
    "bore_dia": 17.0,
    "bolt_hole_dia": 8.5,
    "pattern_pitch": 64.0,
    "bolt_hole_count": 4,
    "fastener_size": "M10",
    "threaded_hole": None,
    "material": "AL-7075-T6",
    "overall_height": 22.0,
    "height_tol": 0.15,
    "wall_thickness": 4.0,
    "mass_g": 412.0,
    "finish": "ANODIZE PER ORN-MF-300 §6",
    "cooling_channel": "straight",
    "general_tol": "ISO 2768-mK (reference only)",
    "release_note": "Initial release for prototype build.",
    "dwg_no": "DWG-042",
    "assy_balloons": [1, 2, 3, 4],
}

REV_B: dict[str, Any] = {
    **REV_A,
    "label": "B",
    "name": "Rev B",
    "date": "2026-03-04",
    "flange_dia": 52.0,
    "flange_tol": 0.05,
    "bolt_hole_dia": 10.5,
    "threaded_hole": {"size": "M6", "depth": 12.0},
    "mass_g": 438.0,
    "release_note": "Flange enlarged, bolt holes upsized, M6 tapped hole added for sensor bracket.",
    "assy_balloons": [1, 2, 3, 4, 5],
}

REV_C: dict[str, Any] = {
    **REV_B,
    "label": "C",
    "name": "Rev C",
    "date": "2026-06-18",
    "material": "AL-6061-T6",
    "cooling_channel": "serpentine",
    "bolt_hole_dia": 12.5,
    "fastener_size": "M12",
    "mass_g": 421.0,
    "finish": "HARD ANODIZE 25µm PER ORN-MF-300 §6.3",
    "release_note": "Material change to 6061-T6, serpentine cooling channel, M12 fasteners.",
}

REVISIONS = {"A": REV_A, "B": REV_B, "C": REV_C}


def _tb(draw: ImageDraw.ImageDraw, text: str, font, x: int, y: int) -> list[int]:
    left, top, right, bottom = draw.textbbox((x, y), text, font=font)
    return [int(left), int(top), int(right - left), int(bottom - top)]


def _text(draw, x, y, text, font, fill=INK):
    draw.text((x, y), text, font=font, fill=fill)
    return _tb(draw, text, font, x, y)


def _leader(draw, x1, y1, x2, y2, color=FAINT):
    draw.line([x1, y1, x2, y2], fill=color, width=1)
    draw.ellipse([x1 - 2, y1 - 2, x1 + 2, y1 + 2], fill=color)


def _dim_v(draw, x, y1, y2):
    draw.line([x, y1, x, y2], fill=INK, width=2)
    for y in (y1, y2):
        draw.polygon([(x - 5, y), (x + 5, y), (x, y + (6 if y == y1 else -6))], fill=INK)


def _center_marks(draw, cx, cy, r):
    draw.line([cx - r - 16, cy, cx + r + 16, cy], fill=CENTER, width=1)
    draw.line([cx, cy - r - 16, cx, cy + r + 16], fill=CENTER, width=1)


def _item(
    item_id: str,
    kind: str,
    semantic: str,
    label: str,
    value: Any,
    unit: str,
    bbox: list[int],
    *,
    tolerance: str | None = None,
    count: int | None = None,
    drawing: str = "part",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item_id,
        "kind": kind,
        "semantic": semantic,
        "label": label,
        "value": value,
        "unit": unit,
        "bbox": bbox,
        "component_id": "cmp_motor_mount",
        "drawing": drawing,
    }
    if tolerance:
        out["tolerance"] = tolerance
    if count is not None:
        out["count"] = count
    return out


def render_frame(draw):
    draw.rectangle([16, 16, W - 16, H - 16], outline=INK, width=3)
    draw.rectangle([26, 26, W - 26, H - 26], outline=FAINT, width=1)


def render_front_view(draw, rev: dict[str, Any], items: list[dict[str, Any]]) -> None:
    half = int(rev["plate_size"] / 2 * MM)
    r_boss = rev["flange_dia"] / 2 * MM
    r_bore = rev["bore_dia"] / 2 * MM
    r_hole = rev["bolt_hole_dia"] / 2 * MM
    pitch = int(rev["pattern_pitch"] / 2 * MM)

    _text(draw, FRONT_CX - 60, 108, "FRONT VIEW", F_LABEL)

    # square flange plate
    draw.rectangle([FRONT_CX - half, FRONT_CY - half, FRONT_CX + half, FRONT_CY + half], outline=INK, width=3)
    _center_marks(draw, FRONT_CX, FRONT_CY, half)
    # round boss + centre bore
    draw.ellipse([FRONT_CX - r_boss, FRONT_CY - r_boss, FRONT_CX + r_boss, FRONT_CY + r_boss], outline=INK, width=3)
    draw.ellipse([FRONT_CX - r_bore, FRONT_CY - r_bore, FRONT_CX + r_bore, FRONT_CY + r_bore], outline=INK, width=2)

    # 4-hole square pattern
    for sx in (-1, 1):
        for sy in (-1, 1):
            hx, hy = FRONT_CX + sx * pitch, FRONT_CY + sy * pitch
            draw.ellipse([hx - r_hole, hy - r_hole, hx + r_hole, hy + r_hole], outline=INK, width=2)
            draw.line([hx - r_hole - 6, hy, hx + r_hole + 6, hy], fill=CENTER, width=1)
            draw.line([hx, hy - r_hole - 6, hx, hy + r_hole + 6], fill=CENTER, width=1)

    if rev.get("cooling_channel") == "serpentine":
        for k in range(3):
            yy = FRONT_CY - 52 + k * 52
            draw.arc([FRONT_CX - 78, yy - 26, FRONT_CX + 78, yy + 26], 0, 180, fill=ACCENT, width=2)

    # plate width dimension (top)
    plabel = f"{rev['plate_size']:.1f} SQ"
    _dim_v(draw, FRONT_CX - half - 40, FRONT_CY - half, FRONT_CY - half + 0) if False else None
    draw.line([FRONT_CX - half, FRONT_CY - half - 40, FRONT_CX + half, FRONT_CY - half - 40], fill=INK, width=2)
    for x in (FRONT_CX - half, FRONT_CX + half):
        draw.polygon([(x, FRONT_CY - half - 45), (x, FRONT_CY - half - 35), (x + (6 if x < FRONT_CX else -6), FRONT_CY - half - 40)], fill=INK)
    bbox = _text(draw, FRONT_CX - 34, FRONT_CY - half - 66, plabel, F_DIM)
    items.append(_item("plate_size", "dimension", "plate_size", plabel, rev["plate_size"], "mm", bbox))

    # boss diameter dimension (bottom-left leader)
    dlabel = f"Ø{rev['flange_dia']:.1f} ±{rev['flange_tol']:.2f}"
    bx = FRONT_CX - int(r_boss * 0.707)
    by = FRONT_CY + int(r_boss * 0.707)
    lx, ly = bx - 210, by + 120
    _leader(draw, bx, by, lx + 150, ly + 2)
    bbox = _text(draw, lx, ly, dlabel, F_DIM)
    items.append(
        _item("flange_diameter", "dimension", "flange_diameter", dlabel, rev["flange_dia"], "mm", bbox,
              tolerance=f"±{rev['flange_tol']:.2f}")
    )

    # bore dimension (right of view)
    blabel = f"Ø{rev['bore_dia']:.1f}"
    _leader(draw, FRONT_CX + int(r_bore * 0.707), FRONT_CY - int(r_bore * 0.707), FRONT_CX + half + 30, FRONT_CY - half - 10)
    bbox = _text(draw, FRONT_CX + half + 36, FRONT_CY - half - 18, blabel, F_DIM)
    items.append(_item("bore_diameter", "dimension", "bore_diameter", blabel, rev["bore_dia"], "mm", bbox))

    # bolt-hole callout (top-right leader)
    hlabel = f"{rev['bolt_hole_count']} × Ø{rev['bolt_hole_dia']:.1f} THRU"
    hx, hy = FRONT_CX + pitch, FRONT_CY - pitch
    _leader(draw, hx + int(r_hole * 0.7), hy - int(r_hole * 0.7), hx + 96, hy - 92)
    bbox = _text(draw, hx + 102, hy - 100, hlabel, F_DIM)
    items.append(
        _item("bolt_hole_diameter", "dimension", "bolt_hole_diameter", hlabel, rev["bolt_hole_dia"], "mm", bbox,
              count=rev["bolt_hole_count"])
    )

    # pattern pitch dimension (bottom)
    clabel = f"{rev['pattern_pitch']:.1f} SQ PATTERN"
    draw.line([FRONT_CX - pitch, FRONT_CY + half + 34, FRONT_CX + pitch, FRONT_CY + half + 34], fill=INK, width=2)
    for x in (FRONT_CX - pitch, FRONT_CX + pitch):
        draw.line([x, FRONT_CY + half + 6, x, FRONT_CY + half + 40], fill=CENTER, width=1)
    bbox = _text(draw, FRONT_CX - 66, FRONT_CY + half + 44, clabel, F_DIM)
    items.append(_item("hole_pattern", "dimension", "hole_pattern_pitch", clabel, rev["pattern_pitch"], "mm", bbox))

    # fastener note under pattern
    flabel = f"FASTENERS: {rev['fastener_size']} × {rev['bolt_hole_count']} PER ORN-FS-017 §4"
    bbox = _text(draw, FRONT_CX - 130, FRONT_CY + half + 70, flabel, F_SMALL)
    items.append(_item("fastener_callout", "annotation", "fastener_size", flabel, rev["fastener_size"], "", bbox))

    # threaded hole (Rev B+)
    if rev.get("threaded_hole"):
        th = rev["threaded_hole"]
        tx, ty = FRONT_CX, FRONT_CY + int(36 * MM)
        draw.ellipse([tx - 11, ty - 11, tx + 11, ty + 11], outline=ACCENT, width=3)
        draw.line([tx - 7, ty - 7, tx + 7, ty + 7], fill=ACCENT, width=2)
        tlabel = f"{th['size']} TAP × {th['depth']:.0f} DEEP"
        _leader(draw, tx + 11, ty, tx + 210, ty - 40, ACCENT)
        bbox = _text(draw, tx + 216, ty - 52, tlabel, F_DIM, ACCENT)
        items.append(
            _item("threaded_hole", "feature", "threaded_hole", tlabel, th["size"], "", [tx - 13, ty - 13, 26, 26])
        )


def render_side_view(draw, rev: dict[str, Any], items: list[dict[str, Any]]) -> None:
    hw = 130
    hh = int(rev["overall_height"] * MM)
    x0, y0 = SIDE_X, SIDE_Y
    _text(draw, x0 - 10, y0 - 52, "SIDE VIEW / SECTION A-A", F_LABEL)
    draw.rectangle([x0, y0, x0 + hw * 2, y0 + hh], outline=INK, width=3)
    wall = int(rev["wall_thickness"] * MM)
    draw.line([x0 + wall, y0, x0 + wall, y0 + hh], fill=FAINT, width=1)
    draw.line([x0 + hw * 2 - wall, y0, x0 + hw * 2 - wall, y0 + hh], fill=FAINT, width=1)
    draw.rectangle([x0 + 96, y0 - 6, x0 + 96 + 30, y0 + hh + 6], outline=INK, width=2)
    draw.rectangle([x0 + 156, y0 - 6, x0 + 156 + 30, y0 + hh + 6], outline=INK, width=2)

    if rev.get("cooling_channel") == "serpentine":
        pts = [(x0 + 30 + k * 40, y0 + hh - 12 if k % 2 else y0 + 12) for k in range(6)]
        draw.line(pts, fill=ACCENT, width=3)
        clabel = "COOLING CHANNEL — SERPENTINE"
        color = ACCENT
    else:
        draw.line([x0 + 30, y0 + hh - 12, x0 + hw * 2 - 30, y0 + hh - 12], fill=FAINT, width=2)
        clabel = "COOLING CHANNEL — STRAIGHT"
        color = FAINT
    bbox = _text(draw, x0, y0 + hh + 22, clabel, F_DIM, color)
    items.append(_item("cooling_channel", "geometry", "cooling_channel_geometry", clabel, rev["cooling_channel"], "", bbox))

    # height dimension
    hlabel = f"{rev['overall_height']:.1f} ±{rev['height_tol']:.2f}"
    _dim_v(draw, x0 - 36, y0, y0 + hh)
    bbox = _text(draw, x0 - 150, y0 + hh // 2 - 8, hlabel, F_DIM)
    items.append(_item("overall_height", "dimension", "overall_height", hlabel, rev["overall_height"], "mm", bbox))


def render_notes(draw, rev: dict[str, Any], items: list[dict[str, Any]]) -> None:
    x, y = 70, 706
    _text(draw, x, y, "NOTES", F_LABEL)
    draw.line([x, y + 30, x + 600, y + 30], fill=INK, width=2)
    notes = [
        ("material_note", f"1. MATERIAL: {rev['material']}", rev["material"]),
        ("finish_note", f"2. FINISH: {rev['finish']}", rev["finish"]),
        ("general_tol_note", f"3. GENERAL TOLERANCES: {rev['general_tol']}", rev["general_tol"]),
        ("deburr_note", "4. DEBURR ALL EDGES. NO SHARP CORNERS.", "DEBURR"),
        ("mass_note", f"5. MASS: {rev['mass_g']:.0f} g (REFERENCE)", rev["mass_g"]),
    ]
    for i, (key, text, value) in enumerate(notes):
        bbox = _text(draw, x, y + 44 + i * 28, text, F_SMALL)
        items.append(_item(key, "annotation", key, text, value, "", bbox))


def render_title_block(draw, rev: dict[str, Any], items: list[dict[str, Any]]) -> None:
    x0, y1 = W - 590, H - 40
    y0 = y1 - 208
    x1 = W - 40
    draw.rectangle([x0, y0, x1, y1], outline=INK, width=3)
    col = x0 + 280
    draw.line([col, y0, col, y1 - 34], fill=INK, width=2)
    for fy in (y0 + 58, y0 + 116, y0 + 174):
        draw.line([x0, fy, x1, fy], fill=INK, width=2)

    left = [("DRAWING NO.", rev["dwg_no"]), ("PART", "MOTOR MOUNT"), ("SCALE / SHEET", "2:1  ·  1/1")]
    right = [("REVISION", rev["name"]), ("DATE", rev["date"]), ("MASS", f"{rev['mass_g']:.0f} g")]
    for i, ((kl, vl), (kr, vr)) in enumerate(zip(left, right)):
        yy = y0 + 6 + i * 58
        _text(draw, x0 + 12, yy, kl, F_TINY, FAINT)
        bbox = _text(draw, x0 + 12, yy + 18, vl, F_BLOCK)
        items.append(_item(f"tb_{kl.split()[0].lower()}", "metadata", f"title_block.{kl.lower().replace(' ', '_').replace('/', '_')}", vl, vl, "", bbox))
        _text(draw, col + 12, yy, kr, F_TINY, FAINT)
        bbox = _text(draw, col + 12, yy + 18, vr, F_BLOCK)
        items.append(_item(f"tb_{kr.lower().replace(' ', '_')}", "metadata", f"title_block.{kr.lower().replace(' ', '_')}", vr, vr, "", bbox))

    line = "ORION EV — MOTOR MOUNT ASSEMBLY A-01 — SYNTHETIC DATASET"
    bbox = _text(draw, x0 + 12, y1 - 28, line, F_SMALL)
    items.append(_item("tb_project", "metadata", "title_block.project", line, "Orion EV", "", bbox))


def render_part_drawing(rev: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    items: list[dict[str, Any]] = []
    render_frame(draw)
    _text(draw, 56, 46, f"ORION EV  ·  {rev['name']}  ·  MOTOR MOUNT  ·  {rev['dwg_no']}", F_TITLE)
    _text(draw, 56, 84, "SYNTHETIC DATASET — NOT A REAL MANUFACTURING DOCUMENT", F_SMALL, FAINT)
    render_front_view(draw, rev, items)
    render_side_view(draw, rev, items)
    render_notes(draw, rev, items)
    render_title_block(draw, rev, items)
    filename = f"motor_mount_DWG-042_rev{rev['label']}.png"
    img.save(out_dir / filename, "PNG")
    return {"file": filename, "items": items, "kind": "part"}


ASM_PARTS = {
    1: ("cmp_motor_mount", "MOTOR MOUNT", "DWG-042"),
    2: ("cmp_chassis_interface", "CHASSIS INTERFACE", "DWG-051"),
    3: ("cmp_cooling_bracket", "COOLING BRACKET", "DWG-063"),
    4: ("cmp_fastener_m10", "FASTENER SET", "ORN-FS-017"),
    5: ("cmp_sensor_bracket", "SENSOR BRACKET", "DWG-071"),
}


def render_assembly_drawing(rev: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    items: list[dict[str, Any]] = []
    render_frame(draw)
    _text(draw, 56, 46, f"ORION EV  ·  {rev['name']}  ·  MOTOR MOUNT ASSEMBLY  ·  A-01", F_TITLE)
    _text(draw, 56, 84, "SYNTHETIC DATASET — NOT A REAL MANUFACTURING DOCUMENT", F_SMALL, FAINT)
    _text(draw, ASM_CX - 90, 130, "ASSEMBLY VIEW", F_LABEL)

    # chassis rail
    draw.rectangle([ASM_CX - 300, ASM_CY + 150, ASM_CX + 300, ASM_CY + 220], outline=INK, width=3)
    for x in range(ASM_CX - 280, ASM_CX + 300, 40):
        draw.line([x, ASM_CY + 220, x - 18, ASM_CY + 240], fill=FAINT, width=1)
    # motor mount plate
    draw.rectangle([ASM_CX - 140, ASM_CY - 20, ASM_CX + 140, ASM_CY + 150], outline=INK, width=3)
    draw.line([ASM_CX - 140, ASM_CY + 40, ASM_CX + 140, ASM_CY + 40], fill=FAINT, width=1)
    # cooling bracket
    draw.polygon([(ASM_CX + 150, ASM_CY - 60), (ASM_CX + 260, ASM_CY - 60), (ASM_CX + 260, ASM_CY + 90),
                  (ASM_CX + 200, ASM_CY + 90), (ASM_CX + 200, ASM_CY - 10), (ASM_CX + 150, ASM_CY - 10)],
                 outline=INK, width=3)
    # fasteners
    for sx in (-110, 110):
        draw.rectangle([ASM_CX + sx - 10, ASM_CY + 90, ASM_CX + sx + 10, ASM_CY + 210], outline=INK, width=2)
        draw.polygon([(ASM_CX + sx - 22, ASM_CY + 90), (ASM_CX + sx + 22, ASM_CY + 90),
                      (ASM_CX + sx + 14, ASM_CY + 60), (ASM_CX + sx - 14, ASM_CY + 60)], outline=INK, width=2)

    balloons = [
        (1, ASM_CX - 60, ASM_CY + 60, ASM_CX - 250, ASM_CY - 120),
        (2, ASM_CX + 40, ASM_CY + 185, ASM_CX + 250, ASM_CY + 300),
        (3, ASM_CX + 210, ASM_CY - 30, ASM_CX + 330, ASM_CY - 150),
        (4, ASM_CX + 110, ASM_CY + 120, ASM_CX + 320, ASM_CY + 90),
    ]
    if 5 in rev["assy_balloons"]:
        balloons.append((5, ASM_CX - 120, ASM_CY + 10, ASM_CX - 330, ASM_CY - 40))
        draw.rectangle([ASM_CX - 130, ASM_CY - 8, ASM_CX - 60, ASM_CY + 28], outline=ACCENT, width=3)
        items.append(
            _item("assy_sensor_bracket", "component", "component_added", "ITEM 5 SENSOR BRACKET (NEW)",
                  "cmp_sensor_bracket", "", [ASM_CX - 130, ASM_CY - 8, 70, 36], drawing="assembly")
        )

    for num, ax, ay, bx, by in balloons:
        draw.line([ax, ay, bx, by], fill=INK, width=1)
        draw.ellipse([bx - 20, by - 20, bx + 20, by + 20], outline=INK, width=2, fill=PAPER)
        bbox = _text(draw, bx - 7, by - 11, str(num), F_DIM)
        comp_id, name, ref = ASM_PARTS[num]
        items.append(_item(f"assy_balloon_{num}", "component", f"balloon_{num}", f"ITEM {num} — {name}", comp_id,
                           "", bbox, drawing="assembly"))

    # parts table
    tx0, ty0 = W - 620, 150
    draw.rectangle([tx0, ty0, tx0 + 560, ty0 + 46 + 46 * len(rev["assy_balloons"])], outline=INK, width=3)
    _text(draw, tx0 + 12, ty0 + 8, "ITEM", F_TINY, FAINT)
    _text(draw, tx0 + 70, ty0 + 8, "COMPONENT", F_TINY, FAINT)
    _text(draw, tx0 + 330, ty0 + 8, "REFERENCE", F_TINY, FAINT)
    draw.line([tx0, ty0 + 34, tx0 + 560, ty0 + 34], fill=INK, width=2)
    for i, num in enumerate(rev["assy_balloons"]):
        yy = ty0 + 42 + i * 46
        comp_id, name, ref = ASM_PARTS[num]
        if num == 4 and rev["fastener_size"] != "M10":
            name = f"FASTENER SET {rev['fastener_size']}"
        _text(draw, tx0 + 22, yy + 6, str(num), F_DIM)
        bbox = _text(draw, tx0 + 70, yy + 6, name, F_BLOCK)
        _text(draw, tx0 + 330, yy + 6, ref, F_DIM)
        if num == 4:
            items.append(_item("assy_fastener_row", "annotation", "fastener_size", name, rev["fastener_size"], "", bbox, drawing="assembly"))
        draw.line([tx0, yy + 40, tx0 + 560, yy + 40], fill=FAINT, width=1)

    # revision note block
    nx, ny = 70, 760
    _text(draw, nx, ny, "REVISION NOTE", F_LABEL)
    draw.line([nx, ny + 28, nx + 700, ny + 28], fill=INK, width=2)
    bbox = _text(draw, nx, ny + 40, rev["release_note"], F_SMALL)
    items.append(_item("assy_release_note", "annotation", "revision_note", rev["release_note"], rev["name"], "", bbox, drawing="assembly"))

    filename = f"motor_mount_assy_A-01_rev{rev['label']}.png"
    img.save(out_dir / filename, "PNG")
    return {"file": filename, "items": items, "kind": "assembly"}


def main() -> None:
    for label, rev in REVISIONS.items():
        out_dir = OUT_ROOT / f"rev_{label.lower()}"
        out_dir.mkdir(parents=True, exist_ok=True)
        part = render_part_drawing(rev, out_dir)
        assy = render_assembly_drawing(rev, out_dir)
        blob = (out_dir / part["file"]).read_bytes()
        manifest = {
            "schema_version": 2,
            "revision": rev["name"],
            "revision_label": label,
            "project": "Orion EV",
            "component_id": "cmp_motor_mount",
            "synthetic": True,
            "drawings": {
                "part": {"file": part["file"], "sheet": "1/1", "drawing_type": "part",
                         "checksum": hashlib.sha256(blob).hexdigest()},
                "assembly": {"file": assy["file"], "sheet": "1/1", "drawing_type": "assembly",
                             "checksum": hashlib.sha256((out_dir / assy["file"]).read_bytes()).hexdigest()},
            },
            "width_px": W,
            "height_px": H,
            "geometry": {
                "front_view": {
                    "center": [FRONT_CX, FRONT_CY],
                    "px_per_mm": MM,
                    "plate_half_px": int(rev["plate_size"] / 2 * MM),
                    "boss_radius_px": rev["flange_dia"] / 2 * MM,
                    "bore_radius_px": rev["bore_dia"] / 2 * MM,
                    "bolt_hole_radius_px": rev["bolt_hole_dia"] / 2 * MM,
                    "pattern_half_px": int(rev["pattern_pitch"] / 2 * MM),
                },
                "side_view": {"origin": [SIDE_X, SIDE_Y], "height_px": int(rev["overall_height"] * MM)},
            },
            "parameters": {k: v for k, v in rev.items() if k not in ("assy_balloons",)},
            "items": part["items"] + assy["items"],
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"  Rev {label}: {len(manifest['items']):>3} annotated items "
              f"({len(part['items'])} part / {len(assy['items'])} assembly) → data/drawings/rev_{label.lower()}/")
    print(f"\nGround truth: data/drawings/rev_*/manifest.json")


if __name__ == "__main__":
    main()
