"""Colour handling for OmniGraffle plists and Cocoa RTF.

OmniGraffle colour dictionaries come in several flavours::

    {"r": .4, "g": .4, "b": .4, "space": "srgb"}          # sRGB
    {"w": "0", "space": "gg22"}                            # gamma-2.2 grey
    {"r": "0.6", "g": "0.6", "b": "0.6"}                   # legacy generic RGB
    {"r": .98, "g": .73, "b": .66, "space": "<sha1>"}      # ICC profile embedded in
                                                           # doc["ColorProfiles"] (usually Display P3)
    {..., "a": .5}                                         # optional alpha

Everything is normalised to sRGB ``(r, g, b, a)`` floats in [0, 1].
"""
from __future__ import annotations

import colorsys

_P3_TO_SRGB = (
    (1.2249401, -0.2249404, 0.0),
    (-0.0420569, 1.0420571, 0.0),
    (-0.0196376, -0.0786361, 1.0982735),
)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def p3_to_srgb(r: float, g: float, b: float) -> tuple[float, float, float]:
    lr, lg, lb = _lin(r), _lin(g), _lin(b)
    out = [m[0] * lr + m[1] * lg + m[2] * lb for m in _P3_TO_SRGB]
    return tuple(_gam(v) for v in out)  # type: ignore[return-value]


class ColorContext:
    """Knows which embedded ICC profiles are Display P3."""

    def __init__(self, doc: dict | None = None):
        self.p3_spaces: set[str] = set()
        if doc:
            for prof in doc.get("ColorProfiles", []):
                data = prof.get("data", b"")
                if b"Display P3" in data or b"D\x00i\x00s\x00p\x00l\x00a\x00y\x00 \x00P\x003" in data:
                    self.p3_spaces.add(prof.get("space"))

    def to_rgba(self, c: dict | None, default=(0.0, 0.0, 0.0, 1.0)) -> tuple[float, float, float, float]:
        if not c:
            return default
        a = float(c.get("a", 1.0))
        space = c.get("space")
        if "w" in c:
            w = float(c["w"])
            return (w, w, w, a)
        if "r" in c:
            r, g, b = float(c["r"]), float(c["g"]), float(c["b"])
            if space in self.p3_spaces:
                r, g, b = p3_to_srgb(r, g, b)
            return (r, g, b, a)
        return default


def to_hex(rgba) -> str:
    r, g, b = rgba[:3]
    return "#%02X%02X%02X" % tuple(int(round(min(1, max(0, v)) * 255)) for v in (r, g, b))


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def og_color(hex_or_rgb, alpha: float | None = None) -> dict:
    """Build an OmniGraffle sRGB colour dict from ``#RRGGBB``, ``#RRGGBB@0.5`` or an rgb tuple."""
    if isinstance(hex_or_rgb, str):
        if "@" in hex_or_rgb:
            hex_or_rgb, a = hex_or_rgb.split("@", 1)
            alpha = float(a) if alpha is None else alpha * float(a)
        r, g, b = hex_to_rgb(hex_or_rgb)
    else:
        r, g, b = hex_or_rgb[:3]
    d = {"r": round(r, 6), "g": round(g, 6), "b": round(b, 6), "space": "srgb"}
    if alpha is not None and alpha < 1:
        d["a"] = round(alpha, 4)
    return d


def hsl(hex_color: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s, l


def mix(c1: str, c2: str, t: float) -> str:
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def hue_family(hex_color: str) -> str:
    """Coarse colour-family name used to cluster the palette."""
    h, s, l = hsl(hex_color)
    if s < 0.12 or l > 0.97:
        if l > 0.9:
            return "white"
        if l < 0.12:
            return "black"
        return "gray"
    if h < 15 or h >= 340:
        return "red"
    if h < 40:
        return "orange"
    if h < 70:
        return "yellow"
    if h < 165:
        return "green"
    if h < 195:
        return "teal"
    if h < 250:
        return "blue"
    if h < 290:
        return "purple"
    return "pink"
