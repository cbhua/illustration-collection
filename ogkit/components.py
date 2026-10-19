"""Parametric components = the recurring motifs of the corpus, rebuilt as code.

Each returns a compound :class:`~ogkit.diagram.Node` (moves as a unit, can be
connected to via ``node.members[i]``).  All take theme colours (palette hue names).

Motif                          where it appears in the corpus
-----------------------------  --------------------------------------------------------
badge(icon)                    EvoNav / PILLM / VRPAgent — Material icon in rounded square
code_chip("</>")               ReEvo, BuildEvo, VRPAgent, Water Research LLM
population([...])              ReEvo / BuildEvo — column of </> chips with "......"
matrix(rows, cols)             CAMP, RouteFinder, PARCO, USPR — 9x9 pt feature cells
vector(n) / bar()              embeddings ("Node Embed.", "Hidden States")
trapezoid()                    encoder / decoder layer funnels
stack(node, n)                 "Partitions", "Solutions" — offset card stacks
op("+")                        residual adds in Transformer blocks (circle + cross)
vrp_instance()                 depot square + customer circles in a frame (≥10 figures)
legend([...])                  legends under illustrations
section_bar("Summary")         poster section headers (KAIST blue / RL4CO red)
caption(node, "text")          label above/below a box that moves with it
"""
from __future__ import annotations

import math
import random

from . import gio
from .colors import og_color


def install(cls):
    cls.free_line = free_line
    for name in ("caption", "badge", "code_chip", "population", "matrix", "vector", "bar", "trapezoid",
                 "stack", "op", "vrp_instance", "legend", "section_bar", "ellipsis", "gauge", "compound"):
        setattr(cls, name, globals()["_" + name])


def free_line(self, p, q, *, color="#A9A9A9", width=1.0, head=None, tail=None, head_scale=0.5, dash=None, z="front",
              via=None):
    """A static (unconnected) line that moves with compound nodes."""
    from .diagram import Node
    st = {"Color": og_color(self._line_color(color)), "Legacy": False}
    if width != 1:
        st["Width"] = float(width)
    if head:
        st["HeadArrow"] = head
        st["HeadScale"] = float(head_scale)
    if tail:
        st["TailArrow"] = tail
        st["TailScale"] = float(head_scale)
    if dash:
        st["Pattern"] = int(self.theme.line.get("dash_pattern", 24) if dash is True else dash)
    pts = [tuple(p)] + [tuple(v) for v in (via or [])] + [tuple(q)]
    g = {"Class": "LineGraphic", "ID": self._id(), "Points": [gio.fmt_point(*v) for v in pts],
         "Style": {"fill": {"Draws": "NO"}, "shadow": {"Draws": "NO"}, "stroke": st},
         "LogicalPath": {"elements": [{"element": "MOVETO" if i == 0 else "LINETO", "point": gio.fmt_point(*v)}
                                      for i, v in enumerate(pts)]}}
    self._add(g, z)
    return FreeLine(self, g)


class _FreeLineBase:
    pass


def _compound(self, nodes, kind="compound"):
    """Bundle nodes so they move together (not an OmniGraffle group)."""
    from .diagram import Node
    n = Node(self, None, kind, members=list(nodes))
    return n


def _caption(self, node, text, side="top", gap=2, size="label", color="secondary", **kw):
    """Text label outside ``node`` that follows it (user's habit: titles above boxes,
    'Node Features' above tables, captions below panels)."""
    t = self.text(text, size=size, color=color, **kw)
    if side == "top":
        t.place(cx=node.cx, bottom=node.top - gap)
    elif side == "bottom":
        t.place(cx=node.cx, top=node.bottom + gap)
    elif side == "left":
        t.place(right=node.left - gap, cy=node.cy)
    elif side == "right":
        t.place(left=node.right + gap, cy=node.cy)
    elif side == "top-left":
        t.place(left=node.left, bottom=node.top - gap)
    node.attached.append(t)
    return t


def _badge(self, icon, x=0, y=0, size=16, color="blue", tone="light", frame=True, label=None,
           label_size="small"):
    """Material icon inside a rounded square (stroke = dark crayon, fill = light)."""
    sw = self.theme.swatch(color, tone)
    parts = []
    if frame:
        f = self.shape(x, y, size, size, fill=sw["fill"], alpha=sw["alpha"], stroke=sw["stroke"],
                       stroke_width=1, radius=size * 0.18)
        parts.append(f)
        s = size * 0.64
        ic = self.icon(icon, x + (size - s) / 2, y + (size - s) / 2, s, color=color)
    else:  # same glyph size as the framed variant, centred in the same footprint
        s = size * 0.64
        ic = self.icon(icon, x + (size - s) / 2, y + (size - s) / 2, s, color=color)
    parts.append(ic)
    node = _compound(self, parts, "badge")
    if frame:
        node.meta["layout"] = parts[0]
    if label:
        _caption(self, node, label, side="bottom", size=label_size, color=color)
    return node


def _code_chip(self, text="</>", x=0, y=0, color="blue", w=None, h=None, size="small"):
    """The `</>` code chip (white or light fill, dark stroke, mono text)."""
    sw = self.theme.swatch(color)
    n = self.box(text, x, y, w=w or 20, h=h or 12, style="tag", color=color, font="mono", size=size,
                 text_color=sw["text"])
    return n


def _ellipsis(self, x=0, y=0, vertical=False, color="secondary", size="small", cx=None, cy=None):
    """'......' (horizontal text) or a vertical ⋮ drawn as three dots (fonts lack the glyph)."""
    if cx is not None:
        x, y = cx, cy
    if not vertical:
        return self.text("......", x, y, size=size, color=color, anchor="center")
    col = self.theme.text_color(color)
    r = max(1.0, self.theme.size(size) * 0.13)
    dots = [self.shape(x - r, y + k * r * 3.2 - r, 2 * r, 2 * r, shape="Circle", fill=col, stroke=None)
            for k in (-1, 0, 1)]
    return _compound(self, dots, "ellipsis")


def _population(self, items=3, x=0, y=0, *, color="blue", chip="</>", gap=5, ellipsis=True,
                title=None, frame=True, chip_w=20, chip_h=12, title_size="label"):
    """Column of code chips (a population of programs/heuristics), ReEvo style."""
    labels = [chip] * items if isinstance(items, int) else list(items)
    chips = []
    cy = y
    for i, lab in enumerate(labels):
        if ellipsis and i == len(labels) - 1 and len(labels) > 1:
            e = self.text("......", size="small", color="secondary", anchor="top")
            e.place(cx=x + chip_w / 2, top=cy - 2)
            chips.append(e)
            cy += e.h - 2
        c = _code_chip(self, lab, x, cy, color=color, w=chip_w, h=chip_h)
        chips.append(c)
        cy += chip_h + gap
    if frame:
        cont = self.container(chips, title, color=color, style="panel", pad=4, title_size=title_size,
                              title_color=color)
        return cont
    return _compound(self, chips, "population")


def _matrix(self, rows=3, cols=4, x=0, y=0, *, cell=9, color="blue", tone="light", gap=0,
            row_labels=None, col_labels=None, highlight=None, highlight_color=None, highlight_tone="strong",
            label_size="small", label_font="mono"):
    """Grid of feature cells (the 9x9 pt cells used for features / preference matrices).
    ``highlight`` = list of (r, c) cells drawn with ``highlight_color``."""
    sw = self.theme.swatch(color, tone)
    hs = self.theme.swatch(highlight_color or color, highlight_tone)
    hl = set(map(tuple, highlight or []))
    cells = []
    for r in range(rows):
        for c in range(cols):
            s = hs if (r, c) in hl else sw
            cells.append(self.shape(x + c * (cell + gap), y + r * (cell + gap), cell, cell, fill=s["fill"],
                                    alpha=s["alpha"], stroke=s["stroke"], stroke_width=0.8))
    parts = list(cells)
    if row_labels:
        for r, lab in enumerate(row_labels):
            if lab is None:
                continue
            t = self.text(lab, size=label_size, color="secondary", font=label_font, anchor="right")
            t.place(right=x - 3, cy=y + r * (cell + gap) + cell / 2)
            parts.append(t)
    if col_labels:
        for c, lab in enumerate(col_labels):
            if lab is None:
                continue
            t = self.text(lab, size=label_size, color="secondary", font=label_font, rotation=-90)
            t.place(cx=x + c * (cell + gap) + cell / 2, top=y + rows * (cell + gap) + 2)
            parts.append(t)
    node = _compound(self, parts, "matrix")
    node.meta["cells"] = cells
    return node


def _vector(self, n=4, x=0, y=0, *, cell=9, color="blue", tone="light", vertical=False, highlight=None,
            highlight_color=None, highlight_tone="strong"):
    """1×n cells; ``highlight`` = list of indices."""
    hl = [(i, 0) if vertical else (0, i) for i in (highlight or [])]
    return _matrix(self, n if vertical else 1, 1 if vertical else n, x, y, cell=cell, color=color, tone=tone,
                   highlight=hl, highlight_color=highlight_color, highlight_tone=highlight_tone)


def _bar(self, x=0, y=0, w=38, h=9, *, color="blue", tone="light", text=None, size="small"):
    """Thin embedding bar (e.g. 'Node Embed.')."""
    sw = self.theme.swatch(color, tone)
    return self.shape(x, y, w, h, fill=sw["fill"], alpha=sw["alpha"], stroke=sw["stroke"], stroke_width=0.8,
                      text=text, size=size, text_color=sw["text"], pad_x=1, pad_y=0)


def _trapezoid(self, x=0, y=0, w=20, h=56, *, narrow="right", ratio=0.6, color="gray", tone="light"):
    """Encoder/decoder funnel: a Bezier trapezoid whose ``narrow`` side is shorter."""
    sw = self.theme.swatch(color, tone)
    a = ratio / 2
    pts = {"right": [(-.5, -.5), (.5, -a), (.5, a), (-.5, .5)],
           "left": [(-.5, -a), (.5, -.5), (.5, .5), (-.5, a)],
           "top": [(-a, -.5), (a, -.5), (.5, .5), (-.5, .5)],
           "bottom": [(-.5, -.5), (.5, -.5), (a, .5), (-a, .5)]}[narrow]
    # UnitPoints: p0, c0out, c1in, p1, ... (straight edges -> controls on the points)
    unit = []
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        unit += [p, p, q]
    n = self.shape(x, y, w, h, shape="Bezier", fill=sw["fill"], alpha=sw["alpha"], stroke=sw["stroke"])
    n.g["ShapeData"] = {"UnitPoints": [gio.fmt_point(*p) for p in unit]}
    return n


def _stack(self, node, n=2, dx=4, dy=-4):
    """Draw ``n`` offset copies *behind* a box to suggest a stack (Partitions / Solutions)."""
    import copy
    copies = []
    for i in range(n, 0, -1):
        g = copy.deepcopy(node.g)
        g["ID"] = self._id()
        g["Text"] = {"TextAlongPathGlyphAnchor": "center"}
        g.pop("FontInfo", None)
        x, y, w, h = node.bounds
        g["Bounds"] = gio.fmt_rect(x + dx * i, y + dy * i, w, h)
        g["Style"]["fill"] = {"Color": og_color("#FFFFFF")}
        self._add(g, "under")
        from .diagram import Node
        copies.append(Node(self, g, "stack-copy"))
    node.attached.extend(copies)
    return node


def _op(self, symbol="+", x=0, y=0, d=10, *, color="gray", cx=None, cy=None):
    """Circle operator (⊕ / ⊗) drawn like the corpus: circle + two strokes."""
    sw = self.theme.swatch(color)
    if cx is not None:
        x, y = cx - d / 2, cy - d / 2
    c = self.shape(x, y, d, d, shape="Circle", fill="#FFFFFF", stroke=sw["stroke"])
    c.kind = "circle"
    mx, my = x + d / 2, y + d / 2
    if symbol in ("+", "plus"):
        segs = [((mx - d / 2, my), (mx + d / 2, my)), ((mx, my - d / 2), (mx, my + d / 2))]
    else:
        k = d * 0.3535
        segs = [((mx - k, my - k), (mx + k, my + k)), ((mx - k, my + k), (mx + k, my - k))]
    for p, q in segs:
        c.attached.append(free_line(self, p, q, color=sw["stroke"]))
    return c


def _vrp_instance(self, x=0, y=0, w=60, h=60, *, n=8, seed=0, depot=True, routes=None, node_d=None,
                  customer_color="blue", depot_color="red", route_colors=("green", "red", "purple", "blue"),
                  labels=False, frame=True, points=None, depot_at=(0.5, 0.5), open_routes=False):
    """Routing instance: frame + depot (square) + customers (circles) [+ routes].
    ``routes`` = list of lists of customer indices (depot implied at both ends unless
    ``open_routes``).  ``depot_at`` = relative (u, v) position; ``points`` = relative customer
    positions.  ``route_colors=("gray",)`` gives the neutral grey arrows of problem figures."""
    rnd = random.Random(seed)
    nd = node_d or max(5.0, min(w, h) / 9)
    parts = []
    if frame:
        parts.append(self.box("", x, y, w, h, style="frame", color="white", z="container"))
    pts = points or _spread_points(rnd, n, nd * 1.8 / min(w, h))
    dep = None
    if depot:
        dw = nd * 1.1
        dep = self.shape(x + depot_at[0] * w - dw / 2, y + depot_at[1] * h - dw / 2, dw, dw, fill=self.theme.swatch(depot_color)["fill"],
                         alpha=max(0.2, self.theme.swatch(depot_color)["alpha"]),
                         stroke=self.theme.swatch(depot_color)["stroke"], stroke_width=0.9)
        parts.append(dep)
    custs = []
    for i, (u, v) in enumerate(pts):
        c = self.circle(cx=x + u * w, cy=y + v * h, d=nd, color=customer_color, stroke_width=0.9,
                        tone="medium" if self.theme.swatch(customer_color)["alpha"] < 1 else "light")
        custs.append(c)
        parts.append(c)
        if labels:
            t = self.text(str(i + 1), size="tiny", color="secondary")
            t.place(cx=c.cx - nd * 0.9, cy=c.cy - nd * 0.9)
            parts.append(t)
    for ri, route in enumerate(routes or []):
        col = route_colors[ri % len(route_colors)]
        seq = ([dep] if dep else []) + [custs[i] for i in route] + ([dep] if dep and not open_routes else [])
        for a, b in zip(seq, seq[1:]):
            self.line(a, b, route="straight", src_side="center", dst_side="center", color=col, width=0.75,
                      head="FilledArrow", head_scale=0.32)
    node = _compound(self, parts, "instance")
    node.meta.update(depot=dep, customers=custs)
    if frame:
        node.meta["layout"] = parts[0]
    return node


def _spread_points(rnd, n, min_d, lo=0.12, hi=0.88):
    """Rejection sampling with a minimum distance (unit square), avoiding the centre depot."""
    pts = []
    tries = 0
    while len(pts) < n and tries < 5000:
        tries += 1
        p = (rnd.uniform(lo, hi), rnd.uniform(lo, hi))
        if math.hypot(p[0] - 0.5, p[1] - 0.5) < min_d:
            continue
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= min_d for q in pts):
            pts.append(p)
    while len(pts) < n:
        pts.append((rnd.uniform(lo, hi), rnd.uniform(lo, hi)))
    return pts


def _legend(self, items, x=0, y=0, *, horizontal=True, gap=10, size="small", swatch=8, frame=False,
            tone="medium"):
    """items: list of (kind, color, label[, tone]); kind in box | square | circle | triangle-up |
    triangle-down | line | arrow | dashed.  Marker tone defaults to "medium" (matches vrp_instance).
    frame: False | True (grey panel) | "pill" (rounded light-grey bar, as under RouteFinder figures)."""
    parts = []
    cx, cy = x, y
    for item in items:
        kind, color, label = item[:3]
        sw = self.theme.swatch(color, item[3] if len(item) > 3 else tone)
        if kind in ("box", "square", "circle"):
            m = self.shape(cx, cy, swatch, swatch, shape="Circle" if kind == "circle" else "Rectangle",
                           fill=sw["fill"], alpha=sw["alpha"], stroke=sw["stroke"], stroke_width=0.9)
            mw = swatch
        elif kind.startswith("triangle"):
            direction = kind.split("-", 1)[1] if "-" in kind else "up"
            m = self.triangle(cx + swatch / 2, cy + swatch / 2, swatch, direction=direction, color=color,
                              tone=item[3] if len(item) > 3 else tone)
            mw = swatch
        else:
            mw = swatch * 2.4
            m = free_line(self, (cx, cy + swatch / 2), (cx + mw, cy + swatch / 2), color=color,
                          head=(self.theme.line.get("head", "FilledArrow") if kind == "arrow" else None),
                          head_scale=self.theme.line.get("head_scale", 0.75) * 0.7, dash=(kind == "dashed"))
        t = self.text(label, size=size, color="secondary")
        t.place(left=cx + mw + 4, cy=cy + swatch / 2)
        parts += [m, t]
        if horizontal:
            cx = t.right + gap
        else:
            cy = max(t.bottom, cy + swatch) + gap / 2
    node = _compound(self, parts, "legend")
    if frame == "pill":
        return self.container([node], None, color="silver", fill="#FAFAFA", radius=8, pad=8, stroke_width=1)
    if frame:
        return self.container([node], None, color="gray", style="panel", pad=5)
    return node


def _section_bar(self, text, x=0, y=0, w=300, h=None, *, color="blue", size="heading", radius=3):
    """Poster section header: solid dark-crayon bar with white text, left aligned."""
    sw = self.theme.swatch(color)
    runs = self._runs(text, size, "#FFFFFF")
    from .diagram import measure_runs
    _, th, _ = measure_runs(runs)
    h = h or math.ceil(th + 6)
    n = self.shape(x, y, w, h, fill=sw["text"], stroke=None, radius=radius, text=runs, align="left",
                   pad_x=8, pad_y=0)
    return n


def _gauge(self, x=0, y=0, w=15, *, level="high"):
    """Performance gauge pictogram (from the image library)."""
    import os
    from .library import LIB
    p = os.path.join(LIB, "images", "icon", f"gauge-{'high' if level == 'high' else 'low'}.png")
    if not os.path.exists(p):
        p = p[:-4] + ".pdf"
    return self.image(p, x, y, w=w)


from .diagram import Node as _Node  # noqa: E402


class FreeLine(_Node):
    """Node wrapper for an unconnected LineGraphic (bounds = points' bbox)."""

    def __init__(self, d, g):
        super().__init__(d, g, "line")

    @property
    def bounds(self):
        pts = [gio.parse_point(p) for p in self.g["Points"]]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def move(self, dx, dy):
        self.g["Points"] = [gio.fmt_point(*(lambda p: (p[0] + dx, p[1] + dy))(gio.parse_point(p)))
                            for p in self.g["Points"]]
        for e in self.g.get("LogicalPath", {}).get("elements", []):
            for k in ("point", "control1", "control2"):
                if k in e:
                    px, py = gio.parse_point(e[k])
                    e[k] = gio.fmt_point(px + dx, py + dy)
        for a in self.attached:
            a.move(dx, dy)
        return self
