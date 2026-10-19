"""Every built-in component on one canvas (visual regression sheet)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ogkit import Diagram

theme = sys.argv[1] if len(sys.argv) > 1 else "crayon"
d = Diagram(theme=theme)
T = lambda s, x, y: d.text(s, x, y, size="heading", color="primary")

T("Boxes / palette", 0, 0)
x = 0
for c in d.theme.palette_names():
    b = d.box(c, x, 22, color=c)
    x = b.right + 6
x = 0
for c in ("blue", "red", "green", "purple"):
    b = d.box(f"{c} medium", x, 44, color=c, tone="medium", style="card")
    x = b.right + 6

T("Badges & icons", 0, 80)
x = 0
for ic, col in [("memory", "blue"), ("message", "green"), ("settings", "purple"), ("dns", "orange"),
                ("insert-chart", "yellow"), ("bug-report", "red"), ("person", "gray")]:
    b = d.badge(ic, x, 102, size=18, color=col, label=ic)
    x += 40

T("Code chips / population", 300, 80)
p = d.population(4, 300, 104, color="blue", title="Population")
p2 = d.population(3, 360, 104, color="red", title="Elites")
d.arrow(p, p2)

T("Matrix / vector / bar / trapezoid / op", 0, 170)
m = d.matrix(3, 5, 30, 196, color="green", row_labels=["Node 1", "...", "Node N"], highlight=[(1, 2)])
v = d.vector(4, 110, 205, color="purple")
b1 = d.bar(160, 196, color="blue", text="Embed.")
b2 = d.bar(160, 210, color="blue")
tz = d.trapezoid(215, 192, 18, 36, narrow="right")
o = d.op("+", cx=255, cy=210, d=10)
o2 = d.op("x", cx=275, cy=210, d=10)

T("VRP instance + routes", 300, 170)
inst = d.vrp_instance(300, 192, 70, 70, n=7, seed=3, routes=[[0, 1, 2], [3, 4], [5, 6]])
inst2 = d.vrp_instance(385, 192, 70, 70, n=7, seed=3)

T("Stack / caption / legend / section bar", 0, 280)
card = d.box("Solutions", 10, 315, w=60, h=40, style="frame", color="white", text_color="secondary")
d.stack(card, n=2)
d.caption(card, "Partitions", side="bottom")
lg = d.legend([("square", "red", "Depot"), ("circle", "blue", "Customer"), ("arrow", "gray", "Route"),
               ("dashed", "gray", "Optional")], 100, 330)
sb = d.section_bar("Summary", 300, 300, w=160, color="blue")
sb2 = d.section_bar("Methodology", 300, 326, w=160, color="red")

T("Math (LaTeX → PDF)", 0, 380)
d.math(r"\mathcal{L}_{\mathrm{RL}} = -\mathbb{E}_{\pi_\theta}[R(\tau)]", 0, 402, size="heading")
d.math(r"\alpha_i = \frac{\exp(e_i)}{\sum_j \exp(e_j)}", 200, 400, size="label", color="blue")

T("Snippets from your files", 300, 380)
s1 = d.snippet("tile-mlp", 300, 402, width=40)
s2 = d.snippet("graph-k4-blue", 350, 402, width=70)
s3 = d.snippet("token-stack-history", 440, 395, width=40)
s1.move(0, 0); d.snippet("tile-lstm", 300, 470, width=40); d.snippet("card-gru-cell", 350, 470, width=60)

out = os.path.join(os.path.dirname(__file__), "out", f"02_components_{theme}.graffle")
d.save(out)
print(out)
