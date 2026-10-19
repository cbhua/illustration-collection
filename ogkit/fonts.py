"""Font mapping + text measurement.

OmniGraffle stores PostScript font names (``LMSans10-Regular``, ``Monaco``...).  On
macOS those resolve to the real fonts.  For previews rendered on Linux we map each
PostScript name to a metric-compatible (or at least similar) family available via
fontconfig, and we measure text with the same file so wrapping/auto-sizing matches.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
if os.path.exists(os.path.join(_FONT_DIR, "fonts.conf")) and "FONTCONFIG_FILE" not in os.environ:
    # must happen before cairo / fc-* are first used
    os.environ["FONTCONFIG_FILE"] = os.path.join(_FONT_DIR, "fonts.conf")

# PostScript-name prefix -> (fontconfig family, css generic, is_mono)
_FAMILY_RULES = [
    (r"^LMSans10|^LMSans", "Latin Modern Sans", "sans-serif", False),
    (r"^LMRoman|^CMUSerif|^LMSerif", "Latin Modern Roman", "serif", False),
    (r"^CMUSansSerif", "Latin Modern Sans", "sans-serif", False),
    (r"^LMMono|^CMUTypewriter", "Latin Modern Mono", "monospace", True),
    (r"^MapleMono", "Maple Mono", "monospace", True),
    (r"^FiraCode", "Fira Code", "monospace", True),
    (r"^Monaco|^Menlo|^PTMono|^SFMono|^Courier|^JetBrains|^SourceCode", "DejaVu Sans Mono", "monospace", True),
    (r"^TimesNewRoman|^Times|^Baskerville|^STSongti|^SourceHanSerif|^Georgia", "TeX Gyre Termes", "serif", False),
    (r"^Avenir", "Lato", "sans-serif", False),
    (r"^Helvetica|^Arial|^SFPro|^LucidaGrande|^Calibri|^NanumGothic|^\.SF", "TeX Gyre Heros", "sans-serif", False),
    (r"^PingFang|^Hiragino|^STHeiti", "Droid Sans Fallback", "sans-serif", False),
    (r"^AppleColorEmoji", "Noto Color Emoji", "sans-serif", False),
]

_FALLBACK_MONO = ["Maple Mono", "Fira Code", "DejaVu Sans Mono", "Noto Sans Mono"]

# OmniGraffle line height / font size, measured on 4 000+ auto-sized labels in the corpus
_LINE_HEIGHT = [
    (r"^LMSans|^LMRoman|^CMUSans", 1.438),
    (r"^CMUSerif", 1.25),
    (r"^Monaco", 1.369),
    (r"^Menlo", 1.164),
    (r"^MapleMono", 1.29),
    (r"^FiraCode", 1.26),
    (r"^Avenir", 1.375),
    (r"^TimesNewRoman", 1.15),
    (r"^Helvetica|^Arial", 1.15),
    (r"^PingFang", 1.4),
]


def _style(ps: str) -> tuple[str, str]:
    """Return (css weight, css style) from a PostScript name."""
    low = ps.lower()
    weight = "normal"
    for key, w in (("thin", "200"), ("extralight", "200"), ("light", "300"), ("book", "normal"),
                   ("medium", "500"), ("semibold", "600"), ("demi", "600"), ("bold", "bold"),
                   ("heavy", "800"), ("black", "900")):
        if key in low.split("-")[-1] or low.endswith(key):
            weight = w
    style = "italic" if ("italic" in low or "oblique" in low) else "normal"
    return weight, style


@functools.lru_cache(maxsize=None)
def available_families() -> frozenset[str]:
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return frozenset()
    fams = set()
    for line in out.splitlines():
        for f in line.split(","):
            fams.add(f.strip())
    return frozenset(fams)


@functools.lru_cache(maxsize=None)
def css_for(ps_name: str) -> dict:
    fam, generic, mono = None, "sans-serif", False
    for pat, family, gen, is_mono in _FAMILY_RULES:
        if re.search(pat, ps_name or ""):
            fam, generic, mono = family, gen, is_mono
            break
    avail = available_families()
    if fam and fam not in avail and mono:
        fam = next((f for f in _FALLBACK_MONO if f in avail), fam)
    weight, style = _style(ps_name or "")
    family_list = [f for f in (fam, ) if f] + (["Droid Sans Fallback"] if "Droid Sans Fallback" in avail else []) + [generic]
    return {"family": ", ".join(f"'{f}'" if " " in f else f for f in family_list), "primary": fam or generic,
            "weight": weight, "style": style, "mono": mono}


@functools.lru_cache(maxsize=None)
def font_file(ps_name: str, bold: bool = False, italic: bool = False) -> str | None:
    c = css_for(ps_name)
    pattern = c["primary"]
    if bold or c["weight"] in ("bold", "600", "800", "900"):
        pattern += ":bold"
    elif c["weight"] in ("200", "300"):
        pattern += ":light"
    if italic or c["style"] == "italic":
        pattern += ":italic"
    try:
        f = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True,
                           timeout=10).stdout.strip()
        return f if f and os.path.exists(f) else None
    except Exception:
        return None


@functools.lru_cache(maxsize=4096)
def _pil_font(ps_name: str, size_q: int, bold: bool = False, italic: bool = False):
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover
        return None
    path = font_file(ps_name, bold, italic)
    if not path:
        return None
    try:
        return ImageFont.truetype(path, size_q)
    except Exception:
        return None


def text_width(text: str, ps_name: str, size: float, bold: bool = False, italic: bool = False) -> float:
    """Width in points of ``text`` set in ``ps_name`` at ``size`` pt."""
    if not text:
        return 0.0
    c = css_for(ps_name)
    if c["mono"] and not re.search(r"[⺀-￿]", text):
        # true monospace fonts on macOS (Monaco/Menlo/Maple/Fira) are all 0.6 em
        return 0.6 * size * len(text)
    f = _pil_font(ps_name, 100, bold, italic)
    if f is None:
        return 0.55 * size * len(text)
    w = f.getlength(text)
    # CJK glyphs missing from the latin font -> use full em
    return w * size / 100.0


def line_height(ps_name: str, size: float) -> float:
    for pat, k in _LINE_HEIGHT:
        if re.search(pat, ps_name or ""):
            return size * k
    return size * 1.25
