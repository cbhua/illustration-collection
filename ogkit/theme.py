"""Theme loading: resolves semantic style names (colour hue + tone, size role, font
role) into concrete OmniGraffle values."""
from __future__ import annotations

import copy
import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_DIR = os.path.join(ROOT, "style", "themes")


def list_themes() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(THEME_DIR) if f.endswith(".yaml"))


class Theme:
    def __init__(self, data: dict):
        self.data = data
        self.name = data.get("name", "custom")

    @classmethod
    def load(cls, name_or_path: str | dict = "crayon", overrides: dict | None = None) -> "Theme":
        if isinstance(name_or_path, dict):
            data = copy.deepcopy(name_or_path)
        else:
            path = name_or_path if os.path.exists(str(name_or_path)) else os.path.join(THEME_DIR, f"{name_or_path}.yaml")
            with open(path) as fh:
                data = yaml.safe_load(fh)
        if overrides:
            _deep_update(data, overrides)
        return cls(data)

    # ---------------------------------------------------------------- fonts
    def font(self, role: str | None) -> str:
        fonts = self.data["fonts"]
        if role is None:
            return fonts["sans"]
        return fonts.get(role, role)  # unknown role = literal PostScript name

    def size(self, role) -> float:
        if isinstance(role, (int, float)):
            return float(role)
        return float(self.data["sizes"].get(role, self.data["sizes"]["label"]))

    # --------------------------------------------------------------- colours
    def text_color(self, c: str | None) -> str:
        if c is None:
            return self.data["text"]["primary"]
        if c.startswith("#"):
            return c
        if c in self.data["text"]:
            return self.data["text"][c]
        if c in self.data["palette"]:
            return self.swatch(c)["text"]
        raise KeyError(f"unknown text colour {c!r}; use #hex, a text role {list(self.data['text'])} "
                       f"or a palette hue {list(self.data['palette'])}")

    def swatch(self, color: str, tone: str = "light") -> dict:
        """Return {'fill': hex, 'alpha': a, 'stroke': hex, 'text': hex} for a palette hue."""
        if color.startswith("#"):
            return {"fill": color, "alpha": 1.0, "stroke": color, "text": color}
        pal = self.data["palette"]
        if color not in pal:
            raise KeyError(f"unknown colour {color!r}; palette = {list(pal)}")
        p = pal[color]
        if "base" in p:
            alpha = float(self.data.get("alpha", {}).get(tone, 0.1)) if tone != "solid" else 1.0
            return {"fill": p["base"], "alpha": alpha, "stroke": p["dark"], "text": p["dark"]}
        return {"fill": p["fill"], "alpha": float(p.get("alpha", 1.0)), "stroke": p["stroke"], "text": p["text"]}

    def palette_names(self) -> list[str]:
        return list(self.data["palette"])

    # ------------------------------------------------------------ components
    def comp(self, name: str) -> dict:
        return dict(self.data.get("components", {}).get(name, {}))

    @property
    def line(self) -> dict:
        return self.data["line"]

    @property
    def spacing(self) -> dict:
        return self.data["spacing"]

    @property
    def author(self) -> str:
        return self.data.get("author", "ogkit")


def theme_from_file(gf, base: str = "crayon", sheet: int | None = None) -> dict:
    """Derive theme data from an existing document so additions match it: dominant sans / mono
    fonts and sizes, connector colour/width/arrow/corner radius, and per-hue (fill, stroke, text)
    triples (the most common pair of each colour family)."""
    import collections
    from . import gio, rtf
    from .colors import ColorContext, to_hex, hue_family

    data = copy.deepcopy(Theme.load(base).data)
    data["name"] = f"auto({base})"
    cc = ColorContext(gf.doc)
    sheets = gf.sheets if sheet is None else [gf.sheets[sheet]]
    fonts, sizes, lines, heads, radii, pairs, texts = (collections.Counter() for _ in range(7))
    mono = collections.Counter()

    def yes(v):
        return v is None or v is True or str(v).upper() in ("YES", "TRUE", "1")

    for s in sheets:
        for g, _, _ in gio.iter_graphics(s.get("GraphicsList", [])):
            st = g.get("Style", {})
            stroke = st.get("stroke", {})
            if g.get("Class") == "LineGraphic":
                lines[(to_hex(cc.to_rgba(stroke.get("Color"))), float(stroke.get("Width", 1)))] += 1
                if stroke.get("HeadArrow") not in (None, "0"):
                    heads[(stroke["HeadArrow"], float(stroke.get("HeadScale", 1)))] += 1
                if stroke.get("LineType") == 2:
                    radii[float(stroke.get("CornerRadius", 0))] += 1
                continue
            t = g.get("Text", {}).get("Text")
            if t:
                for r in rtf.parse(t).runs():
                    if not r.text.strip():
                        continue
                    if re.search(r"Mono|Monaco|Menlo|Code|Courier|Consol", r.font):
                        mono[r.font] += len(r.text)
                    else:
                        fonts[r.font] += len(r.text)
                        sizes[r.size] += 1
                    texts[(hue_family(r.color), r.color)] += 1
            fill = st.get("fill", {})
            if yes(fill.get("Draws")) and yes(stroke.get("Draws")) and fill.get("Color"):
                f = cc.to_rgba(fill["Color"])
                sc = to_hex(cc.to_rgba(stroke.get("Color")))
                fam = hue_family(sc) if hue_family(sc) not in ("gray", "white", "black") else hue_family(to_hex(f))
                pairs[(fam, to_hex(f), round(f[3], 2), sc)] += 1
    if fonts:
        data["fonts"]["sans"] = fonts.most_common(1)[0][0]
    if mono:
        data["fonts"]["mono"] = mono.most_common(1)[0][0]
    if lines:
        (lc, lw), _ = lines.most_common(1)[0]
        data["line"]["color"], data["line"]["width"] = lc, lw
    if heads:
        (hd, hs), _ = heads.most_common(1)[0]
        data["line"]["head"], data["line"]["head_scale"] = hd, hs
    if radii:
        data["line"]["corner_radius"] = radii.most_common(1)[0][0]
    if sizes:
        common = sorted(sizes, key=lambda k: -sizes[k])[:4]
        lab = common[0]
        data["sizes"].update(label=lab, small=min(common + [lab]) if min(common) < lab else lab - 1,
                             heading=max(common) if max(common) > lab else lab + 2)
    seen = set()
    for (fam, fhex, a, shex), _ in pairs.most_common():
        if fam in seen or fam in ("white", "black"):
            continue
        seen.add(fam)
        tcol = next((c for (tf, c), _ in texts.most_common() if tf == fam), shex)
        data["palette"][fam] = {"fill": fhex, "alpha": a, "stroke": shex, "text": tcol}
    return data


def _deep_update(a: dict, b: dict):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_update(a[k], v)
        else:
            a[k] = v
