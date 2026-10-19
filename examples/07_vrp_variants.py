"""VRP variants problem illustration (4 panels + legend), crayon (written by an agent from a one-paragraph request using the skill)."""
"""VRP variants problem illustration: O / L / TW / B, plus a legend bar (crayon, ~500pt)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram
from ogkit.colors import mix

d = Diagram(theme="crayon")
TH = d.theme
RED = TH.swatch("red")["stroke"]          # #941100 — numbers / constraints
BLUE = TH.swatch("blue")["stroke"]        # #005493
ROUTE = "#C0C0C0"
FRAME = "#808080"
TITLE_PT, LEG_PT = 9, 9

S, GAP = 114, 14                          # 4*114 + 3*14 = 498 pt
TOP = 20
NODE = 8                                  # customer diameter
DEP = 10                                  # depot side

# Shared customer layout (fractions of the panel), depot bottom-left like the reference.
DEPOT = (0.27, 0.80)
CUST = [(0.14, 0.50), (0.28, 0.20), (0.60, 0.14), (0.86, 0.36), (0.83, 0.68), (0.58, 0.84)]


def route(nodes, closed=True):
    seq = nodes + ([nodes[0]] if closed else [])
    out = []
    for a, b in zip(seq, seq[1:]):
        out.append(d.arrow(a, b, route="straight", src_side="center", dst_side="center",
                           color=ROUTE, head="StickArrow", head_scale=0.5))
    return out


def panel(i, title):
    x0 = i * (S + GAP)
    fr = d.shape(x0, TOP, S, S, fill="#FFFFFF", stroke=FRAME, stroke_width=1, z="container")
    d.text(title, size=TITLE_PT, color="secondary").place(cx=fr.cx, bottom=fr.top - 3)
    P = lambda u, v: (x0 + u * S, TOP + v * S)
    dep_c = P(*DEPOT)
    dep = d.box("", w=DEP, h=DEP, color="red").place(cx=dep_c[0], cy=dep_c[1])
    return fr, P, dep


def customers(P, kinds=None):
    out = []
    for k, (u, v) in enumerate(CUST):
        cx, cy = P(u, v)
        kind = kinds[k] if kinds else "c"
        if kind == "c":
            n = d.circle(cx=cx, cy=cy, d=NODE, color="blue")
        elif kind == "L":   # linehaul: downward triangle, blue
            n = d.polygon("HorizontalTriangle", cx - NODE / 2, cy - NODE / 2, NODE, NODE, color="blue", rotation=90)
        else:               # backhaul: upward triangle, olive
            n = d.polygon("HorizontalTriangle", cx - NODE / 2, cy - NODE / 2, NODE, NODE, color="yellow", rotation=270)
        out.append(n)
    return out


def mono(txt, x, y, size=8, anchor="center"):
    return d.text(f"`{txt}`", x, y, size=size, color=RED, anchor=anchor)


# ---------------- (O) open route: never returns to the depot
fr, P, dep = panel(0, "Open route (O)")
cs = customers(P)
route([dep] + cs, closed=False)

# ---------------- (L) duration limit: travel times on edges, "< L" at the depot
fr, P, dep = panel(1, "Duration limit (L)")
cs = customers(P)
seq = [dep] + cs
lines = route(seq)
times = ["0.2", "0.1", "0.3", "0.1", "0.2", "0.1", "0.1"]
pts = [P(*DEPOT)] + [P(*c) for c in CUST] + [P(*DEPOT)]
cxp, cyp = P(0.52, 0.50)                    # tour centre: push labels outwards
for k, t in enumerate(times):
    (ax, ay), (bx, by) = pts[k], pts[k + 1]
    t_ = 0.3 if k == len(times) - 1 else 0.5      # last edge: keep clear of "< L"
    mx, my = ax + (bx - ax) * t_, ay + (by - ay) * t_
    vx, vy = mx - cxp, my - cyp
    nrm = (vx * vx + vy * vy) ** 0.5 or 1
    mono(t, mx + vx / nrm * 8, my + vy / nrm * 8)
mono("< L", dep.cx, dep.bottom + 6)

# ---------------- (TW) time windows + service durations
fr, P, dep = panel(2, "Time windows (TW)")
cs = customers(P)
route([dep] + cs)
TW_BLUE = mix(BLUE, "#FFFFFF", 0.5)


def tw_bar(cx, cy, w=22, a=0.3, b=0.65):
    """|——| window (light blue) with the service interval (red) inside."""
    x0 = cx - w / 2
    d.line((x0, cy), (x0 + w, cy), route="straight", color=TW_BLUE, head="NegativeControls",
           tail="NegativeControls", head_scale=0.5)
    d.line((x0 + a * w, cy), (x0 + b * w, cy), route="straight", color=RED, head="NegativeControls",
           tail="NegativeControls", head_scale=0.5)


# (customer index, bar offset dx, dy, sd label, label offset dx, dy)
tw = [(0, 0, -9), (1, 0, -9), (2, 0, -9), (5, 4, 9)]   # (customer, bar dx, bar dy)
for k, bdx, bdy in tw:
    c = cs[k]
    tw_bar(c.cx + bdx, c.cy + bdy)
mono("sd:0", dep.left - 2, dep.cy, size=6, anchor="right")
for k, sd, side in [(0, "0.5", "right"), (1, "1.2", "left"), (2, "0.7", "right"), (3, "0.2", "left"),
                    (4, "0.4", "left"), (5, "0.3", "right")]:
    c = cs[k]
    if side == "right":
        mono(f"sd:{sd}", c.right + 2, c.cy, size=6, anchor="left")
    else:
        mono(f"sd:{sd}", c.left - 2, c.cy, size=6, anchor="right")

# ---------------- (B) backhauls: linehauls (▽) before backhauls (△)
fr, P, dep = panel(3, "Backhauls (B)")
cs = customers(P, kinds=["L", "L", "L", "B", "B", "B"])
route([dep] + cs)

# ---------------- legend bar
LEG_TOP = TOP + S + 12
items = []
bar = d.shape(0, LEG_TOP, 4 * S + 3 * GAP, 20, fill="#EBEBEB", alpha=0.15, stroke="#C0C0C0", radius=5,
              z="container")
cy = bar.cy
parts = []
m = d.box("", w=DEP, h=DEP, color="red"); parts.append((m, d.text("Depot", size=LEG_PT)))
m = d.circle(d=NODE, color="blue"); parts.append((m, d.text("Customer", size=LEG_PT)))
m = d.polygon("HorizontalTriangle", 0, 0, NODE, NODE, color="blue", rotation=90)
parts.append((m, d.text("Linehaul", size=LEG_PT)))
m = d.polygon("HorizontalTriangle", 0, 0, NODE, NODE, color="yellow", rotation=270)
parts.append((m, d.text("Backhaul", size=LEG_PT)))
ITEM_GAP, MARK_GAP = 18, 5
widths = [mk.w + MARK_GAP + t.w for mk, t in parts]
ARROW_W = 22
route_lbl = d.text("Feasible route", size=LEG_PT)
total = sum(widths) + ARROW_W + MARK_GAP + route_lbl.w + ITEM_GAP * len(parts)
x = bar.cx - total / 2
for (mk, t), w in zip(parts, widths):
    mk.place(left=x, cy=cy)
    t.place(left=mk.right + MARK_GAP, cy=cy)
    x += w + ITEM_GAP
d.line((x, cy), (x + ARROW_W, cy), route="straight", color=ROUTE, head="StickArrow", head_scale=0.5)
route_lbl.place(left=x + ARROW_W + MARK_GAP, cy=cy)

d.save(os.path.join(os.path.dirname(__file__), "out/07_vrp_variants.graffle"))
