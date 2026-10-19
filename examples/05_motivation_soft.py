"""Motivation comparison (manual vs ours), soft theme (written by an agent from a one-paragraph request using the skill)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram

d = Diagram(theme="soft")
SW = d.theme.swatch  # palette lookup: SW("blue") -> {fill, stroke, text, alpha}

W = 236           # stage-box width
GAP = 18          # vertical gap between stages
COL_GAP = 56      # gap between the two panels
STROKE = "#A9A9A9"
ROW_H, ROW_GAP, ROW_PAD = 40, 6, 9


def stage(h, w=W, **kw):
    """White rounded stage box, drawn in the background layer so scene lines stay visible."""
    return d.box(kw.pop("text", ""), w=w, h=h, color="white", stroke=STROKE, radius=6, z="container", **kw)


def scene(x, y, s=44, goal=True):
    """Tiny social-navigation scene: pedestrians with dashed trajectories, robot -> goal."""
    k = s / 44.0
    # z="line": a z="container" shape created *after* the stage box would be sorted behind it
    d.shape(x, y, s, s, fill="#FFFFFF", stroke="#C0C0C0", z="line")
    peds = [((14, 10), (3, 3)), ((29, 17), (43, 19)), ((32, 31), (42, 42)), ((14, 26), (3, 14))]
    for (px, py), (ex, ey) in peds:
        c = d.circle(cx=x + px * k, cy=y + py * k, d=5 * k, color="blue")
        d.line(c, (x + ex * k, y + ey * k), route="curved", src_side="center", dst_side="center",
               color="blue", dash=True, head=None, curve=0.3)
    rob = d.box("", x + 4 * k, y + 35 * k, 5 * k, 5 * k, color="orange", radius=0)
    if goal:
        gx, gy = x + 37 * k, y + 7 * k
        r = 2.5 * k
        d.free_line((gx - r, gy - r), (gx + r, gy + r), color="red", head=None)
        d.free_line((gx - r, gy + r), (gx + r, gy - r), color="red", head=None)
        d.line(rob, (gx - 4 * k, gy + 4 * k), route="curved", src_side="center", dst_side="center",
               color="orange", dash=True, head="StickArrow", curve=-0.3)


# ------------------------------------------------------------------ stage boxes
rew_h = 3 * ROW_H + 2 * ROW_GAP + 2 * ROW_PAD
L_tasks, L_exp, L_rew = stage(64), stage(32), stage(rew_h)
code = ("[purple]{def} [blue]{cal_reward}(state):\n"
        "    [muted]{# danger punish}\n"
        "    ...\n"
        "    [muted]{# sparse punish}\n"
        "    ...\n"
        "    [muted]{# speed punish}\n"
        "    ...\n"
        "    [purple]{return} reward")
R_tasks, R_llm = stage(64), stage(32)
R_code = stage(rew_h, text=code, font="mono", size="small", align="left", text_color="secondary")

d.column([L_tasks, L_exp, L_rew], gap=GAP, x=0, y=0)
d.column([R_tasks, R_llm, R_code], gap=GAP, x=W + COL_GAP, y=0)

# ------------------------------------------------------------------ stage contents
for b in (L_tasks, R_tasks):
    scene(b.left + 12, b.cy - 22)
    d.text("Social Navigation\nTasks", font="mono", color="secondary", align="right",
           x=b.right - 14, y=b.cy, anchor="right")

for b, ic_name, label, hue in ((L_exp, "person", "Human Expert", "blue"),
                               (R_llm, "message", "LLMs + Evolution", "red")):
    t = d.text(label, font="mono", color="secondary")
    ic = d.icon(ic_name, 0, 0, size=16, fill=SW(hue)["stroke"])
    total = ic.w + 8 + t.w
    ic.place(left=b.cx - total / 2, cy=b.cy)
    t.place(left=ic.right + 8, cy=b.cy)

for i, (name, formula) in enumerate([("Success", r"R = 10"), ("Collision", r"R = -20"),
                                     ("Other", r"R = 2 \times \mathrm{dist\_to\_goal}")]):
    top = L_rew.top + ROW_PAD + i * (ROW_H + ROW_GAP)
    s = ROW_H
    scene(L_rew.left + 12, top, s=s)
    nt = d.text(name, font="mono", color="secondary")
    fm = d.math(formula, size="label", color="secondary")
    blk_h = nt.h + 2 + fm.h
    nt.place(left=L_rew.left + 12 + s + 12, top=top + (s - blk_h) / 2)
    fm.place(left=nt.left, top=nt.bottom + 2)

# ------------------------------------------------------------------ panels + flow arrows
LP = d.container([L_tasks, L_exp, L_rew], "Manual Reward Design", color="blue", tone="light",
                 title_bold=False, pad=12, radius=10)
RP = d.container([R_tasks, R_llm, R_code], "EvoNav (Ours)", color="red", tone="light",
                 pad=12, radius=10)
for a, b, hue in ((L_tasks, L_exp, "blue"), (L_exp, L_rew, "blue"),
                  (R_tasks, R_llm, "red"), (R_llm, R_code, "red")):
    d.arrow(a, b, src_side="bottom", dst_side="top", color=hue)

# ------------------------------------------------------------------ comparison boxes
cons = ["Need human expert", "Trial-and-error pipeline", "Suboptimal effectiveness"]
pros = ["Automatically design", "Evolutionary pipeline", "SOTA effectiveness"]
LINE_H, CPAD = 22, 10
box_h = 3 * LINE_H + 2 * CPAD - 4
LC = d.box("", w=LP.w, h=box_h, color="blue", fill="#FFFFFF", dash=True, radius=6, z="container")
RC = d.box("", w=RP.w, h=box_h, color="red", fill="#FFFFFF", dash=True, radius=6, z="container")
LC.place(left=LP.left, top=LP.bottom + 20)
RC.place(left=RP.left, top=LP.bottom + 20)
for i, (a, b) in enumerate(zip(cons, pros)):
    cy = LC.top + CPAD + LINE_H / 2 + i * LINE_H - 2
    ta = d.text(a, color=SW("blue")["text"], x=LC.right - 16, y=cy, anchor="right")
    tb = d.text(b, color=SW("red")["text"], x=RC.left + 16, y=cy, anchor="left")
    # unbound points so the arrow keeps a small gap to both texts
    d.arrow((ta.right + 5, cy), (tb.left - 5, cy), route="straight", color="red")

d.save(os.path.join(os.path.dirname(__file__), "out", "05_motivation_soft.graffle"))
