"""Multi-vehicle routing solver overview, crayon theme (written by an agent from a one-paragraph request using the skill)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram
from ogkit.colors import og_color

d = Diagram(theme="crayon")
HERE = os.path.dirname(__file__)
NODE, VEH = "blue", "orange"          # customer/node hue, vehicle hue


def vdots(cx, top, gap=2.6, dia=1.4):
    """Vertical ellipsis drawn as 3 dots (LM Sans has no U+22EE glyph -> d.ellipsis(vertical=True) is blank)."""
    dots = [d.circle(cx=cx, cy=top + dia / 2 + i * gap, d=dia, fill="#8E8E8E", stroke=None) for i in range(3)]
    return d.compound(dots)


def feat_table(first_labels, last_label, color, cols=4, cell=7):
    """Feature table: first rows, a '...' gap row, last row (Node 1, Node 2, ..., Node N)."""
    top = d.matrix(len(first_labels), cols, 0, 0, cell=cell, color=color, row_labels=first_labels)
    gap = vdots(0, 0)
    gap.place(cx=top.meta["cells"][0].left + cols * cell / 2, top=top.bottom + 1.5)
    bot = d.matrix(1, cols, 0, 0, cell=cell, color=color, row_labels=[last_label])
    bot.place(right=top.right, top=gap.bottom + 1.5)
    lab_dots = vdots(0, 0)
    lab_dots.place(cx=top.members[-1].cx, cy=gap.cy)   # under the last row label
    return d.compound([top, gap, bot, lab_dots])


def emb_stack(n_first, color, w=40, h=6):
    bars = [d.bar(w=w, h=h, color=color) for _ in range(n_first)]
    d.column(bars, gap=3)
    dots = vdots(bars[0].cx, bars[-1].bottom + 2)
    last = d.bar(w=w, h=h, color=color)
    last.place(left=bars[0].left, top=dots.bottom + 2)
    return d.compound(bars + [dots, last]), bars + [last]


# ------------------------------------------------------------------ Instances (left)
vrp = d.vrp_instance(0, 0, w=74, h=58, n=8, seed=3, frame=False,
                     routes=[[0, 1, 2, 3], [4, 5, 6, 7]], route_colors=(VEH, VEH))
nf_lab = d.text("Node Features", size="small", color="secondary")
nf = feat_table(["Node 1", "Node 2"], "Node N", NODE)
vf_lab = d.text("Vehicle Features", size="small", color="secondary")
vf = feat_table(["Vehicle 1"], "Vehicle M", VEH)
nf_lab.below(vrp, gap=8)
nf.below(nf_lab, gap=3)
vf_lab.below(nf, gap=8)
vf.below(vf_lab, gap=3)
d.align([nf, vf], "right")
I = d.container([vrp, nf_lab, nf, vf_lab, vf], "Instances", color="gray", pad=8)

# ------------------------------------------------------------------ Encoder (blue)
trap = d.trapezoid(0, 0, w=20, h=60, narrow="right", color="blue")
# trapezoid forces alpha>=0.5 -> too saturated next to 10% boxes; tone it down to the 20% "medium" tint
trap.g["Style"]["fill"]["Color"] = og_color(d.theme.swatch("blue")["fill"], 0.2)
trap.place(left=I.right + 26)
trap.place(top=nf.cy - 0.35 * trap.h)   # nf -> trap enters straight at t=0.35
d.caption(trap, "Initial\nEmbedding", side="top", size="small", gap=4)
encl = d.box("Encoder\nLayers", color="blue", w=40, h=60).right_of(trap, gap=18)
d.stack(encl, n=2, dx=3, dy=-3)
d.caption(encl, "× L", side="bottom", size="small", gap=3)

NE, ne_bars = emb_stack(2, NODE)
VE, ve_bars = emb_stack(1, VEH)
NE.place(left=encl.right + 22, bottom=encl.cy - 8)
VE.place(left=NE.left, top=encl.cy + 8)
ne_lab = d.caption(NE, "Node\nEmbeddings", side="top", size="small")
ve_lab = d.caption(VE, "Vehicle\nEmbeddings", side="bottom", size="small")

E = d.container([trap, encl, NE, VE], "Encoder", color="blue", pad=8)

# ------------------------------------------------------------------ Decoder (purple)
mha = d.box("MHA", color="attn", w=24, h=40, size="small")
nrm = d.box("Norm", color="norm", w=24, h=40, size="small")
mlp = d.box("MLP", color="ffn", w=24, h=40, size="small")
d.row([mha, nrm, mlp], gap=8)
COMM = d.panel([mha, nrm, mlp], "Communication Layer", title_size="small", pad=6, title_pos="inside-top")
COMM.place(left=E.right + 34)
COMM.move(0, VE.cy - mha.cy)   # K port level with the vehicle embeddings
ptr = d.box("Multiple\nPointer", color="purple", tone="medium", w=40, h=10)
ptr.resize(h=COMM.cy - NE.cy + 22)
ptr.place(left=COMM.right + 16, top=NE.cy - 11)
qkv_parts = []
# Q, K, V into the communication MHA (self-attention among vehicles)
for t, q in ((0.25, "Q"), (0.5, "K"), (0.75, "V")):
    y = mha.anchor("left", t)[1]
    d.arrow((COMM.left - 12, y), mha.anchor("left", t), route="straight", head_scale=0.5)
    lab = d.text(f"`{q}`", size="tiny", color="secondary")
    lab.place(cx=(COMM.left - 12 + mha.left) / 2 - 1, bottom=y + 0.5)   # above its arrow, right of the bus
    qkv_parts.append(lab)
d.free_line((VE.right + 1, VE.cy), (COMM.left - 12, VE.cy), color="#A9A9A9")
bus = d.free_line((COMM.left - 12, mha.anchor("left", 0.25)[1]), (COMM.left - 12, mha.anchor("left", 0.75)[1]),
            color="#A9A9A9")
# container() has no min_h / explicit height: an invisible spacer makes the Decoder frame match the Encoder's
# NB: E.top / E.h include the container title; use E.geom (the frame) for the frame box
spacer = d.shape(COMM.left, E.geom.top + 8, 1, E.geom.h - 16, fill=None, stroke=None)
D = d.container([COMM, ptr, bus, spacer] + qkv_parts, "Decoder", color="purple", pad=8)

# per-vehicle action probabilities (one pointer per vehicle)
p1 = d.matrix(1, 5, cell=6, color="purple", highlight=[(0, 1)], highlight_color="purple")
pm = d.matrix(1, 5, cell=6, color="purple", highlight=[(0, 3)], highlight_color="purple")
for v, k in ((p1, 1), (pm, 3)):     # highlight in same hue = invisible; bump the chosen cell to "medium"
    c = v.meta["cells"][k]
    c.g["Style"]["fill"]["Color"] = og_color(d.theme.swatch("purple")["fill"], 0.45)
p1.place(left=D.right + 20, cy=ptr.top + 10)
pm.place(left=p1.left, cy=ptr.bottom - 10)
pdots = vdots(p1.cx, 0)
pdots.place(cx=p1.cx, cy=(p1.cy + pm.cy) / 2)
v1c = d.caption(p1, "Vehicle 1", side="top", size="tiny")
d.caption(pm, "Vehicle M", side="bottom", size="tiny")
PROB = d.compound([p1, pdots, pm])
prob_t = d.text("Action\nProbabilities", size="small", color="secondary")
prob_t.place(cx=PROB.cx, bottom=v1c.top - 2)

# ------------------------------------------------------------------ Environment (red)
env = d.box("Environment", color="red", style="card", size="heading", w=110, h=24)
env.place(cx=(E.cx + D.cx) / 2, top=max(E.bottom, D.bottom) + 30)

# ------------------------------------------------------------------ arrows
d.arrow(nf, trap, src_side="right", dst_side="left", dst_t=0.35, route="straight")
d.arrow(vf, trap, src_side="right", dst_side="left", dst_t=0.7, route="ortho")
d.arrow(trap, encl)
d.arrow(encl, NE, dst_side="left")
d.arrow(encl, VE, dst_side="left")
d.arrow(mha, nrm, head_scale=0.5)
d.arrow(nrm, mlp, head_scale=0.5)
d.arrow(COMM, ptr, dst_side="left", src_side="right")
d.arrow(NE, ptr, src_side="right", dst_side="left", route="straight")
d.arrow(ptr, p1, src_side="right", dst_side="left", route="ortho")
d.arrow(ptr, pm, src_side="right", dst_side="left", route="ortho")
d.arrow(PROB, env, src_side="bottom", dst_side="right", route="ortho",
        label="`step(actions)`", label_color="red", label_pos=0.75, label_side="above")
d.arrow(env, I, src_side="left", dst_side="bottom", route="ortho",
        label="`reset()`", label_color="green", label_pos=0.3, label_side="above")

# ------------------------------------------------------------------ legend
leg = d.legend([("square", "red", "Depot"), ("circle", NODE, "Customer"), ("arrow", VEH, "Vehicle route")])
leg.place(cx=(I.left + PROB.right) / 2, top=max(env.bottom, I.bottom) + 12)

d.save(os.path.join(os.path.dirname(__file__), "out", "06_routing_solver.graffle"))
