"""Render an OmniGraffle document to SVG / PNG (no OmniGraffle required).

This is a pragmatic re-implementation of OmniGraffle's drawing model, good enough to
preview generated figures on Linux and for an agent to visually self-check its work:

* rectangles (rounded), circles, triangles, diamonds, stars, adjustable arrows,
  free Bezier shapes, custom ``pdfImport-*`` shapes (paths from ``ExportShapes``)
* fills (solid / alpha / linear+radial gradients), strokes, dash patterns, shadows
* lines (straight / orthogonal / curved via ``LogicalPath``) with arrow heads
* Cocoa-RTF rich text with wrapping, alignment and vertical placement
* embedded images, including PDF (via pypdfium2) and TIFF
* groups, tables, rotation, flips, opacity, hidden layers

CLI::

    python -m ogkit.render figure.graffle -o figure.png [--sheet 0] [--scale 2]
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import math
import os
import re

from . import gio, rtf
from .colors import ColorContext, to_hex
from .fonts import css_for, text_width, line_height


def _yes(v, default=True):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).upper() in ("YES", "TRUE", "1")


def _f(v: float) -> str:
    return ("%.3f" % v).rstrip("0").rstrip(".")


# OmniGraffle stroke "Pattern" presets -> dash arrays in multiples of the stroke width
DASH = {
    1: (4, 3), 2: (1, 2), 3: (10, 5), 4: (1, 3), 5: (2, 2), 6: (4, 2), 7: (8, 4),
    11: (3, 3), 17: (6, 3, 1, 3), 24: (4, 4),
}


class SVGRenderer:
    def __init__(self, gf: gio.GraffleFile, sheet: int = 0, embed_images: bool = True,
                 image_dpi_scale: float = 2.0):
        self.gf = gf
        self.sheet = gf.sheets[sheet]
        self.cc = ColorContext(gf.doc)
        self.embed_images = embed_images
        self.image_scale = image_dpi_scale
        self.defs: list[str] = []
        self._uid = 0
        self.custom_shapes = {}
        for s in gf.sheets:
            for es in s.get("ExportShapes", []) or []:
                self.custom_shapes[es.get("ShapeName")] = es
        self.hidden_layers = {i for i, l in enumerate(self.sheet.get("Layers", [])) if not _yes(l.get("View"), True)}
        self.by_id = {}
        for g, _, _ in gio.iter_graphics(self.sheet.get("GraphicsList", [])):
            if "ID" in g:
                self.by_id[g["ID"]] = g
        self._img_cache: dict[int, tuple[str, str]] = {}

    # ------------------------------------------------------------------ utils
    def uid(self, p="d"):
        self._uid += 1
        return f"{p}{self._uid}"

    def color(self, c, default=(0, 0, 0, 1)):
        r = self.cc.to_rgba(c, default)
        return to_hex(r), r[3]

    # ------------------------------------------------------------- bounding box
    def bbox(self, margin: float = 10.0):
        xs, ys = [], []
        for g, _, _ in gio.iter_graphics(self.sheet.get("GraphicsList", [])):
            if g.get("Layer") in self.hidden_layers:
                continue
            if "Bounds" in g:
                x, y, w, h = gio.parse_rect(g["Bounds"])
                if w * h > 4e7:  # giant background
                    continue
                xs += [x, x + w]
                ys += [y, y + h]
            for p in g.get("Points", []):
                px, py = gio.parse_point(p)
                xs.append(px)
                ys.append(py)
        if not xs:
            return (0, 0, 100, 100)
        return (min(xs) - margin, min(ys) - margin, max(xs) - min(xs) + 2 * margin, max(ys) - min(ys) + 2 * margin)

    # ----------------------------------------------------------------- render
    def render(self, viewbox=None, background: str | None = "#FFFFFF") -> str:
        body = []
        for g in reversed(self.sheet.get("GraphicsList", [])):
            body.append(self.graphic(g))
        x, y, w, h = viewbox or self.bbox()
        bg = f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="{background}"/>' if background else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="{_f(x)} {_f(y)} {_f(w)} {_f(h)}" width="{_f(w)}" height="{_f(h)}">'
                f'<defs>{"".join(self.defs)}</defs>{bg}{"".join(body)}</svg>')

    def graphic(self, g: dict) -> str:
        if g.get("Layer") in self.hidden_layers:
            return ""
        cls = g.get("Class")
        out = ""
        if cls in ("Group", "TableGroup"):
            out = "".join(self.graphic(c) for c in reversed(g.get("Graphics", [])))
            if "Rotation" in g and cls == "Group":
                pass  # children already carry absolute geometry
        elif cls == "LineGraphic":
            out = self.line(g)
        elif cls == "ShapedGraphic":
            out = self.shape(g)
        op = g.get("Opacity")
        if op is not None and float(op) < 1 and out:
            out = f'<g opacity="{_f(float(op))}">{out}</g>'
        return out

    # ------------------------------------------------------------------ paint
    def paint(self, style: dict, bounds=None):
        fill = style.get("fill", {})
        stroke = style.get("stroke", {})
        attrs = []
        if _yes(fill.get("Draws"), True):
            ft = fill.get("FillType")
            if ft in (2, 3) and bounds is not None:
                gid = self.uid("grad")
                c1, a1 = self.color(fill.get("Color"), (1, 1, 1, 1))
                c2, a2 = self.color(fill.get("GradientColor"), (0, 0, 0, 1))
                mid = float(fill.get("MiddleFraction", 0.5))
                if ft == 2:
                    ang = math.radians(float(fill.get("GradientAngle", 0)))
                    dx, dy = math.cos(ang) / 2, math.sin(ang) / 2
                    self.defs.append(
                        f'<linearGradient id="{gid}" x1="{_f(.5 - dx)}" y1="{_f(.5 - dy)}" x2="{_f(.5 + dx)}" y2="{_f(.5 + dy)}">'
                        f'<stop offset="0" stop-color="{c1}" stop-opacity="{_f(a1)}"/>'
                        f'<stop offset="1" stop-color="{c2}" stop-opacity="{_f(a2)}"/></linearGradient>')
                else:
                    self.defs.append(
                        f'<radialGradient id="{gid}"><stop offset="0" stop-color="{c1}" stop-opacity="{_f(a1)}"/>'
                        f'<stop offset="1" stop-color="{c2}" stop-opacity="{_f(a2)}"/></radialGradient>')
                attrs.append(f'fill="url(#{gid})"')
            else:
                c, a = self.color(fill.get("Color"), (1, 1, 1, 1))
                attrs.append(f'fill="{c}"')
                if a < 1:
                    attrs.append(f'fill-opacity="{_f(a)}"')
        else:
            attrs.append('fill="none"')
        if _yes(stroke.get("Draws"), True):
            c, a = self.color(stroke.get("Color"))
            w = float(stroke.get("Width", 1))
            attrs.append(f'stroke="{c}" stroke-width="{_f(w)}"')
            if a < 1:
                attrs.append(f'stroke-opacity="{_f(a)}"')
            pat = stroke.get("Pattern")
            if pat:
                d = DASH.get(int(pat), (4, 4))
                attrs.append('stroke-dasharray="%s"' % ",".join(_f(v * max(w, 0.5)) for v in d))
            cap = stroke.get("Cap")
            if cap is not None:
                attrs.append('stroke-linecap="%s"' % {0: "butt", 1: "round", 2: "square"}.get(int(cap), "butt"))
            join = stroke.get("Join")
            if join is not None:
                attrs.append('stroke-linejoin="%s"' % {0: "miter", 1: "round", 2: "bevel"}.get(int(join), "miter"))
        else:
            attrs.append('stroke="none"')
        return " ".join(attrs)

    def shadow_filter(self, style: dict):
        sh = style.get("shadow", {})
        if not sh or not _yes(sh.get("Draws"), True):
            return ""
        fid = self.uid("sh")
        c, a = self.color(sh.get("Color"), (0, 0, 0, 0.5))
        dx, dy = gio.parse_point(sh.get("ShadowVector", "{0, 2}"))
        fz = float(sh.get("Fuzziness", 4))
        self.defs.append(f'<filter id="{fid}" x="-50%" y="-50%" width="200%" height="200%">'
                         f'<feDropShadow dx="{_f(dx)}" dy="{_f(dy)}" stdDeviation="{_f(fz / 2)}" '
                         f'flood-color="{c}" flood-opacity="{_f(a)}"/></filter>')
        return f' filter="url(#{fid})"'

    # ------------------------------------------------------------------ shapes
    def shape_path(self, g, x, y, w, h) -> str | None:
        shape = g.get("Shape", "Rectangle")
        style = g.get("Style", {})
        if shape in ("Rectangle", None):
            r = float(style.get("stroke", {}).get("CornerRadius", 0))
            r = min(r, w / 2, h / 2)
            return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" rx="{_f(r)}" ry="{_f(r)}" %s/>'
        if shape == "Circle":
            return f'<ellipse cx="{_f(x + w / 2)}" cy="{_f(y + h / 2)}" rx="{_f(w / 2)}" ry="{_f(h / 2)}" %s/>'
        pts = None
        if shape == "HorizontalTriangle":
            pts = [(x, y), (x + w, y + h / 2), (x, y + h)]
        elif shape == "VerticalTriangle":
            pts = [(x, y), (x + w, y), (x + w / 2, y + h)]
        elif shape == "RightTriangle":
            pts = [(x, y), (x + w, y + h), (x, y + h)]
        elif shape == "Diamond":
            pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        elif shape == "Parallelogram":
            o = w * 0.2
            pts = [(x + o, y), (x + w, y), (x + w - o, y + h), (x, y + h)]
        elif shape == "AdjustableStar":
            pts = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rr = 0.5 if i % 2 == 0 else 0.2
                pts.append((x + w / 2 + rr * w * math.cos(ang), y + h / 2 + rr * h * math.sin(ang)))
        elif shape == "AdjustableArrow":
            sd = g.get("ShapeData", {})
            ratio = float(sd.get("ratio", 0.5))
            head = min(float(sd.get("width", h)), w)
            t = h * (1 - ratio) / 2
            pts = [(x, y + t), (x + w - head, y + t), (x + w - head, y), (x + w, y + h / 2),
                   (x + w - head, y + h), (x + w - head, y + h - t), (x, y + h - t)]
        if pts:
            return '<polygon points="%s" %%s/>' % " ".join(f"{_f(px)},{_f(py)}" for px, py in pts)
        if shape == "Bezier":
            up = [gio.parse_point(p) for p in g.get("ShapeData", {}).get("UnitPoints", [])]
            if len(up) >= 3:
                P = lambda p: (x + (p[0] + 0.5) * w, y + (p[1] + 0.5) * h)
                n = len(up) // 3
                d = "M %s %s" % tuple(map(_f, P(up[0])))
                for i in range(n):
                    c1, c2 = P(up[3 * i + 1]), P(up[3 * i + 2])
                    p = P(up[3 * i + 3]) if 3 * i + 3 < len(up) else P(up[0])
                    d += " C %s %s %s %s %s %s" % tuple(map(_f, (*c1, *c2, *p)))
                return f'<path d="{d} Z" %s/>'
        es = self.custom_shapes.get(shape)
        if es and es.get("StrokePath"):
            d = self.path_d(es["StrokePath"].get("elements", []), lambda p: (x + (p[0] + 0.5) * w, y + (p[1] + 0.5) * h))
            return f'<path d="{d}" fill-rule="evenodd" %s/>'
        return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" %s/>'

    def path_d(self, elements, tf=lambda p: p) -> str:
        d = []
        for e in elements:
            el = e.get("element")
            if el == "MOVETO":
                d.append("M %s %s" % tuple(map(_f, tf(gio.parse_point(e["point"])))))
            elif el == "LINETO":
                d.append("L %s %s" % tuple(map(_f, tf(gio.parse_point(e["point"])))))
            elif el == "CURVETO":
                c1 = tf(gio.parse_point(e["control1"]))
                c2 = tf(gio.parse_point(e["control2"]))
                p = tf(gio.parse_point(e["point"]))
                d.append("C %s %s %s %s %s %s" % tuple(map(_f, (*c1, *c2, *p))))
            elif el == "CLOSE":
                d.append("Z")
        return " ".join(d)

    def transform(self, g, x, y, w, h) -> str:
        t = []
        cx, cy = x + w / 2, y + h / 2
        rot = float(g.get("Rotation", 0) or 0)
        if rot:
            t.append(f"rotate({_f(rot)} {_f(cx)} {_f(cy)})")
        hf, vf = _yes(g.get("HFlip"), False), _yes(g.get("VFlip"), False)
        if hf or vf:
            t.append(f"translate({_f(cx)} {_f(cy)}) scale({-1 if hf else 1} {-1 if vf else 1}) translate({_f(-cx)} {_f(-cy)})")
        return f' transform="{" ".join(t)}"' if t else ""

    def shape(self, g: dict) -> str:
        if "Bounds" not in g:
            return ""
        x, y, w, h = gio.parse_rect(g["Bounds"])
        style = g.get("Style", {})
        tf = self.transform(g, x, y, w, h)
        parts = []
        tmpl = self.shape_path(g, x, y, w, h)
        img_id = g.get("ImageID")
        fill_on = _yes(style.get("fill", {}).get("Draws"), True)
        stroke_on = _yes(style.get("stroke", {}).get("Draws"), True)
        flt = self.shadow_filter(style)
        if fill_on or flt:
            fill_style = {"fill": style.get("fill", {}), "stroke": {"Draws": "NO"}}
            parts.append(f'<g{flt}>' + tmpl % self.paint(fill_style, (x, y, w, h)) + "</g>")
        if img_id is not None:
            parts.append(self.image(g, img_id, x, y, w, h, tmpl))
        if stroke_on:
            stroke_style = {"fill": {"Draws": "NO"}, "stroke": style.get("stroke", {})}
            parts.append(tmpl % self.paint(stroke_style))
        out = "".join(parts)
        if tf:
            out = f"<g{tf}>{out}</g>"
        text = self.text(g, x, y, w, h)
        if text:
            trot = g.get("TextRotation")
            rot = float(g.get("Rotation", 0) or 0)
            if trot is not None:
                rot = float(trot)
            if rot:
                text = f'<g transform="rotate({_f(rot)} {_f(x + w / 2)} {_f(y + h / 2)})">{text}</g>'
            out += text
        return out

    # ------------------------------------------------------------------ images
    def _image_data(self, img_id: int):
        if img_id in self._img_cache:
            return self._img_cache[img_id]
        name = self.gf.image_name(img_id)
        data = self.gf.assets.get(name) if name else None
        res = None
        if data:
            ext = os.path.splitext(name)[1].lower()
            try:
                if ext == ".pdf":
                    res = ("image/png", _pdf_to_png(data, self.image_scale))
                elif ext in (".png",):
                    res = ("image/png", data)
                elif ext in (".jpg", ".jpeg"):
                    res = ("image/jpeg", data)
                else:
                    from PIL import Image
                    im = Image.open(io.BytesIO(data))
                    buf = io.BytesIO()
                    im.save(buf, "PNG")
                    res = ("image/png", buf.getvalue())
            except Exception:
                res = None
        self._img_cache[img_id] = res
        return res

    def image(self, g, img_id, x, y, w, h, tmpl) -> str:
        if not self.embed_images:
            return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="#ddd"/>'
        d = self._image_data(img_id)
        if not d:
            return ""
        mime, data = d
        href = f"data:{mime};base64," + base64.b64encode(data).decode()
        shape = g.get("Shape", "Rectangle")
        clip = ""
        if shape != "Rectangle" or float(g.get("Style", {}).get("stroke", {}).get("CornerRadius", 0) or 0) > 0:
            cid = self.uid("clip")
            self.defs.append(f'<clipPath id="{cid}">' + tmpl % "" + "</clipPath>")
            clip = f' clip-path="url(#{cid})"'
        par = "none" if _yes(g.get("StretchImage"), False) or g.get("Scaling") in (None, 1) else "xMidYMid meet"
        if _yes(g.get("ManualSizeImage"), False) and "Scale" in g:
            # manual scale/offset: approximate by centring the scaled natural image
            par = "xMidYMid slice"
        return f'<image x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" preserveAspectRatio="{par}" href="{href}"{clip}/>'

    # ------------------------------------------------------------------- text
    def text(self, g, x, y, w, h) -> str:
        t = g.get("Text", {})
        src = t.get("Text")
        if not src:
            return ""
        fi = g.get("FontInfo", {})
        rich = rtf.parse(src, fi.get("Font", "Helvetica"), float(fi.get("Size", 12)))
        if not rich.plain.strip():
            return ""
        pad = float(t.get("Pad", 5))
        vpad = float(t.get("VerticalPad", pad if "Pad" in t else 5))
        tra = g.get("TextRelativeArea")
        if tra:
            rx, ry, rw, rh = gio.parse_rect(tra)
            x, y, w, h = x + rx * w, y + ry * h, rw * w, rh * h
        wrap = _yes(g.get("Wrap"), True)
        avail = max(1.0, w - 2 * pad)
        lines = layout(rich, avail if wrap else None)
        total = sum(lh for _, lh, _, _ in lines)
        place = int(g.get("TextPlacement", 1))
        if place == 0:
            ty = y + vpad
        elif place == 2:
            ty = y + h - vpad - total
        else:
            ty = y + (h - total) / 2
        out = []
        for runs, lh, lw, align in lines:
            asc = lh * 0.78
            if align == "center":
                tx = x + w / 2 - lw / 2
            elif align == "right":
                tx = x + w - pad - lw
            else:
                tx = x + pad
            spans = []
            cx = tx
            for r in runs:
                css = css_for(r.font)
                fw = "bold" if r.bold else css["weight"]
                fs_ = "italic" if r.italic else css["style"]
                size = r.size * (0.7 if r.baseline else 1)
                dy = (-r.size * 0.35 if r.baseline == "super" else r.size * 0.2 if r.baseline == "sub" else 0)
                deco = []
                if r.underline:
                    deco.append("underline")
                if r.strike:
                    deco.append("line-through")
                rw = text_width(r.text, r.font, size, r.bold, r.italic)
                if r.background:
                    out.append(f'<rect x="{_f(cx)}" y="{_f(ty)}" width="{_f(rw)}" height="{_f(lh)}" fill="{r.background}"/>')
                spans.append(
                    f'<tspan x="{_f(cx)}" y="{_f(ty + asc + dy)}" font-family="{html.escape(css["family"])}" '
                    f'font-size="{_f(size)}" font-weight="{fw}" font-style="{fs_}" fill="{r.color}"'
                    + (f' text-decoration="{" ".join(deco)}"' if deco else "")
                    + f'>{html.escape(r.text)}</tspan>')
                cx += rw
            out.append(f'<text xml:space="preserve">{"".join(spans)}</text>')
            ty += lh
        return "".join(out)

    # ------------------------------------------------------------------- lines
    def line(self, g: dict) -> str:
        style = g.get("Style", {})
        stroke = style.get("stroke", {})
        if not _yes(stroke.get("Draws"), True):
            return ""
        pts = [gio.parse_point(p) for p in g.get("Points", [])]
        if len(pts) < 2:
            return ""
        lp = g.get("LogicalPath", {}).get("elements")
        poly = flatten(lp) if lp else pts
        # connected ends are stored at the shape centre; OmniGraffle clips them to the outline
        tail_g = self.by_id.get(g.get("Tail", {}).get("ID"))
        head_g = self.by_id.get(g.get("Head", {}).get("ID"))
        if tail_g is not None and tail_g.get("Class") == "ShapedGraphic":
            poly = clip_start(poly, lambda p: self.inside(tail_g, p))
        if head_g is not None and head_g.get("Class") == "ShapedGraphic":
            poly = clip_start(poly[::-1], lambda p: self.inside(head_g, p))[::-1]
        if len(poly) < 2:
            return ""
        c, a = self.color(stroke.get("Color"))
        w = float(stroke.get("Width", 1))
        head = stroke.get("HeadArrow")
        tail = stroke.get("TailArrow")
        hs, ts = float(stroke.get("HeadScale", 1)), float(stroke.get("TailScale", 1))
        out = []
        # shorten the stroke under filled arrow heads so the tip stays sharp
        body = list(poly)
        if head in FILLED_HEADS:
            body = shorten(body[::-1], arrow_len(w, hs) * 0.6)[::-1]
        if tail in FILLED_HEADS:
            body = shorten(body, arrow_len(w, ts) * 0.6)
        paint = self.paint({"fill": {"Draws": "NO"}, "stroke": stroke})
        if len(lp or []) <= 2 and not lp:
            pass
        d = path_from_poly(body)
        out.append(f'<path d="{d}" {paint}/>')
        if head and head != "0":
            out.append(arrowhead(head, _dir_from(poly, True), poly[-1], w, hs, c, a))
        if tail and tail != "0":
            out.append(arrowhead(tail, _dir_from(poly, False), poly[0], w, ts, c, a))
        return "".join(out)

    def inside(self, g: dict, p, tol: float = 0.01) -> bool:
        if "Bounds" not in g:
            return False
        x, y, w, h = gio.parse_rect(g["Bounds"])
        px, py = p
        rot = float(g.get("Rotation", 0) or 0)
        if rot:
            cx, cy = x + w / 2, y + h / 2
            t = math.radians(-rot)
            dx, dy = px - cx, py - cy
            px, py = cx + dx * math.cos(t) - dy * math.sin(t), cy + dx * math.sin(t) + dy * math.cos(t)
        if g.get("Shape") == "Circle":
            rx, ry = w / 2, h / 2
            if rx <= 0 or ry <= 0:
                return False
            return ((px - x - rx) / rx) ** 2 + ((py - y - ry) / ry) ** 2 < 1 - tol
        return x + tol < px < x + w - tol and y + tol < py < y + h - tol


FILLED_HEADS = {"FilledArrow", "Arrow", "SharpArrow", "FilledSharpArrow"}


def arrow_len(width: float, scale: float) -> float:
    return 9.0 * scale * max(1.0, width) ** 0.75


def flatten(elements, steps: int = 12):
    pts = []
    cur = None
    for e in elements:
        el = e.get("element")
        if el in ("MOVETO", "LINETO"):
            cur = gio.parse_point(e["point"])
            pts.append(cur)
        elif el == "CURVETO" and cur is not None:
            c1, c2, p = (gio.parse_point(e[k]) for k in ("control1", "control2", "point"))
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                pts.append((mt ** 3 * cur[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p[0],
                            mt ** 3 * cur[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p[1]))
            cur = p
    # drop consecutive duplicates
    out = [pts[0]] if pts else []
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def clip_start(poly, inside):
    """Remove the leading part of ``poly`` that lies inside a shape."""
    if not poly or not inside(poly[0]):
        return poly
    for i in range(1, len(poly)):
        if not inside(poly[i]):
            a, b = poly[i - 1], poly[i]
            lo, hi = 0.0, 1.0
            for _ in range(30):
                m = (lo + hi) / 2
                q = (a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m)
                if inside(q):
                    lo = m
                else:
                    hi = m
            q = (a[0] + (b[0] - a[0]) * hi, a[1] + (b[1] - a[1]) * hi)
            return [q] + poly[i:]
    return poly[-1:]


def shorten(poly, dist):
    """Trim ``dist`` from the start of a polyline."""
    if len(poly) < 2 or dist <= 0:
        return poly
    a, b = poly[0], poly[1]
    seg = math.hypot(b[0] - a[0], b[1] - a[1])
    if seg <= dist:
        return poly if len(poly) == 2 else shorten(poly[1:], dist - seg)
    t = dist / seg
    return [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)] + poly[1:]


def path_from_poly(poly):
    return "M " + " L ".join(f"{_f(x)} {_f(y)}" for x, y in poly)


def _dir_from(poly, head: bool):
    """A point some distance back along the path, for arrow direction."""
    seq = poly[::-1] if head else poly
    end = seq[0]
    for p in seq[1:]:
        if math.hypot(p[0] - end[0], p[1] - end[1]) > 2:
            return p
    return seq[-1] if len(seq) > 1 else (end[0] - 1, end[1])


def _path_ends(elements):
    """(tail_from, tail_point, head_from, head_point) direction vectors from a LogicalPath."""
    pts = []
    for e in elements:
        if e.get("element") == "CURVETO":
            pts.append(("c", gio.parse_point(e["control1"]), gio.parse_point(e["control2"]), gio.parse_point(e["point"])))
        elif "point" in e:
            pts.append(("p", gio.parse_point(e["point"])))
    start = pts[0][-1]
    first = pts[1]
    t_from = first[1] if first[0] == "c" and first[1] != start else first[-1]
    end = pts[-1][-1]
    last = pts[-1]
    h_from = last[2] if last[0] == "c" and last[2] != end else pts[-2][-1]
    return t_from, start, h_from, end


def _smooth_path(pts):
    d = f"M {_f(pts[0][0])} {_f(pts[0][1])}"
    for i in range(1, len(pts)):
        p0, p1 = pts[i - 1], pts[i]
        d += f" L {_f(p1[0])} {_f(p1[1])}"
    return d


def arrowhead(kind: str, frm, to, width: float, scale: float, color: str, alpha: float) -> str:
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    L = arrow_len(width, scale)
    W = L * 0.42
    tx, ty = to
    bx, by = tx - ux * L, ty - uy * L
    op = f' fill-opacity="{_f(alpha)}" stroke-opacity="{_f(alpha)}"' if alpha < 1 else ""
    sw = _f(max(width, 0.5))
    if kind in ("FilledArrow", "Arrow", "SharpArrow", "FilledSharpArrow"):
        fill = color if kind.startswith("Filled") else "#FFFFFF"
        return (f'<polygon points="{_f(tx)},{_f(ty)} {_f(bx + px * W)},{_f(by + py * W)} {_f(bx - px * W)},{_f(by - py * W)}" '
                f'fill="{fill}" stroke="{color}" stroke-width="{sw}" stroke-linejoin="miter"{op}/>')
    if kind == "StickArrow":
        return (f'<polyline points="{_f(bx + px * W)},{_f(by + py * W)} {_f(tx)},{_f(ty)} {_f(bx - px * W)},{_f(by - py * W)}" '
                f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="miter"{op}/>')
    if kind in ("FilledBall", "Ball"):
        r = L * 0.35
        cx, cy = tx - ux * r, ty - uy * r
        fill = color if kind.startswith("Filled") else "#FFFFFF"
        return f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="{fill}" stroke="{color}" stroke-width="{sw}"{op}/>'
    if kind in ("FilledDiamond", "Diamond"):
        mx, my = tx - ux * L / 2, ty - uy * L / 2
        fill = color if kind.startswith("Filled") else "#FFFFFF"
        return (f'<polygon points="{_f(tx)},{_f(ty)} {_f(mx + px * W)},{_f(my + py * W)} {_f(bx)},{_f(by)} '
                f'{_f(mx - px * W)},{_f(my - py * W)}" fill="{fill}" stroke="{color}" stroke-width="{sw}"{op}/>')
    if kind in ("NegativeControls", "DimensionArrow", "Bar"):
        W2 = L * 0.5
        return (f'<line x1="{_f(tx + px * W2)}" y1="{_f(ty + py * W2)}" x2="{_f(tx - px * W2)}" y2="{_f(ty - py * W2)}" '
                f'stroke="{color}" stroke-width="{sw}"{op}/>')
    return ""


# ---------------------------------------------------------------------------
# text layout
# ---------------------------------------------------------------------------

def layout(rich: rtf.RichText, max_width: float | None):
    """Break paragraphs into lines -> [(runs, line_height, line_width, align)]."""
    lines = []
    for p in rich.paragraphs:
        runs = p.runs or [rtf.Run("")]
        lh = max(line_height(r.font, r.size) for r in runs)
        if max_width is None:
            lw = sum(text_width(r.text, r.font, r.size, r.bold, r.italic) for r in runs)
            lines.append((runs, lh, lw, p.align))
            continue
        # word-wrap across runs
        cur, cur_w = [], 0.0
        tokens = []
        for r in runs:
            for tok in re.findall(r"\S+\s*|\s+", r.text) or [""]:
                # split CJK into characters so they can wrap anywhere
                if re.search(r"[⺀-鿿가-힯]", tok):
                    tokens += [(r, ch) for ch in tok]
                else:
                    tokens.append((r, tok))
        for r, tok in tokens:
            tw = text_width(tok, r.font, r.size, r.bold, r.italic)
            if cur and cur_w + text_width(tok.rstrip(), r.font, r.size, r.bold, r.italic) > max_width + 0.5:
                lines.append((_merge(cur), lh, _width(cur), p.align))
                cur, cur_w = [], 0.0
                tok = tok.lstrip()
                tw = text_width(tok, r.font, r.size, r.bold, r.italic)
            cur.append((r, tok))
            cur_w += tw
        lines.append((_merge(cur), lh, _width(cur), p.align))
    return lines


def _merge(items):
    out = []
    for r, tok in items:
        if out and out[-1][0] is r:
            out[-1] = (r, out[-1][1] + tok)
        else:
            out.append((r, tok))
    res = []
    for k, (r, t) in enumerate(out):
        if k == len(out) - 1:
            t = t.rstrip()
        res.append(rtf.Run(t, r.font, r.size, r.color, r.bold, r.italic, r.underline, r.strike, r.baseline,
                           r.background, r.kern))
    return res


def _width(items):
    runs = _merge(items)
    return sum(text_width(r.text, r.font, r.size, r.bold, r.italic) for r in runs)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pdf_to_png(data: bytes, scale: float) -> bytes:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    page = pdf[0]
    bm = page.render(scale=scale, may_draw_forms=True)
    im = bm.to_pil()
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def to_svg(gf: gio.GraffleFile, sheet: int = 0, margin: float = 10, **kw) -> str:
    r = SVGRenderer(gf, sheet, **kw)
    return r.render(r.bbox(margin))


def to_png(gf: gio.GraffleFile, out: str | None = None, sheet: int = 0, scale: float = 2.0,
           margin: float = 10, max_pixels: int = 6000) -> bytes:
    import cairosvg
    r = SVGRenderer(gf, sheet)
    vb = r.bbox(margin)
    svg = r.render(vb)
    s = min(scale, max_pixels / max(vb[2], vb[3], 1))
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(vb[2] * s), output_height=int(vb[3] * s),
                           background_color="white")
    if out:
        with open(out, "wb") as fh:
            fh.write(png)
    return png


def preview_jpeg(gf: gio.GraffleFile, max_side: int = 1024) -> bytes:
    """A QuickLook-style preview.jpeg like the one OmniGraffle embeds."""
    from PIL import Image
    png = to_png(gf, None, 0, scale=2.0)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a .graffle sheet to PNG or SVG")
    ap.add_argument("graffle")
    ap.add_argument("-o", "--out")
    ap.add_argument("--sheet", type=int, default=0)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--all-sheets", action="store_true")
    a = ap.parse_args(argv)
    gf = gio.load(a.graffle)
    sheets = range(len(gf.sheets)) if a.all_sheets else [a.sheet]
    base = a.out or os.path.splitext(a.graffle)[0] + ".png"
    for i in sheets:
        out = base if len(sheets) == 1 else re.sub(r"(\.\w+)$", f"_{i}\\1", base)
        if out.endswith(".svg"):
            open(out, "w").write(to_svg(gf, i))
        else:
            to_png(gf, out, i, a.scale)
        print(out)


if __name__ == "__main__":
    main()
