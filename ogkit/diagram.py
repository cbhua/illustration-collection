"""High-level, theme-aware builder for *editable* OmniGraffle figures.

    from ogkit import Diagram

    d = Diagram(theme="crayon")
    enc = d.box("Encoder", color="blue")
    dec = d.box("Decoder", color="purple").right_of(enc)
    d.arrow(enc, dec, label="h")
    d.container([enc, dec], "Model", color="gray")
    d.save("out/model.graffle")          # + preview.jpeg inside, + out/model.png

Everything produced is native OmniGraffle: real shapes with real (RTF) text, lines
*connected* to shapes (Head/Tail IDs, so they follow when you drag boxes in
OmniGraffle), groups, embedded PDF math/images.  Geometry of lines and containers
is resolved lazily at save time, so you can position nodes after connecting them.

Coordinates are points, origin top-left, y grows downwards.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import math
import os
import plistlib
import re
import shutil
import subprocess
import tempfile

from . import gio, rtf
from .colors import og_color
from .fonts import text_width, line_height
from .theme import Theme

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_KAPPA = 0.5523

SIDES = ("left", "right", "top", "bottom")


# ---------------------------------------------------------------------------
# rich-text mini markup
# ---------------------------------------------------------------------------
_MARK = re.compile(r"(\*\*.+?\*\*|`.+?`|\*.+?\*|\^\{.+?\}|_\{.+?\}|\[[#\w]+\]\{.+?\})", re.S)


def parse_markup(text: str, font: str, size: float, color: str, theme: Theme, bold=False, italic=False):
    """Mini markup → rtf.Run list.

    ``**bold**``  ``*italic*``  ```mono```  ``^{sup}``  ``_{sub}``  ``[red]{coloured}`` / ``[#941100]{...}``
    (colour = palette hue → its text colour, or a text role, or #hex)."""
    runs: list[rtf.Run] = []
    base = rtf.Run("", font, size, color, bold, italic)

    def add(t, **kw):
        if t:
            r = copy.copy(base)
            r.text = t
            for k, v in kw.items():
                setattr(r, k, v)
            runs.append(r)

    pos = 0
    for m in _MARK.finditer(text):
        add(text[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("**"):
            add(tok[2:-2], bold=True)
        elif tok.startswith("`"):
            add(tok[1:-1], font=theme.font("mono"))
        elif tok.startswith("*"):
            add(tok[1:-1], italic=True)
        elif tok.startswith("^{"):
            add(tok[2:-1], baseline="super")
        elif tok.startswith("_{"):
            add(tok[2:-1], baseline="sub")
        else:
            cm = re.match(r"\[([#\w]+)\]\{(.+)\}", tok, re.S)
            add(cm.group(2), color=theme.text_color(cm.group(1)))
        pos = m.end()
    add(text[pos:])
    if not runs:
        add(" ")
        runs[-1].text = ""
    return runs


def measure_runs(runs: list[rtf.Run]) -> tuple[float, float, list[float]]:
    """(width, height) of laid-out unwrapped runs; paragraphs split on newlines."""
    lines: list[list[rtf.Run]] = [[]]
    for r in runs:
        parts = r.text.split("\n")
        for k, part in enumerate(parts):
            if k:
                lines.append([])
            rr = copy.copy(r)
            rr.text = part
            lines[-1].append(rr)
    widths, height = [], 0.0
    for ln in lines:
        w = sum(text_width(r.text, r.font, r.size * (0.7 if r.baseline else 1), r.bold, r.italic) for r in ln)
        h = max((line_height(r.font, r.size) for r in ln), default=0)
        widths.append(w)
        height += h
    return (max(widths) if widths else 0.0), height, widths


def wrap_runs(runs: list[rtf.Run], max_w: float) -> list[rtf.Run]:
    """Insert newlines so no line exceeds ``max_w`` (greedy word wrap)."""
    out: list[rtf.Run] = []
    cur_w = 0.0
    for r in runs:
        pieces = re.findall(r"\n|[^\S\n]+|[⺀-鿿]|[^\s⺀-鿿]+", r.text)
        buf = ""
        for p in pieces:
            if p == "\n":
                buf += p
                cur_w = 0
                continue
            pw = text_width(p, r.font, r.size, r.bold, r.italic)
            if cur_w + pw > max_w and cur_w > 0 and not p.isspace():
                buf = buf.rstrip(" ") + "\n"
                cur_w = 0
            if cur_w == 0 and p.isspace():
                continue
            buf += p
            cur_w += pw
        rr = copy.copy(r)
        rr.text = buf
        out.append(rr)
    return out


# ---------------------------------------------------------------------------
# nodes
# ---------------------------------------------------------------------------
class Node:
    """A placed element.  Simple nodes wrap one ShapedGraphic; compound nodes
    (containers, groups, snippets) wrap several and move together."""

    def __init__(self, d: "Diagram", g: dict | None, kind: str, members: list["Node"] | None = None):
        self.d = d
        self.g = g
        self.kind = kind
        self.members = members or []  # child nodes moved together with this one
        self.attached: list[Node] = []  # e.g. external labels that follow the node
        self.meta: dict = {}

    # ---------------------------------------------------------- geometry
    @property
    def id(self) -> int | None:
        if self.g is not None:
            return self.g["ID"]
        if self.kind == "container":
            return self.meta["frame"].id
        if self.meta.get("layout") is not None:
            return self.meta["layout"].id
        return None

    @property
    def geom(self) -> "Node":
        """The node whose outline lines attach to and layout refers to (a container's frame,
        a badge's square, an instance's frame); the node itself otherwise."""
        if self.kind == "container":
            return self.meta["frame"]
        if self.meta.get("layout") is not None:
            return self.meta["layout"]
        return self

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """Full bounding box including titles / captions / stack copies (used for spacing and
        container fitting)."""
        x, y, w, h = self.bounds
        x0, y0, x1, y1 = x, y, x + w, y + h
        for a in self.attached:
            ax, ay, aw, ah = a.extent
            x0, y0, x1, y1 = min(x0, ax), min(y0, ay), max(x1, ax + aw), max(y1, ay + ah)
        return (x0, y0, x1 - x0, y1 - y0)

    @property
    def box(self) -> tuple[float, float, float, float]:
        """Layout box: the frame of containers/badges, else the bounds."""
        g = self.geom
        return g.bounds if g is not self else self.bounds

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        if self.g is not None and "Bounds" in self.g:
            return gio.parse_rect(self.g["Bounds"])
        xs, ys, xe, ye = [], [], [], []
        for m in self.members + self.attached:
            x, y, w, h = m.bounds
            xs.append(x)
            ys.append(y)
            xe.append(x + w)
            ye.append(y + h)
        if not xs:
            return (0, 0, 0, 0)
        return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))

    def _set_bounds(self, x, y, w, h):
        self.g["Bounds"] = gio.fmt_rect(x, y, w, h)

    # geometry accessors refer to the *layout box* (frame without title)
    x = property(lambda s: s.box[0])
    y = property(lambda s: s.box[1])
    w = property(lambda s: s.box[2])
    h = property(lambda s: s.box[3])
    left = property(lambda s: s.box[0])
    top = property(lambda s: s.box[1])
    right = property(lambda s: s.box[0] + s.box[2])
    bottom = property(lambda s: s.box[1] + s.box[3])
    cx = property(lambda s: s.box[0] + s.box[2] / 2)
    cy = property(lambda s: s.box[1] + s.box[3] / 2)

    @property
    def center(self):
        return (self.cx, self.cy)

    def anchor(self, side: str, t: float = 0.5) -> tuple[float, float]:
        """Point on the bounding box: side in left/right/top/bottom/center; ``t`` is the
        relative position along that side (0 = top/left end)."""
        x, y, w, h = self.box
        if side == "left":
            return (x, y + h * t)
        if side == "right":
            return (x + w, y + h * t)
        if side == "top":
            return (x + w * t, y)
        if side == "bottom":
            return (x + w * t, y + h)
        return (x + w / 2, y + h / 2)

    # ---------------------------------------------------------- movement
    def move(self, dx: float, dy: float) -> "Node":
        if self.g is not None and "Bounds" in self.g:
            x, y, w, h = self.bounds
            self._set_bounds(x + dx, y + dy, w, h)
        for m in self.members:
            m.move(dx, dy)
        for a in self.attached:
            a.move(dx, dy)
        return self

    def place(self, x=None, y=None, *, left=None, right=None, top=None, bottom=None, cx=None, cy=None) -> "Node":
        """Absolute positioning by any edge/centre of the layout box."""
        bx, by, bw, bh = self.box
        dx = dy = 0.0
        if x is not None or left is not None:
            dx = (x if x is not None else left) - bx
        elif right is not None:
            dx = right - (bx + bw)
        elif cx is not None:
            dx = cx - (bx + bw / 2)
        if y is not None or top is not None:
            dy = (y if y is not None else top) - by
        elif bottom is not None:
            dy = bottom - (by + bh)
        elif cy is not None:
            dy = cy - (by + bh / 2)
        return self.move(dx, dy)

    def _rel(self, other: "Node", side: str, gap, align: str):
        """Place next to ``other``: spacing between *extents* (titles included),
        alignment between *layout boxes*."""
        gap = self.d.theme.spacing["gap"] if gap is None else gap
        ox, oy, ow, oh = other.extent
        sx, sy, sw, sh = self.extent
        if side == "right":
            self.move(ox + ow + gap - sx, 0)
        elif side == "left":
            self.move(ox - gap - (sx + sw), 0)
        elif side == "below":
            self.move(0, oy + oh + gap - sy)
        elif side == "above":
            self.move(0, oy - gap - (sy + sh))
        if side in ("right", "left"):
            if align == "center":
                self.place(cy=other.cy)
            elif align == "top":
                self.place(top=other.top)
            elif align == "bottom":
                self.place(bottom=other.bottom)
        else:
            if align == "center":
                self.place(cx=other.cx)
            elif align == "left":
                self.place(left=other.left)
            elif align == "right":
                self.place(right=other.right)
        return self

    def right_of(self, other: "Node", gap=None, align="center"):
        return self._rel(other, "right", gap, align)

    def left_of(self, other: "Node", gap=None, align="center"):
        return self._rel(other, "left", gap, align)

    def below(self, other: "Node", gap=None, align="center"):
        return self._rel(other, "below", gap, align)

    def above(self, other: "Node", gap=None, align="center"):
        return self._rel(other, "above", gap, align)

    def resize(self, w=None, h=None, anchor="center") -> "Node":
        """Change size keeping ``anchor`` fixed: center | topleft | top | left | right | bottom |
        topright | bottomleft | bottomright."""
        x, y, bw, bh = self.bounds
        nw, nh = w or bw, h or bh
        fx = {"center": 0.5, "top": 0.5, "bottom": 0.5, "left": 0, "topleft": 0, "bottomleft": 0,
              "right": 1, "topright": 1, "bottomright": 1}[anchor]
        fy = {"center": 0.5, "left": 0.5, "right": 0.5, "top": 0, "topleft": 0, "topright": 0,
              "bottom": 1, "bottomleft": 1, "bottomright": 1}[anchor]
        x, y = x + (bw - nw) * fx, y + (bh - nh) * fy
        self._set_bounds(x, y, nw, nh)
        return self

    def __repr__(self):
        x, y, w, h = self.bounds
        return f"<{self.kind} #{self.id} ({x:.0f},{y:.0f} {w:.0f}x{h:.0f})>"


class Line:
    def __init__(self, d, g, src, dst, spec):
        self.d, self.g, self.src, self.dst, self.spec = d, g, src, dst, spec
        self.label: Node | None = None

    @property
    def id(self):
        return self.g["ID"]


# ---------------------------------------------------------------------------
# the diagram
# ---------------------------------------------------------------------------
class Diagram:
    def __init__(self, theme: str | dict = "crayon", title: str = "Canvas 1", theme_overrides: dict | None = None):
        self.theme = Theme.load(theme, theme_overrides)
        self.title = title
        self._next_id = 2
        self.items: list[tuple[tuple, dict, object]] = []  # (zkey, graphic, owner)
        self._order = 0
        self.lines: list[Line] = []
        self.containers: list[Node] = []
        self.assets: dict[str, bytes] = {}
        self.image_list: list[str] = []
        self._image_counter = 1
        self._image_hash: dict[str, int] = {}
        self.export_shapes: dict[str, dict] = {}
        self.base_doc: dict | None = None  # when editing an existing file
        self.sheet_index = 0

    # ------------------------------------------------------------ internals
    def _id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _add(self, g: dict, z: str = "node", owner=None):
        zrank = {"back": -1, "container": 0, "line": 1, "under": 1.5, "node": 2, "text": 3, "front": 4}[z]
        self._order += 1
        self.items.append(((zrank, 0, self._order), g, owner))
        return g

    def _style(self, fill=None, alpha=1.0, stroke=None, width=1.0, radius=0.0, dash=None, shadow=False):
        st = {"fill": {}, "shadow": {"Draws": "NO"}, "stroke": {}}
        if fill is None:
            st["fill"]["Draws"] = "NO"
        else:
            st["fill"]["Color"] = og_color(fill, alpha)
        if stroke is None:
            st["stroke"]["Draws"] = "NO"
        else:
            st["stroke"]["Color"] = og_color(stroke)
            if width != 1:
                st["stroke"]["Width"] = float(width)
        if radius:
            st["stroke"]["CornerRadius"] = float(radius)
        if dash:
            st["stroke"]["Pattern"] = int(self.theme.line.get("dash_pattern", 24) if dash is True else dash)
        if shadow:
            st["shadow"] = {"Draws": "YES", "Color": og_color("#000000", 0.25), "ShadowVector": "{0, 1}",
                            "Fuzziness": 3.0}
        return st

    def _text_dict(self, runs, align="center", pad_x=0.0, pad_y=0.0):
        return {"Text": rtf.from_runs(runs, align), "Pad": float(pad_x), "VerticalPad": float(pad_y)}

    def _runs(self, text, size="label", color=None, font=None, bold=False, italic=False, markup=True):
        th = self.theme
        fname = th.font(font or th.data.get("default_font", "sans"))
        sz = th.size(size)
        col = th.text_color(color) if color else th.text_color("primary")
        if markup:
            return parse_markup(text, fname, sz, col, th, bold, italic)
        return [rtf.Run(text, fname, sz, col, bold, italic)]

    # ------------------------------------------------------------- primitives
    def shape(self, x=0, y=0, w=60, h=30, *, shape="Rectangle", fill=None, alpha=1.0, stroke=None,
              stroke_width=1.0, radius=0.0, dash=None, shadow=False, text=None, size="label",
              text_color=None, font=None, bold=False, italic=False, align="center", valign="middle",
              pad_x=4, pad_y=2, rotation=None, opacity=None, name=None, z="node", markup=True,
              wrap=True) -> Node:
        """Low-level: any OmniGraffle shape with explicit colours (#hex)."""
        g = {"Class": "ShapedGraphic", "ID": self._id(), "Bounds": gio.fmt_rect(x, y, w, h),
             "Style": self._style(fill, alpha, stroke, stroke_width, radius, dash, shadow)}
        if shape and shape != "Rectangle":
            g["Shape"] = shape
        if text is not None and text != "":
            runs = text if isinstance(text, list) else self._runs(text, size, text_color, font, bold, italic, markup)
            g["Text"] = self._text_dict(runs, align, pad_x, pad_y)
            g["FontInfo"] = {"Font": runs[0].font, "Size": runs[0].size, "Color": og_color(runs[0].color)}
            if valign != "middle":
                g["TextPlacement"] = {"top": 0, "bottom": 2}[valign]
            if not wrap:
                g["Wrap"] = "NO"
        else:
            g["Text"] = {"TextAlongPathGlyphAnchor": "center"}
        if rotation:
            g["Rotation"] = float(rotation)
        if opacity is not None:
            g["Opacity"] = float(opacity)
        if name:
            g["Name"] = name
        self._add(g, z)
        return Node(self, g, "shape")

    def text(self, text: str, x=0, y=0, *, size="label", color="secondary", font=None, bold=False,
             italic=False, align="center", width=None, anchor="topleft", markup=True, z="text",
             rotation=None) -> Node:
        """Free text label (auto-sized, like OmniGraffle's text tool).  ``width`` wraps.
        ``anchor`` says what (x, y) refers to: topleft | center | top | bottom | left | right."""
        runs = self._runs(text, size, color, font, bold, italic, markup)
        if width:
            runs = wrap_runs(runs, width)
        tw, th_, _ = measure_runs(runs)
        tw = math.ceil(tw + 0.5)
        th_ = math.ceil(th_)
        if width and align != "left":
            tw = max(tw, 0)
        ox, oy = _anchor_offset(anchor, tw, th_)
        g = {"Class": "ShapedGraphic", "ID": self._id(), "Bounds": gio.fmt_rect(x - ox, y - oy, tw, th_),
             "Style": self._style(None, stroke=None), "FitText": "YES", "Flow": "Resize", "Wrap": "NO",
             "Text": self._text_dict(runs, align, 0, 0),
             "FontInfo": {"Font": runs[0].font, "Size": runs[0].size, "Color": og_color(runs[0].color)}}
        if rotation:
            g["Rotation"] = float(rotation)
        self._add(g, z)
        n = Node(self, g, "text")
        n.meta["runs"] = runs
        return n

    def box(self, text: str = "", x=0, y=0, w=None, h=None, *, color="blue", tone=None, style="box",
            size=None, text_color=None, font=None, bold=False, italic=False, align="center",
            radius=None, stroke_width=None, dash=None, shadow=False, min_w=None, min_h=None,
            fill=None, stroke=None, shape="Rectangle", markup=True, z=None, name=None,
            wrap_width=None, valign="middle") -> Node:
        """A themed element: pastel fill + dark stroke of ``color`` (palette hue).
        Width/height auto-fit the text unless given.  ``style`` picks a component preset
        from the theme (box | card | tag | chip | frame)."""
        th = self.theme
        c = th.comp(style)
        if z is None:  # frames are backgrounds: keep connectors visible on top of them
            z = "container" if style == "frame" and not text else "node"
        color = color or c.get("color", "blue")
        tone = tone or c.get("tone", "light")
        sw = th.swatch(color, tone)
        fill_c = fill if fill is not None else c.get("fill", sw["fill"])
        alpha = 1.0 if (fill is not None or "fill" in c) else sw["alpha"]
        stroke_c = stroke if stroke is not None else c.get("stroke", sw["stroke"])
        size = size or c.get("size", "label")
        font = font or c.get("font")
        tcol = text_color or (sw["text"] if c.get("text", "dark") == "dark" else th.text_color(c.get("text")))
        pad_x, pad_y = c.get("pad_x", 6), c.get("pad_y", 3)
        runs = self._runs(text, size, tcol, font, bold, italic, markup) if text else None
        if runs and wrap_width:
            runs = wrap_runs(runs, wrap_width)
        if runs:
            tw, tht, _ = measure_runs(runs)
        else:
            tw, tht = 0, 0
        if w is not None and runs and tw + 2 * pad_x + 1 > w:
            pad_x = max(0.5, (w - tw - 1) / 2)  # fixed width: trade padding for no wrap
        w = w if w is not None else max(math.ceil(tw + 2 * pad_x + 1), min_w or 0, 12)
        h = h if h is not None else max(math.ceil(tht + 2 * pad_y), min_h or 0, 10)
        n = self.shape(x, y, w, h, shape=shape, fill=fill_c, alpha=alpha, stroke=stroke_c,
                       stroke_width=stroke_width if stroke_width is not None else c.get("stroke_width", 1),
                       radius=radius if radius is not None else c.get("radius", 0), dash=dash, shadow=shadow,
                       text=runs, align=align, pad_x=pad_x, pad_y=0, z=z, name=name, valign=valign)
        n.kind = "box"
        n.meta.update(color=color, style=style)
        return n

    def tag(self, text, x=0, y=0, *, color=None, **kw) -> Node:
        """Small mono chip, e.g. `</>`, file names, tensor shapes."""
        return self.box(text, x, y, style="tag", color=color or self.theme.comp("tag").get("color", "gray"), **kw)

    def circle(self, x=0, y=0, d=10, *, color="blue", tone="light", text=None, size="small", fill=None,
               stroke=None, stroke_width=1.0, text_color=None, cx=None, cy=None, z="node") -> Node:
        """Node marker / dot.  Give ``cx, cy`` to place by centre."""
        sw = self.theme.swatch(color, tone)
        if cx is not None:
            x, y = cx - d / 2, cy - d / 2
        n = self.shape(x, y, d, d, shape="Circle", fill=fill if fill is not None else sw["fill"],
                       alpha=1.0 if fill is not None else sw["alpha"],
                       stroke=stroke if stroke is not None else sw["stroke"], stroke_width=stroke_width,
                       text=text, size=size, text_color=text_color or sw["text"], pad_x=0, z=z)
        n.kind = "circle"
        return n

    def triangle(self, cx, cy, size=8, *, direction="up", color="blue", tone="light", **kw) -> Node:
        """Equilateral-ish marker triangle centred at (cx, cy); direction up | down | left | right
        (linehaul ▽ / backhaul △ in routing figures)."""
        rot = {"right": None, "down": 90, "left": 180, "up": 270}[direction]
        n = self.polygon("HorizontalTriangle", cx - size / 2, cy - size / 2, size, size, color=color, tone=tone,
                         rotation=rot, **kw)
        n.kind = "triangle"
        return n

    def polygon(self, kind: str, x, y, w, h, *, color="blue", tone="light", rotation=None, **kw) -> Node:
        """Built-in shapes: HorizontalTriangle, VerticalTriangle, RightTriangle, Diamond,
        Parallelogram, AdjustableStar, AdjustableArrow, Circle, Rectangle."""
        sw = self.theme.swatch(color, tone)
        kw.setdefault("fill", sw["fill"])
        kw.setdefault("alpha", sw["alpha"])
        kw.setdefault("stroke", sw["stroke"])
        n = self.shape(x, y, w, h, shape=kind, rotation=rotation, **kw)
        if kind == "AdjustableArrow":
            n.g["ShapeData"] = {"width": min(h, w) * 0.9, "ratio": 0.45}
        if kind == "AdjustableStar":
            n.g["ShapeData"] = {}
        return n

    # ----------------------------------------------------------- containers
    def container(self, children: list[Node], title: str | None = None, *, color="blue", style="container",
                  pad=None, pad_top=None, pad_bottom=None, pad_x=None, title_pos=None, title_size=None, title_color=None, dash=None,
                  fill=None, tone=None, radius=None, stroke_width=None, min_w=None, min_h=None, w=None, h=None,
                  title_bold=None, stroke=None) -> Node:
        """A frame drawn *behind* ``children`` (any nodes), with an optional title.
        title_pos: top (centred above, default) | top-left | inside-top | inside-top-left |
        bottom (centred below) | none.  Re-fitted automatically at save time."""
        th = self.theme
        c = th.comp(style)
        color = color or c.get("color", "blue")
        sw = th.swatch(color, tone or "light")
        if fill is None:
            fill = c.get("fill", "#FFFFFF")
            alpha = 1.0
            if tone:
                fill, alpha = sw["fill"], sw["alpha"]
        else:
            alpha = 1.0
        frame = self.shape(0, 0, 10, 10, fill=fill, alpha=alpha, stroke=stroke or sw["stroke"],
                           stroke_width=stroke_width if stroke_width is not None else c.get("stroke_width", 1),
                           radius=radius if radius is not None else c.get("radius", 6), dash=dash, z="container")
        title_node = None
        title_pos = title_pos or c.get("title_pos", "top")
        if title and title_pos != "none":
            title_node = self.text(title, size=title_size or c.get("title_size", "heading"),
                                   font=c.get("title_font", "sans"),
                                   color=title_color or sw["text"],
                                   bold=c.get("title_bold", False) if title_bold is None else title_bold)
        node = Node(self, None, "container", members=list(children))
        node.meta.update(frame=frame, title=title_node, pad=c.get("pad", 10) if pad is None else pad,
                         pad_top=pad_top, pad_bottom=pad_bottom, pad_x=pad_x, title_pos=title_pos, gap=c.get("title_gap", 3), min_w=w or min_w,
                         min_h=h or min_h)
        node.attached = [frame] + ([title_node] if title_node else [])
        self.containers.append(node)
        self._fit_container(node)
        return node

    def panel(self, children, title=None, **kw) -> Node:
        """Lighter, smaller sub-container (white with grey outline by default)."""
        kw.setdefault("style", "panel")
        kw.setdefault("color", self.theme.comp("panel").get("color", "gray"))
        return self.container(children, title, **kw)

    def _fit_container(self, node: Node):
        m = node.meta
        frame, title = m["frame"], m["title"]
        xs = [c.extent for c in node.members]
        if not xs:
            return
        x0 = min(b[0] for b in xs)
        y0 = min(b[1] for b in xs)
        x1 = max(b[0] + b[2] for b in xs)
        y1 = max(b[1] + b[3] for b in xs)
        pad = m["pad"]
        pt = m["pad_top"] if m["pad_top"] is not None else pad
        pb = m.get("pad_bottom") if m.get("pad_bottom") is not None else pad
        px = m.get("pad_x") if m.get("pad_x") is not None else pad
        if title is not None and m["title_pos"].startswith("inside-top"):
            pt += title.h + m["gap"]
        fx, fy, fw, fh = x0 - px, y0 - pt, (x1 - x0) + 2 * px, (y1 - y0) + pt + pb
        if m.get("min_w") and fw < m["min_w"]:
            fx -= (m["min_w"] - fw) / 2
            fw = m["min_w"]
        if m.get("min_h") and fh < m["min_h"]:
            fy -= (m["min_h"] - fh) / 2  # grow symmetrically: content stays vertically centred
            fh = m["min_h"]
        frame._set_bounds(fx, fy, fw, fh)
        if title is not None:
            tp = m["title_pos"]
            g = m["gap"]
            if tp == "top":
                title.place(cx=fx + fw / 2, bottom=fy - g)
            elif tp == "top-left":
                title.place(left=fx + 2, bottom=fy - g)
            elif tp == "inside-top":
                title.place(cx=fx + fw / 2, top=fy + pad / 2)
            elif tp == "inside-top-left":
                title.place(left=fx + pad, top=fy + pad / 2)
            elif tp == "bottom":
                title.place(cx=fx + fw / 2, top=fy + fh + g)

    # ---------------------------------------------------------------- lines
    def line(self, src, dst, *, route="auto", src_side="auto", dst_side="auto", via=None, color=None,
             width=None, head="theme", tail=None, head_scale=None, dash=None, label=None,
             label_pos=None, label_size=None, label_color=None, label_bg=None, label_offset=(0, 0),
             label_side="auto", src_t=0.5, dst_t=0.5, src_at=None, dst_at=None, src_gap=None,
             dst_gap=None, curve=0.35, corner_radius=None, z="line") -> Line:
        """Connector between two nodes (or (x, y) points).

        route: straight | ortho | curved | auto (ortho if sides are not facing, else straight)
        src_side / dst_side: left | right | top | bottom | auto
        via: list of (x, y) waypoints (ortho/straight polyline)
        head / tail: FilledArrow | StickArrow | Arrow | FilledBall | Ball | FilledDiamond | Diamond | None
        dash: True (theme pattern) or an OmniGraffle Pattern number
        src_t / dst_t: port position along the side, 0..1 (clamped);
        src_at / dst_at: absolute port coordinate along the side (y for left/right, x for top/bottom)
        src_gap / dst_gap: leave this many pt between line end and the node (default 3 for text labels)
        label_pos: 0..1 along the line; default = middle of the longest segment
        """
        th = self.theme.line
        g = {"Class": "LineGraphic", "ID": self._id(), "Points": [], "Style": {
            "fill": {"Draws": "NO"}, "shadow": {"Draws": "NO"},
            "stroke": {"Color": og_color(self._line_color(color)), "Legacy": False}}}
        st = g["Style"]["stroke"]
        wv = th.get("width", 1) if width is None else width
        if wv != 1:
            st["Width"] = float(wv)
        if head == "theme":
            head = th.get("head", "FilledArrow")
        if head:
            st["HeadArrow"] = head
            st["HeadScale"] = float(head_scale if head_scale is not None else th.get("head_scale", 0.75))
        if tail:
            st["TailArrow"] = tail
            st["TailScale"] = float(head_scale if head_scale is not None else th.get("head_scale", 0.75))
        if dash:
            st["Pattern"] = int(th.get("dash_pattern", 24) if dash is True else dash)
        spec = dict(route=route, src_side=src_side, dst_side=dst_side, via=via or [], src_t=src_t, dst_t=dst_t,
                    src_at=src_at, dst_at=dst_at, curve=curve, corner_radius=corner_radius,
                    src_gap=src_gap if src_gap is not None else (3.0 if isinstance(src, Node) and src.kind == "text" else 0.0),
                    dst_gap=dst_gap if dst_gap is not None else (3.0 if isinstance(dst, Node) and dst.kind == "text" else 0.0))
        ln = Line(self, g, src, dst, spec)
        if isinstance(src, Node) and src.id is not None:
            g["Tail"] = {"ID": src.id}
        if isinstance(dst, Node) and dst.id is not None:
            g["Head"] = {"ID": dst.id}
        self._add(g, z, ln)
        self.lines.append(ln)
        if label:
            tn = self.text(label, size=label_size or th.get("label_size", "small"),
                           color=label_color or "secondary", anchor="center")
            if label_bg:
                tn.g["Style"]["fill"] = {"Color": og_color("#FFFFFF" if label_bg is True else label_bg)}
            tn.g["Line"] = {"ID": g["ID"], "Position": float(label_pos if label_pos is not None else 0.5),
                            "RotationType": 0}
            tn.meta["label_auto_pos"] = label_pos is None
            tn.meta["label_offset"] = label_offset
            tn.meta["label_side"] = label_side
            ln.label = tn
        return ln

    def arrow(self, src, dst, **kw) -> Line:
        return self.line(src, dst, **kw)

    def fan_out(self, src, dsts: list, *, side="right", bus=None, **kw) -> list[Line]:
        """One source to many targets through a shared bus (comb) — e.g. planner -> sub-tasks.
        ``bus`` = x (or y for vertical) of the shared segment; default halfway."""
        lines = []
        if side in ("right", "left"):
            sgn = 1 if side == "right" else -1
            edge = src.right if side == "right" else src.left
            near = min(t.left for t in dsts) if side == "right" else max(t.right for t in dsts)
            bx = bus if bus is not None else (edge + near) / 2
            for t in dsts:
                lines.append(self.line(src, t, src_side=side, dst_side="left" if sgn > 0 else "right",
                                       src_at=src.cy, via=[(bx, src.cy), (bx, t.cy)], route="ortho", **kw))
        else:
            edge = src.bottom if side == "bottom" else src.top
            near = min(t.top for t in dsts) if side == "bottom" else max(t.bottom for t in dsts)
            by = bus if bus is not None else (edge + near) / 2
            for t in dsts:
                lines.append(self.line(src, t, src_side=side, dst_side="top" if side == "bottom" else "bottom",
                                       src_at=src.cx, via=[(src.cx, by), (t.cx, by)], route="ortho", **kw))
        return lines

    def fan_in(self, srcs: list, dst, *, side="left", bus=None, **kw) -> list[Line]:
        """Many sources into one target through a shared bus; ``side`` is the target side."""
        lines = []
        if side in ("left", "right"):
            far = max(s_.right for s_ in srcs) if side == "left" else min(s_.left for s_ in srcs)
            edge = dst.left if side == "left" else dst.right
            bx = bus if bus is not None else (edge + far) / 2
            for s_ in srcs:
                lines.append(self.line(s_, dst, src_side="right" if side == "left" else "left", dst_side=side,
                                       dst_at=dst.cy, via=[(bx, s_.cy), (bx, dst.cy)], route="ortho", **kw))
        else:
            far = max(s_.bottom for s_ in srcs) if side == "top" else min(s_.top for s_ in srcs)
            edge = dst.top if side == "top" else dst.bottom
            by = bus if bus is not None else (edge + far) / 2
            for s_ in srcs:
                lines.append(self.line(s_, dst, src_side="bottom" if side == "top" else "top", dst_side=side,
                                       dst_at=dst.cx, via=[(s_.cx, by), (dst.cx, by)], route="ortho", **kw))
        return lines

    def connect_chain(self, nodes: list[Node], **kw) -> list[Line]:
        return [self.line(a, b, **kw) for a, b in zip(nodes, nodes[1:])]

    def _line_color(self, c):
        """hue -> its stroke colour; text role; '#hex'; any of these may carry '@alpha'."""
        if c is None:
            return self.theme.line["color"]
        alpha = ""
        if "@" in c:
            c, a = c.split("@", 1)
            alpha = "@" + a
        if c.startswith("#"):
            return c + alpha
        if c in self.theme.data["palette"]:
            return self.theme.swatch(c)["stroke"] + alpha
        return self.theme.text_color(c) + alpha

    # ------------------------------------------------------------ images / math
    def _register_image(self, data: bytes, ext: str) -> int:
        h = hashlib.sha1(data).hexdigest()
        if h in self._image_hash:
            return self._image_hash[h]
        iid = self._image_counter
        self._image_counter += 1
        name = f"image{iid}.{ext.lstrip('.').lower()}"
        self.assets[name] = data
        self.image_list.insert(0, name)
        self._image_hash[h] = iid
        return iid

    def image(self, path_or_bytes, x=0, y=0, w=None, h=None, *, ext=None, stroke=None, radius=0.0,
              shape="Rectangle", z="node", name=None) -> Node:
        """Embed PNG/JPEG/PDF/TIFF.  Size defaults to the natural size (PDF in pt, bitmaps at 72 dpi
        scaled so the long side is 100 pt) keeping aspect ratio when only w or h is given."""
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytes(path_or_bytes)
            ext = ext or "png"
        else:
            data = open(path_or_bytes, "rb").read()
            ext = ext or os.path.splitext(path_or_bytes)[1].lstrip(".")
        nw, nh = natural_size(data, ext)
        if w is None and h is None:
            w, h = nw, nh
        elif w is None:
            w = h * nw / nh
        elif h is None:
            h = w * nh / nw
        iid = self._register_image(data, ext)
        g = {"Class": "ShapedGraphic", "ID": self._id(), "Bounds": gio.fmt_rect(x, y, w, h),
             "ImageID": iid, "StretchImage": True, "ManualSizeImage": "NO", "Scaling": 1,
             "Style": self._style(None, stroke=stroke, radius=radius),
             "Text": {"TextAlongPathGlyphAnchor": "center"}}
        if shape != "Rectangle":
            g["Shape"] = shape
        if name:
            g["Name"] = name
        self._add(g, z)
        n = Node(self, g, "image")
        return n

    def math(self, latex: str, x=0, y=0, *, size=None, color=None, anchor="topleft", display=False) -> Node:
        """LaTeX → vector PDF embedded as an image (like LaTeXiT, which this corpus uses).
        ``latex`` is math-mode content, e.g. r"\\mathcal{L}_{\\text{RL}}" (no $ needed)."""
        sz = self.theme.size(size or "label")
        col = self.theme.text_color(color) if color else self.theme.text_color("primary")
        pdf = latex_pdf(latex, col, display)
        nw, nh = natural_size(pdf, "pdf")
        k = sz / 10.0  # LaTeX renders at 10 pt
        w, h = nw * k, nh * k
        ox, oy = _anchor_offset(anchor, w, h)
        n = self.image(pdf, x - ox, y - oy, w, h, ext="pdf")
        n.kind = "math"
        n.g["Name"] = "LaTeX: " + latex[:200]
        return n

    # -------------------------------------------------------- groups / library
    def group(self, nodes: list[Node], name: str | None = None) -> Node:
        """Make an OmniGraffle group (moves/selects as one in the app)."""
        n = Node(self, None, "group", members=list(nodes))
        n.meta["group_name"] = name
        n.meta["is_og_group"] = True
        self._groups = getattr(self, "_groups", [])
        self._groups.append(n)
        return n

    def snippet(self, name: str, x=0, y=0, *, recolor: dict | None = None, texts: dict | None = None,
                scale: float = 1.0, width: float | None = None) -> Node:
        """Insert a component from the asset library (library/snippets/<name>.json),
        top-left at (x, y).  ``texts`` maps old label text -> new text; ``recolor`` maps
        '#OLDHEX' -> '#NEWHEX'.  ``scale`` (or a target ``width``) resizes geometry *and* text."""
        from .library import load_snippet
        return load_snippet(self, name, x, y, recolor=recolor, texts=texts, scale=scale, width=width)

    def icon(self, name: str, x=0, y=0, size=12, *, color="blue", tone="solid", fill=None) -> Node:
        """Vector icon from the library (custom OmniGraffle shapes extracted from your files)."""
        from .library import icon_def
        es = icon_def(name)
        aspect = es.pop("aspect", 1.0)
        self.export_shapes[es["ShapeName"]] = es
        sw = self.theme.swatch(color, "light")
        n = self.shape(x, y, size, size * aspect, shape=es["ShapeName"],
                       fill=fill or (sw[self.theme.data.get("icon_color", "text")] if tone == "solid" else sw["fill"]),
                       stroke=None)
        n.kind = "icon"
        n.g["Name"] = name
        return n

    # --------------------------------------------------------------- layout
    def row(self, nodes: list[Node], gap=None, align="center", x=None, y=None) -> list[Node]:
        gap = self.theme.spacing["gap"] if gap is None else gap
        if x is not None or y is not None:
            nodes[0].place(x=x, y=y)
        for a, b in zip(nodes, nodes[1:]):
            b.right_of(a, gap, align)
        return nodes

    def column(self, nodes: list[Node], gap=None, align="center", x=None, y=None) -> list[Node]:
        gap = self.theme.spacing["gap"] if gap is None else gap
        if x is not None or y is not None:
            nodes[0].place(x=x, y=y)
        for a, b in zip(nodes, nodes[1:]):
            b.below(a, gap, align)
        return nodes

    def grid(self, nodes: list[Node], cols: int, gap_x=None, gap_y=None, x=0, y=0) -> list[Node]:
        gx = self.theme.spacing["gap"] if gap_x is None else gap_x
        gy = gx if gap_y is None else gap_y
        cw = max(n.w for n in nodes)
        rh = max(n.h for n in nodes)
        for i, n in enumerate(nodes):
            r, c = divmod(i, cols)
            n.place(cx=x + c * (cw + gx) + cw / 2, cy=y + r * (rh + gy) + rh / 2)
        return nodes

    def same_size(self, nodes: list[Node], w=True, h=True):
        mw = max(n.w for n in nodes)
        mh = max(n.h for n in nodes)
        for n in nodes:
            if n.g is not None:
                n.resize(mw if w else None, mh if h else None)
        return nodes

    def align(self, nodes: list[Node], how="cy", to=None):
        """Align nodes: how in left|right|top|bottom|cx|cy; ``to`` = value or first node's."""
        ref = to if to is not None else getattr(nodes[0], how)
        for n in nodes:
            n.place(**{how: ref})
        return nodes

    def distribute(self, nodes: list[Node], axis="x", start=None, end=None):
        nodes = sorted(nodes, key=lambda n: n.cx if axis == "x" else n.cy)
        a = start if start is not None else (nodes[0].cx if axis == "x" else nodes[0].cy)
        b = end if end is not None else (nodes[-1].cx if axis == "x" else nodes[-1].cy)
        for i, n in enumerate(nodes):
            v = a + (b - a) * i / max(1, len(nodes) - 1)
            n.place(**({"cx": v} if axis == "x" else {"cy": v}))
        return nodes

    # ------------------------------------------------------------- resolve
    def _resolve_lines(self):
        cr = float(self.theme.line.get("corner_radius", 5))
        for ln in self.lines:
            pts, ltype = route_line(ln.src, ln.dst, ln.spec)
            from .render import shorten
            if ln.spec.get("src_gap"):
                pts = shorten(pts, ln.spec["src_gap"])
            if ln.spec.get("dst_gap"):
                pts = shorten(pts[::-1], ln.spec["dst_gap"])[::-1]
            st = ln.g["Style"]["stroke"]
            ln.g["Points"] = [gio.fmt_point(*p) for p in pts]
            if ltype == "ortho":
                r_ = cr if ln.spec.get("corner_radius") is None else float(ln.spec["corner_radius"])
                st["LineType"] = 2
                st["CornerRadius"] = r_
                ln.g["LogicalPath"] = {"elements": rounded_path(pts, r_)}
                ln.g["OrthogonalBarAutomatic"] = True
                ln.g["OrthogonalBarPoint"] = "{0, 0}"
                ln.g["OrthogonalBarPosition"] = -1.0
            elif ltype == "curved":
                st["LineType"] = 1
                st["Bezier"] = True
                p0, p1 = pts[0], pts[-1]
                c1, c2 = curve_controls(p0, p1, ln.spec, ln.src, ln.dst)
                ln.g["ControlPoints"] = [gio.fmt_point(c1[0] - p0[0], c1[1] - p0[1]),
                                         gio.fmt_point(c2[0] - p1[0], c2[1] - p1[1])]
                ln.g["Points"] = [gio.fmt_point(*p0), gio.fmt_point(*p1)]
                ln.g["LogicalPath"] = {"elements": [
                    {"element": "MOVETO", "point": gio.fmt_point(*p0)},
                    {"element": "CURVETO", "control1": gio.fmt_point(*c1), "control2": gio.fmt_point(*c2),
                     "point": gio.fmt_point(*p1)}]}
            else:
                ln.g["LogicalPath"] = {"elements": [{"element": "MOVETO" if i == 0 else "LINETO",
                                                     "point": gio.fmt_point(*p)} for i, p in enumerate(pts)]}
            if ln.label is not None:
                lab = ln.label
                if lab.meta.get("label_auto_pos") and len(pts) > 2:
                    segs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
                    k = max(range(len(segs)), key=lambda i: segs[i])
                    lab.g["Line"]["Position"] = (sum(segs[:k]) + segs[k] / 2) / (sum(segs) or 1)
                (px, py), (tx, ty) = point_along(ln.g["LogicalPath"]["elements"], lab.g["Line"]["Position"], True)
                ox, oy = lab.meta.get("label_offset", (0, 0))
                side = lab.meta.get("label_side", "auto")
                if side == "auto":
                    side = "above" if abs(tx) >= abs(ty) else "right"
                gap = 2.0
                if side == "above":
                    lab.place(cx=px + ox, bottom=py - gap + oy)
                elif side == "below":
                    lab.place(cx=px + ox, top=py + gap + oy)
                elif side == "left":
                    lab.place(right=px - gap - 1 + ox, cy=py + oy)
                elif side == "right":
                    lab.place(left=px + gap + 1 + ox, cy=py + oy)
                else:  # on the line, masked by a white background
                    if lab.g["Style"]["fill"].get("Draws") == "NO":
                        lab.g["Style"]["fill"] = {"Color": og_color("#FFFFFF")}
                    if not lab.meta.get("padded"):
                        bx, by, bw, bh = lab.bounds
                        lab._set_bounds(bx - 3, by - 1, bw + 6, bh + 2)
                        lab.g["Text"]["Pad"] = 3.0
                        lab.g["Text"]["VerticalPad"] = 1.0
                        lab.meta["padded"] = True
                    lab.place(cx=px + ox, cy=py + oy)

    def _finalize(self) -> list[dict]:
        for c in self.containers:  # creation order: inner before outer
            self._fit_container(c)
        self._resolve_lines()
        # nested containers: outer frames behind inner ones (depth = how many containers enclose it)
        depth = {}
        for c in self.containers:
            fid = c.meta["frame"].g["ID"]
            depth[fid] = sum(1 for o in self.containers if o is not c and any(m is c for m in _flatten_members(o)))
        items = []
        for (rank, _, order), g, owner in self.items:
            items.append(((rank, depth.get(g.get("ID"), 0) if rank == 0 else 0, order), g, owner))
        items = sorted(items, key=lambda t: t[0])
        graphics = [g for _, g, _ in reversed(items)]  # GraphicsList is front-to-back
        # wrap OmniGraffle groups
        for grp in getattr(self, "_groups", []):
            ids = set()
            for m in _flatten_members(grp):
                if m.g is not None:
                    ids.add(m.g["ID"])
            members = [g for g in graphics if g["ID"] in ids]
            if not members:
                continue
            pos = graphics.index(members[0])
            graphics = [g for g in graphics if g["ID"] not in ids]
            gg = {"Class": "Group", "ID": self._id(), "Graphics": members,
                  "Style": {"fill": {"Draws": "NO"}, "shadow": {"Draws": "NO"}, "stroke": {"Draws": "NO"}}}
            if grp.meta.get("group_name"):
                gg["Name"] = grp.meta["group_name"]
            graphics.insert(min(pos, len(graphics)), gg)
        return graphics

    def bbox(self, graphics=None):
        graphics = graphics if graphics is not None else self._finalize()
        xs, ys = [], []
        for g, _, _ in gio.iter_graphics(graphics):
            if "Bounds" in g:
                x, y, w, h = gio.parse_rect(g["Bounds"])
                xs += [x, x + w]
                ys += [y, y + h]
            for p in g.get("Points", []):
                px, py = gio.parse_point(p)
                xs.append(px)
                ys.append(py)
        return min(xs), min(ys), max(xs), max(ys)

    # -------------------------------------------------------------- output
    def to_graffle(self) -> gio.GraffleFile:
        graphics = self._finalize()
        x0, y0, x1, y1 = self.bbox(graphics)
        m = float(self.theme.data.get("canvas", {}).get("margin", 12))
        if self.base_doc is None:
            doc = plistlib.load(open(os.path.join(_TEMPLATES, "document.plist"), "rb"))
            sheet = plistlib.load(open(os.path.join(_TEMPLATES, "sheet.plist"), "rb"))
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)
            doc["CreationDate"] = now
            doc["ModificationDate"] = now
            doc["Creator"] = doc["Modifier"] = self.theme.author
            sheet["SheetTitle"] = self.title
            sheet["GraphicsList"] = graphics
            # canvas sized to the content (OmniGraffle "fit to content" mode)
            cx0, cy0 = math.floor(x0 - m), math.floor(y0 - m)
            sheet["CanvasDimensionsOrigin"] = gio.fmt_point(cx0, cy0)
            sheet["CanvasSize"] = gio.fmt_point(math.ceil(x1 + m) - cx0, math.ceil(y1 + m) - cy0)
            sheet["BackgroundGraphic"]["Bounds"] = gio.fmt_rect(cx0 - 500, cy0 - 500, (x1 - x0) + 1000, (y1 - y0) + 1000)
            if self.export_shapes:
                sheet["ExportShapes"] = list(self.export_shapes.values())
            doc["Sheets"] = [sheet]
            doc["WindowInfo"]["VisibleRegion"] = gio.fmt_rect(x0 - 40, y0 - 40, (x1 - x0) + 80, (y1 - y0) + 80)
            doc["WindowInfo"]["ZoomValues"] = [[self.title, 1.0, 1.0]]
        else:
            doc = copy.deepcopy(self.base_doc)
            sheet = doc["Sheets"][self.sheet_index]
            back_ids = {g["ID"] for (rank, _, _), g, _ in self.items if rank <= 0}
            front = [g for g in graphics if g.get("ID") not in back_ids]
            back = [g for g in graphics if g.get("ID") in back_ids]
            # live edits made through find() nodes are already in self.base_doc; re-sync them
            sheet["GraphicsList"] = front + copy.deepcopy(self.base_doc["Sheets"][self.sheet_index]["GraphicsList"]) + back
            ax0, ay0, ax1, ay1 = self.bbox(sheet["GraphicsList"])
            ox, oy = gio.parse_point(sheet.get("CanvasDimensionsOrigin", "{0, 0}"))
            cw, ch = gio.parse_point(sheet.get("CanvasSize", "{0, 0}"))
            nx0, ny0 = min(ox, math.floor(ax0 - m)), min(oy, math.floor(ay0 - m))
            nx1, ny1 = max(ox + cw, math.ceil(ax1 + m)), max(oy + ch, math.ceil(ay1 + m))
            sheet["CanvasDimensionsOrigin"] = gio.fmt_point(nx0, ny0)
            sheet["CanvasSize"] = gio.fmt_point(nx1 - nx0, ny1 - ny0)
            if self.export_shapes:
                have = {e.get("ShapeName") for e in sheet.get("ExportShapes", [])}
                sheet.setdefault("ExportShapes", []).extend(
                    v for k, v in self.export_shapes.items() if k not in have)
            doc["ModificationDate"] = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)
        doc["ImageList"] = self.image_list + [n for n in doc.get("ImageList", []) if n not in self.image_list]
        doc["ImageCounter"] = max(int(doc.get("ImageCounter", 1)), self._image_counter)
        doc["ImageLinkBack"] = [{} for _ in doc["ImageList"]]
        assets = dict(getattr(self, "_base_assets", {}))
        assets.update(self.assets)
        return gio.GraffleFile(doc, assets, None, "zip")

    def save(self, path: str, png: bool | str = True, preview: bool = True, scale: float = 3.0) -> str:
        """Write ``path`` (.graffle).  Also embeds a QuickLook preview and, if ``png``,
        writes a PNG next to it (or to the given path) for quick viewing."""
        from . import render
        gf = self.to_graffle()
        if preview:
            try:
                gf.preview = render.preview_jpeg(gf)
            except Exception:  # preview is cosmetic
                gf.preview = None
        gio.save(gf, path)
        if png:
            out = png if isinstance(png, str) else os.path.splitext(path)[0] + ".png"
            render.to_png(gf, out, 0, scale=scale)
        # keep diagram reusable after save: undo group wrapping side effects
        return path

    def render(self, out: str, scale: float = 3.0) -> str:
        from . import render
        render.to_png(self.to_graffle(), out, 0, scale=scale)
        return out

    # ---------------------------------------------------------- editing mode
    @classmethod
    def open(cls, path: str, theme="auto", sheet: int = 0, theme_overrides: dict | None = None,
             base_theme: str = "crayon") -> "Diagram":
        """Append to / modify an existing document.

        ``theme="auto"`` (default) derives fonts, connector style and per-hue colours from the file
        itself so additions match it; or pass a theme name.  New graphics go on top of sheet
        ``sheet`` (``z="back"``/``"container"`` ones go behind the existing content).  Nodes
        returned by :meth:`find` wrap the live graphics: moving/resizing them edits the file."""
        gf = gio.load(path)
        if theme == "auto":
            from .theme import theme_from_file
            theme = theme_from_file(gf, base_theme, sheet)
        d = cls(theme, theme_overrides=theme_overrides)
        d.base_doc = gf.doc
        d._base_assets = gf.assets
        d.sheet_index = sheet
        d._next_id = max(gio.max_id(s.get("GraphicsList", [])) for s in gf.sheets) + 1
        d._image_counter = int(gf.doc.get("ImageCounter", 1))
        d.image_list = []
        return d

    def _pool(self):
        pool = []
        if self.base_doc is not None:
            pool += [g for g, _, _ in gio.iter_graphics(self.base_doc["Sheets"][self.sheet_index]["GraphicsList"])]
        pool += [g for _, g, _ in self.items]
        return [g for g in pool if g.get("Class") == "ShapedGraphic" and "Bounds" in g]

    def find(self, text: str | None = None, *, id: int | None = None, regex: bool = False,
             contains: bool = False, near: tuple | None = None, radius: float = 30) -> list[Node]:
        """Look up shapes in the opened document (or created ones).

        text: exact label (whitespace/newlines normalised); ``contains=True`` substring; ``regex=True``.
        id: OmniGraffle graphic ID (see ``ogkit inspect``).
        near=(x, y): shapes whose centre is within ``radius`` pt, nearest first.
        A label split over several shapes ("All Nodes" + "Embed.") matches neither — search one part."""
        out = []
        norm = lambda t: " ".join(t.split())
        for g in self._pool():
            if id is not None:
                if g.get("ID") == id:
                    out.append(Node(self, g, "existing"))
                continue
            if text is not None:
                if not g.get("Text", {}).get("Text"):
                    continue
                plain = norm(rtf.parse(g["Text"]["Text"]).plain)
                ok = (re.search(text, plain) if regex else (norm(text) in plain if contains else plain == norm(text)))
                if not ok:
                    continue
            out.append(Node(self, g, "existing"))
        if near is not None:
            nx, ny = near
            out = [n for n in out if math.hypot(n.cx - nx, n.cy - ny) <= radius]
            out.sort(key=lambda n: math.hypot(n.cx - nx, n.cy - ny))
        return out

    def find_frame(self, title: str, **kw) -> Node | None:
        """The container frame belonging to a title label (a text-less shape whose top edge is
        just below/at the title and which horizontally contains it), e.g. find_frame("Decoder")."""
        ts = self.find(title, **kw)
        best = None
        for t in ts:
            for g in self._pool():
                if g is t.g or g.get("Text", {}).get("Text") and rtf.parse(g["Text"]["Text"]).plain.strip():
                    continue
                x, y, w, h = gio.parse_rect(g["Bounds"])
                if x - 2 <= t.cx <= x + w + 2 and -6 <= y - t.bottom <= 25 or (x <= t.cx <= x + w and y <= t.top <= y + 30):
                    score = abs(y - t.bottom) - 0.001 * w * h
                    if best is None or score < best[0]:
                        best = (score, g)
        return Node(self, best[1], "existing") if best else None


def _anchor_offset(anchor, w, h):
    table = {"topleft": (0, 0), "center": (w / 2, h / 2), "top": (w / 2, 0), "bottom": (w / 2, h),
             "left": (0, h / 2), "right": (w, h / 2), "topright": (w, 0), "bottomleft": (0, h),
             "bottomright": (w, h)}
    if anchor not in table:
        raise ValueError(f"anchor must be one of {list(table)}")
    return table[anchor]


def _flatten_members(n: Node):
    for m in n.members + n.attached:
        yield m
        yield from _flatten_members(m)


# ---------------------------------------------------------------------------
# routing helpers
# ---------------------------------------------------------------------------

def _pt(obj):
    if isinstance(obj, Node):
        return obj.center
    return (float(obj[0]), float(obj[1]))


def _auto_sides(a, b):
    ax, ay, aw, ah = a.bounds if isinstance(a, Node) else (*_pt(a), 0, 0)
    bx, by, bw, bh = b.bounds if isinstance(b, Node) else (*_pt(b), 0, 0)
    acx, acy = ax + aw / 2, ay + ah / 2
    bcx, bcy = bx + bw / 2, by + bh / 2
    # horizontal gap vs vertical gap between boxes
    hgap = max(bx - (ax + aw), ax - (bx + bw))
    vgap = max(by - (ay + ah), ay - (by + bh))
    if hgap >= vgap:
        return ("right", "left") if bcx >= acx else ("left", "right")
    return ("bottom", "top") if bcy >= acy else ("top", "bottom")


def _side_point(obj, side, t=0.5):
    if isinstance(obj, Node):
        if side == "center":
            return obj.center
        if obj.kind == "circle" and t == 0.5:
            cx, cy = obj.center
            return {"left": (obj.left, cy), "right": (obj.right, cy), "top": (cx, obj.top), "bottom": (cx, obj.bottom)}[side]
        return obj.anchor(side, t)
    return _pt(obj)


_DIRS = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}


def _rect(obj):
    if isinstance(obj, Node):
        return obj.bounds
    x, y = _pt(obj)
    return (x, y, 0.0, 0.0)


def _align_ports(src, dst, ss, ds, spec):
    """If facing sides overlap, slide the attachment points so the connector is straight."""
    if spec["src_t"] != 0.5 or spec["dst_t"] != 0.5 or not (isinstance(src, Node) and isinstance(dst, Node)):
        return None
    ax, ay, aw, ah = src.bounds
    bx, by, bw, bh = dst.bounds
    if {ss, ds} == {"left", "right"}:
        lo, hi = max(ay, by) + 2, min(ay + ah, by + bh) - 2
        if hi - lo < 2:
            return None
        for y in (by + bh / 2, ay + ah / 2, (lo + hi) / 2):
            if lo <= y <= hi:
                return (_side_point(src, ss)[0], y), (_side_point(dst, ds)[0], y)
    if {ss, ds} == {"top", "bottom"}:
        lo, hi = max(ax, bx) + 2, min(ax + aw, bx + bw) - 2
        if hi - lo < 2:
            return None
        for x in (bx + bw / 2, ax + aw / 2, (lo + hi) / 2):
            if lo <= x <= hi:
                return (x, _side_point(src, ss)[1]), (x, _side_point(dst, ds)[1])
    return None


def route_line(src, dst, spec) -> tuple[list[tuple[float, float]], str]:
    src = src.geom if isinstance(src, Node) else src
    dst = dst.geom if isinstance(dst, Node) else dst
    ss, ds = spec["src_side"], spec["dst_side"]
    if ss == "auto" or ds == "auto":
        a_s, a_d = _auto_sides(src, dst)
        ss = a_s if ss == "auto" else ss
        ds = a_d if ds == "auto" else ds
    route = spec["route"]
    via = [tuple(v) for v in spec["via"]]
    spec = dict(spec)
    for end, obj, side in (("src", src, ss), ("dst", dst, ds)):
        at = spec.get(f"{end}_at")
        if at is not None and isinstance(obj, Node) and side in _DIRS:
            x, y, w, h = obj.bounds
            spec[f"{end}_t"] = ((at - y) / h if h else 0.5) if side in ("left", "right") else ((at - x) / w if w else 0.5)
        spec[f"{end}_t"] = min(1.0, max(0.0, float(spec[f"{end}_t"])))
    aligned = None if via or route == "curved" else _align_ports(src, dst, ss, ds, spec)
    if aligned:
        return list(aligned), "straight"
    p0 = _side_point(src, ss, spec["src_t"]) if ss in _DIRS else _pt(src)
    p1 = _side_point(dst, ds, spec["dst_t"]) if ds in _DIRS else _pt(dst)
    if route == "curved":
        return [p0] + via + [p1], "curved"
    if route == "straight":
        return [p0] + via + [p1], "straight"
    if via:
        return _simplify(_orthogonalize([p0] + via + [p1], ss)), "ortho"
    if abs(p0[0] - p1[0]) < 0.5 or abs(p0[1] - p1[1]) < 0.5:
        if (ss in ("left", "right")) == (abs(p0[1] - p1[1]) < 0.5) and _faces(p0, ss, p1):
            return [p0, p1], "straight"
    pts = _ortho_route(p0, ss, p1, ds, _rect(src), _rect(dst))
    return pts, ("straight" if len(pts) == 2 else "ortho")


def _faces(p0, s0, p1):
    d = _DIRS.get(s0, (0, 0))
    return (p1[0] - p0[0]) * d[0] + (p1[1] - p0[1]) * d[1] > 0


def _seg_hits_rect(a, b, r, shrink=1.0):
    x, y, w, h = r
    if w <= 0 or h <= 0:
        return False
    x0, y0, x1, y1 = x + shrink, y + shrink, x + w - shrink, y + h - shrink
    if abs(a[1] - b[1]) < 1e-6:  # horizontal
        yy = a[1]
        return y0 < yy < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0
    if abs(a[0] - b[0]) < 1e-6:
        xx = a[0]
        return x0 < xx < x1 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0
    return False


def _simplify(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) < 1e-6 and abs(p[1] - out[-1][1]) < 1e-6:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if (abs(a[0] - b[0]) < 1e-6 and abs(b[0] - p[0]) < 1e-6) or (abs(a[1] - b[1]) < 1e-6 and abs(b[1] - p[1]) < 1e-6):
                out[-1] = p
                continue
        out.append(p)
    return out


def _ortho_route(p0, s0, p1, s1, r0, r1, out=12.0):
    """Pick the cheapest axis-aligned path that leaves/enters along the side normals
    and does not cut through either end box."""
    d0, d1 = _DIRS[s0], _DIRS[s1]
    a = (p0[0] + d0[0] * out, p0[1] + d0[1] * out)
    b = (p1[0] + d1[0] * out, p1[1] + d1[1] * out)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    # direct L/Z forms using the real ports (no stubs) — preferred when valid
    cands = [
        [p0, (p1[0], p0[1]), p1], [p0, (p0[0], p1[1]), p1],
        [p0, ((p0[0] + p1[0]) / 2, p0[1]), ((p0[0] + p1[0]) / 2, p1[1]), p1],
        [p0, (p0[0], (p0[1] + p1[1]) / 2), (p1[0], (p0[1] + p1[1]) / 2), p1],
        # stub-based detours
        [p0, a, (b[0], a[1]), b, p1], [p0, a, (a[0], b[1]), b, p1],
        [p0, a, (mx, a[1]), (mx, b[1]), b, p1], [p0, a, (a[0], my), (b[0], my), b, p1],
    ]
    # detours around both boxes
    top = min(r0[1], r1[1]) - out
    bot = max(r0[1] + r0[3], r1[1] + r1[3]) + out
    lef = min(r0[0], r1[0]) - out
    rig = max(r0[0] + r0[2], r1[0] + r1[2]) + out
    for yy in (top, bot):
        cands.append([p0, a, (a[0], yy), (b[0], yy), b, p1])
    for xx in (lef, rig):
        cands.append([p0, a, (xx, a[1]), (xx, b[1]), b, p1])
    best, best_cost = None, None
    for c in cands:
        c = _simplify(c)
        if not _valid_ortho(c):
            continue
        # first segment must leave along d0, last must arrive against d1
        if not _dir_ok(c[0], c[1], d0) or not _dir_ok(c[-1], c[-2], d1):
            continue
        hits = sum(_seg_hits_rect(u, v, r) for u, v in zip(c, c[1:]) for r in (r0, r1))
        length = sum(abs(u[0] - v[0]) + abs(u[1] - v[1]) for u, v in zip(c, c[1:]))
        cost = hits * 1e6 + length + 18 * (len(c) - 2)
        if best_cost is None or cost < best_cost:
            best, best_cost = c, cost
    return best or [p0, p1]


def _valid_ortho(c):
    return all(abs(u[0] - v[0]) < 1e-6 or abs(u[1] - v[1]) < 1e-6 for u, v in zip(c, c[1:]))


def _dir_ok(p, q, d):
    """Segment p->q heads in direction d (for the last segment we pass end, prev)."""
    vx, vy = q[0] - p[0], q[1] - p[1]
    n = math.hypot(vx, vy)
    if n < 1e-6:
        return False
    return (vx * d[0] + vy * d[1]) / n > 0.99


def _orthogonalize(pts, first_side):
    """Insert corners so consecutive waypoints are joined by axis-aligned segments."""
    out = [pts[0]]
    horizontal = first_side in ("left", "right")
    for p in pts[1:]:
        q = out[-1]
        if abs(q[0] - p[0]) > 0.5 and abs(q[1] - p[1]) > 0.5:
            out.append((p[0], q[1]) if horizontal else (q[0], p[1]))
            horizontal = not horizontal
        else:
            horizontal = abs(q[1] - p[1]) <= 0.5
        out.append(p)
    return out


def rounded_path(pts, r):
    els = [{"element": "MOVETO", "point": gio.fmt_point(*pts[0])}]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        la = math.hypot(b[0] - a[0], b[1] - a[1])
        lc = math.hypot(c[0] - b[0], c[1] - b[1])
        rr = min(r, la / 2, lc / 2)
        if rr < 0.5:
            els.append({"element": "LINETO", "point": gio.fmt_point(*b)})
            continue
        s = (b[0] + (a[0] - b[0]) * rr / la, b[1] + (a[1] - b[1]) * rr / la)
        e = (b[0] + (c[0] - b[0]) * rr / lc, b[1] + (c[1] - b[1]) * rr / lc)
        c1 = (s[0] + (b[0] - s[0]) * _KAPPA, s[1] + (b[1] - s[1]) * _KAPPA)
        c2 = (e[0] + (b[0] - e[0]) * _KAPPA, e[1] + (b[1] - e[1]) * _KAPPA)
        els.append({"element": "LINETO", "point": gio.fmt_point(*s)})
        els.append({"element": "CURVETO", "control1": gio.fmt_point(*c1), "control2": gio.fmt_point(*c2),
                    "point": gio.fmt_point(*e)})
    els.append({"element": "LINETO", "point": gio.fmt_point(*pts[-1])})
    return els


def curve_controls(p0, p1, spec, src, dst):
    k = float(spec.get("curve", 0.35))
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy) or 1
    ss, ds = spec["src_side"], spec["dst_side"]
    if ss in _DIRS and ds in _DIRS:
        d0, d1 = _DIRS[ss], _DIRS[ds]
        return ((p0[0] + d0[0] * dist * k * 1.4, p0[1] + d0[1] * dist * k * 1.4),
                (p1[0] + d1[0] * dist * k * 1.4, p1[1] + d1[1] * dist * k * 1.4))
    # bow sideways (perpendicular offset) — positive k bends to the left of travel
    nx, ny = -dy / dist, dx / dist
    off = dist * k
    return ((p0[0] + dx / 3 + nx * off, p0[1] + dy / 3 + ny * off),
            (p0[0] + 2 * dx / 3 + nx * off, p0[1] + 2 * dy / 3 + ny * off))


def point_along(elements, t, with_tangent=False):
    from .render import flatten
    poly = flatten(elements)
    segs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly, poly[1:])]
    total = sum(segs) or 1
    target = total * t
    acc = 0.0
    for (a, b), s in zip(zip(poly, poly[1:]), segs):
        if acc + s >= target and s > 0:
            u = (target - acc) / s
            p = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
            return (p, (b[0] - a[0], b[1] - a[1])) if with_tangent else p
        acc += s
    if with_tangent:
        a, b = poly[-2], poly[-1]
        return poly[-1], (b[0] - a[0], b[1] - a[1])
    return poly[-1]


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

def natural_size(data: bytes, ext: str) -> tuple[float, float]:
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        w, h = pdf[0].get_size()
        return float(w), float(h)
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    w, h = im.size
    dpi = im.info.get("dpi", (72, 72))[0] or 72
    w, h = w * 72 / dpi, h * 72 / dpi
    s = 100.0 / max(w, h) if max(w, h) > 100 else 1.0
    return w * s, h * s


_LATEX_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "ogkit", "latex")


def latex_pdf(expr: str, color: str = "#000000", display: bool = False) -> bytes:
    """Compile a math expression to a tight vector PDF (cached)."""
    key = hashlib.sha1(f"{expr}|{color}|{display}".encode()).hexdigest()[:20]
    os.makedirs(_LATEX_CACHE, exist_ok=True)
    out = os.path.join(_LATEX_CACHE, key + ".pdf")
    if os.path.exists(out):
        return open(out, "rb").read()
    if not shutil.which("pdflatex"):
        raise RuntimeError("pdflatex not found: install TeX Live to use Diagram.math()")
    hexc = color.lstrip("#")
    body = (r"\displaystyle " if display else "") + expr
    src = (r"\documentclass[10pt,border=0.5pt]{standalone}" "\n"
           r"\usepackage{amsmath,amssymb,bm,xcolor}" "\n"
           r"\definecolor{ogc}{HTML}{" + hexc.upper() + "}\n"
           r"\begin{document}\color{ogc}$" + body + r"$\end{document}" "\n")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "m.tex"), "w").write(src)
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "m.tex"], cwd=td,
                           capture_output=True, text=True, timeout=60)
        pdf = os.path.join(td, "m.pdf")
        if r.returncode != 0 or not os.path.exists(pdf):
            tail = "\n".join(l for l in r.stdout.splitlines() if l.startswith("!") or "error" in l.lower())[:800]
            raise RuntimeError(f"LaTeX failed for {expr!r}:\n{tail}")
        shutil.copy(pdf, out)
    return open(out, "rb").read()


from .components import install as _install_components  # noqa: E402

_install_components(Diagram)
