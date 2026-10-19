"""Corpus analysis: distil style statistics from a folder of .graffle files.

Usage::

    python -m ogkit.analyze sources/OmniGraffle -o style/corpus_stats.json

The JSON is the raw material for ``style/theme.yaml`` and ``docs/style-guide.md``.
Every statistic is reported both for the full corpus and for "recent" files
(modified in or after ``--recent-year``), because personal style drifts over time.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics

from . import gio, rtf
from .colors import ColorContext, to_hex, hue_family

C = collections.Counter


def _yes(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).upper() in ("YES", "TRUE", "1")


def _round(v, q=0.5):
    return round(round(float(v) / q) * q, 2)


class Stats:
    def __init__(self):
        self.files = 0
        self.graphics = C()
        self.shapes = C()
        self.fonts_runs = C()
        self.fonts_chars = C()
        self.font_sizes = collections.defaultdict(C)  # font -> size counter
        self.text_colors = C()
        self.fill = C()
        self.stroke = C()
        self.pairs = C()  # (fill, stroke) for drawn+stroked boxes
        self.pair_text = C()  # (fill, stroke, textcolor) for boxes with text
        self.shape_stroke_w = C()
        self.line_w = C()
        self.line_color = C()
        self.radius = C()
        self.head = C()
        self.tail = C()
        self.head_scale = C()
        self.line_type = C()
        self.pattern_shape = C()
        self.pattern_line = C()
        self.shadow = C()
        self.box_sizes = C()
        self.align = C()
        self.pad = C()
        self.image_ext = C()
        self.bold_runs = 0
        self.italic_runs = 0
        self.canvas_bg = C()
        self.gaps_h = C()
        self.gaps_v = C()
        self.text_on_box = C()  # text placed inside filled/stroked shapes vs free labels
        self.opacity = C()
        self.families = C()

    def to_json(self, top=40):
        def top_items(c, n=top):
            return [[k if not isinstance(k, tuple) else list(k), v] for k, v in c.most_common(n)]

        out = {"files": self.files}
        for k, v in self.__dict__.items():
            if isinstance(v, collections.Counter):
                out[k] = top_items(v)
            elif isinstance(v, collections.defaultdict):
                out[k] = {f: top_items(c, 12) for f, c in sorted(v.items(), key=lambda kv: -sum(kv[1].values()))[:20]}
            elif k != "files":
                out[k] = v
        return out


def analyse_file(gf: gio.GraffleFile, st: Stats):
    doc = gf.doc
    cc = ColorContext(doc)
    st.files += 1
    for name in gf.assets:
        st.image_ext[os.path.splitext(name)[1].lower()] += 1
    for sheet in gf.sheets:
        bg = sheet.get("BackgroundGraphic", {}).get("Style", {}).get("fill", {})
        if _yes(bg.get("Draws"), True) and bg.get("Color"):
            st.canvas_bg[to_hex(cc.to_rgba(bg["Color"]))] += 1
        boxes = []
        for g, depth, parent in gio.iter_graphics(sheet.get("GraphicsList", [])):
            cls = g.get("Class")
            st.graphics[cls] += 1
            style = g.get("Style", {})
            fill, stroke, shadow = style.get("fill", {}), style.get("stroke", {}), style.get("shadow", {})
            if shadow and _yes(shadow.get("Draws"), True):
                st.shadow["on"] += 1
            else:
                st.shadow["off"] += 1
            if "Opacity" in g:
                st.opacity[_round(g["Opacity"], 0.05)] += 1
            if cls == "LineGraphic":
                st.line_w[_round(stroke.get("Width", 1), 0.25)] += 1
                st.line_color[to_hex(cc.to_rgba(stroke.get("Color")))] += 1
                st.head[stroke.get("HeadArrow", "0")] += 1
                st.tail[stroke.get("TailArrow", "0")] += 1
                if "HeadArrow" in stroke:
                    st.head_scale[stroke.get("HeadScale", 1)] += 1
                st.line_type[{None: "straight", 1: "curved", 2: "orthogonal"}.get(stroke.get("LineType"),
                                                                                      str(stroke.get("LineType")))] += 1
                st.pattern_line[stroke.get("Pattern", 0)] += 1
                if "CornerRadius" in stroke:
                    st.radius[("line", _round(stroke["CornerRadius"], 1))] += 1
                continue
            if cls != "ShapedGraphic":
                continue
            shape = g.get("Shape", "Rectangle")
            if str(shape).startswith("pdfImport"):
                shape = "pdfImport"
            if g.get("ImageID") is not None:
                shape = "Image"
            st.shapes[shape] += 1
            fill_on = _yes(fill.get("Draws"), True)
            stroke_on = _yes(stroke.get("Draws"), True)
            fc = to_hex(cc.to_rgba(fill.get("Color"), (1, 1, 1, 1))) if fill_on else None
            sc = to_hex(cc.to_rgba(stroke.get("Color"))) if stroke_on else None
            if fc:
                st.fill[fc] += 1
            if sc:
                st.stroke[sc] += 1
                st.shape_stroke_w[_round(stroke.get("Width", 1), 0.25)] += 1
                st.pattern_shape[stroke.get("Pattern", 0)] += 1
            if fc or sc:
                st.radius[("shape", _round(stroke.get("CornerRadius", 0), 1))] += 1
            if fc and sc and shape in ("Rectangle", "Circle"):
                st.pairs[(fc, sc)] += 1
                st.families[(hue_family(fc), hue_family(sc))] += 1
            text = g.get("Text", {})
            rt = rtf.parse(text.get("Text")) if text.get("Text") else None
            x, y, w, h = gio.parse_rect(g["Bounds"])
            if shape == "Rectangle" and (fc or sc) and g.get("ImageID") is None and depth >= 0:
                boxes.append((x, y, w, h))
            if rt and rt.plain.strip():
                st.text_on_box["box" if (fc or sc) else "label"] += 1
                runs = [r for r in rt.runs() if r.text.strip()]
                for r in runs:
                    st.fonts_runs[r.font] += 1
                    st.fonts_chars[r.font] += len(r.text)
                    st.font_sizes[r.font][r.size] += 1
                    st.text_colors[r.color] += 1
                    st.bold_runs += r.bold
                    st.italic_runs += r.italic
                for p in rt.paragraphs:
                    if p.text.strip():
                        st.align[p.align] += 1
                if (fc or sc) and runs:
                    st.pair_text[(fc or "none", sc or "none", runs[0].color)] += 1
                    st.box_sizes[(int(_round(w, 5)), int(_round(h, 5)))] += 1
                st.pad[(text.get("Pad", "default"), text.get("VerticalPad", "default"))] += 1
        _gaps(boxes, st)


def _gaps(boxes, st: Stats):
    """Estimate typical spacing between neighbouring boxes on the same row/column."""
    for i, (x, y, w, h) in enumerate(boxes):
        best_h = best_v = None
        for j, (x2, y2, w2, h2) in enumerate(boxes):
            if i == j:
                continue
            # same row: vertical overlap > 50%
            ov = min(y + h, y2 + h2) - max(y, y2)
            if ov > 0.5 * min(h, h2) and x2 >= x + w:
                gap = x2 - (x + w)
                if gap < 200 and (best_h is None or gap < best_h):
                    best_h = gap
            ov = min(x + w, x2 + w2) - max(x, x2)
            if ov > 0.5 * min(w, w2) and y2 >= y + h:
                gap = y2 - (y + h)
                if gap < 200 and (best_v is None or gap < best_v):
                    best_v = gap
        if best_h is not None:
            st.gaps_h[int(_round(best_h, 5))] += 1
        if best_v is not None:
            st.gaps_v[int(_round(best_v, 5))] += 1


def file_summary(gf: gio.GraffleFile) -> dict:
    doc = gf.doc
    st = Stats()
    analyse_file(gf, st)
    mod = doc.get("ModificationDate")
    cre = doc.get("CreationDate")
    sheets = []
    for s in gf.sheets:
        sheets.append({"title": s.get("SheetTitle"), "graphics": sum(1 for _ in gio.iter_graphics(s.get("GraphicsList", []))),
                       "canvas": s.get("CanvasSize")})
    return {
        "name": os.path.splitext(os.path.basename(gf.path or "?"))[0],
        "created": str(cre)[:10] if cre else None,
        "modified": str(mod)[:10] if mod else None,
        "app": (doc.get("ApplicationVersion") or [None, None])[1],
        "sheets": sheets,
        "graphics": dict(st.graphics),
        "images": len(gf.assets),
        "fonts": [f for f, _ in st.fonts_chars.most_common(5)],
        "top_pairs": [list(k) for k, _ in st.pairs.most_common(6)],
        "line_types": dict(st.line_type),
    }


def run(src: str, recent_year: int = 2024):
    files = sorted(f for f in os.listdir(src) if f.endswith(".graffle"))
    all_st, recent_st = Stats(), Stats()
    per_year = collections.defaultdict(Stats)
    summaries = []
    for f in files:
        gf = gio.load(os.path.join(src, f))
        summ = file_summary(gf)
        summaries.append(summ)
        analyse_file(gf, all_st)
        year = int((summ["modified"] or "1970")[:4])
        analyse_file(gf, per_year[year])
        if year >= recent_year:
            analyse_file(gf, recent_st)
    years = {}
    for y, s in sorted(per_year.items()):
        years[y] = {"files": s.files, "fonts": s.fonts_chars.most_common(6),
                    "line_types": dict(s.line_type), "shape_stroke_w": s.shape_stroke_w.most_common(4),
                    "radius": [[list(k), v] for k, v in s.radius.most_common(5)],
                    "families": [[list(k), v] for k, v in s.families.most_common(6)]}
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "source": os.path.relpath(src),
        "recent_year": recent_year,
        "all": all_st.to_json(),
        "recent": recent_st.to_json(),
        "by_year": years,
        "files": summaries,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default="style/corpus_stats.json")
    ap.add_argument("--recent-year", type=int, default=2024)
    a = ap.parse_args(argv)
    res = run(a.src, a.recent_year)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, ensure_ascii=False, default=str)
    print(f"analysed {res['all']['files']} files -> {a.out}")


if __name__ == "__main__":
    main()
