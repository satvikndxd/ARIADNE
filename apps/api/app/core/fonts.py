"""Portable TrueType font resolution.

The drawing generator and any server-side rendering need a real TTF (Pillow's
built-in bitmap font produces unreadable CAD text).  We look in, in order:
``$ARIADNE_FONT_DIR``, common Linux font dirs, and finally the TTFs bundled
with ReportLab — so rendering works in a bare container with no font packages.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_CANDIDATE_DIRS = [
    os.environ.get("ARIADNE_FONT_DIR", ""),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts",
    "/System/Library/Fonts",
    "C:/Windows/Fonts",
]

_PREFERRED = {
    "regular": ["DejaVuSansMono.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Vera.ttf", "Arial.ttf"],
    "bold": ["DejaVuSansMono-Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "VeraBd.ttf", "Arialbd.ttf"],
}


def _reportlab_font_dir() -> Path | None:
    try:
        import reportlab  # noqa: PLC0415

        p = Path(reportlab.__file__).parent / "fonts"
        return p if p.is_dir() else None
    except Exception:  # pragma: no cover
        return None


@lru_cache(maxsize=1)
def available_fonts() -> dict[str, str]:
    found: dict[str, str] = {}
    dirs = [Path(d) for d in _CANDIDATE_DIRS if d]
    rl = _reportlab_font_dir()
    if rl:
        dirs.append(rl)
    for d in dirs:
        try:
            names = {p.name for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf")}
        except (OSError, FileNotFoundError):
            continue
        for style, prefs in _PREFERRED.items():
            if style in found:
                continue
            for pref in prefs:
                if pref in names:
                    found[style] = str(d / pref)
                    break
        # last-resort: any ttf in the directory
        if "regular" not in found and names:
            found["regular"] = str(d / sorted(names)[0])
    return found


def resolve_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts = available_fonts()
    path = fonts.get("bold" if bold else "regular") or fonts.get("regular")
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:  # pragma: no cover
            pass
    return ImageFont.load_default()
