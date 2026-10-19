"""LLM-driven heuristic evolution overview, crayon theme (written by an agent from a one-paragraph request using the skill)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram

d = Diagram(theme="crayon")
GAP = 28


def frame(n):
    """Outline geometry (container frame without its title)."""
    return n.geom


def put_right(n, ref, gap=GAP):
    """right_of + align on the *frame* centre line (right_of aligns title-inclusive bounds)."""
    n.place(left=ref.right + gap)   # horizontal: titles are centred, so bounds width == frame width
    n.move(0, frame(ref).cy - frame(n).cy)
    return n


def t_at(n, x):
    f = frame(n)
    return (x - f.left) / f.w


# ---------------- inputs ----------------
seed = d.box("Seed\nHeuristic", color="green", w=60)
task = d.box("Task\nDescription", color="green", w=60).below(seed, gap=10)
inputs = d.panel([seed, task], "Inputs", title_size="small")

# ---------------- population ----------------
pop = put_right(d.population(4, color="blue", title="Population"), inputs)

# ---------------- generator (LLM + operators) ----------------
gl = d.badge("memory", size=18, color="green", label="Generator LLM")
cross = d.box("Crossover", color="orange", w=56)
mut = d.box("Mutation", color="orange", w=56).below(cross, gap=10)
cross.right_of(gl, gap=14)
mut.below(cross, gap=10)
gl.move(0, (cross.top + mut.bottom) / 2 - frame(gl).cy - 3)
gen = put_right(d.container([gl, cross, mut], None, color="green"), pop)

# ---------------- offspring ----------------
off = put_right(d.population(3, color="orange", title="Offspring"), gen)

# ---------------- evaluation ----------------
ev = d.box("Evaluation", color="yellow", w=60, h=42, valign="top")
gg = d.gauge(w=24)
gg.place(cx=ev.cx, bottom=ev.bottom - 5)
evn = put_right(d.compound([ev, gg]), off)

# ---------------- elites ----------------
eli = put_right(d.population(2, color="blue", title="Elites", ), evn)

# ---------------- reflection ----------------
rl = d.badge("memory", size=18, color="purple", label="Reflector LLM")
st = d.box("Short-term\nReflection", color="purple", w=64).right_of(rl, gap=14)
lt = d.box("Long-term\nReflection", color="purple", w=64).right_of(st, gap=14)
rl.move(0, st.cy - frame(rl).cy - 3)
refl = d.container([rl, st, lt], "Reflection", color="purple", title_size="label")
refl.place(cx=(gen.cx + ev.cx) / 2)
refl.move(0, (frame(gen).top - 42) - frame(refl).bottom)

# ---------------- flows ----------------
d.arrow(inputs, pop)
d.arrow(pop, gen)
d.arrow(gen, off)
d.arrow(off, evn)
d.arrow(evn, eli, label="select", label_side="above")
d.arrow(st, lt)
d.arrow(ev, refl, src_side="top", dst_side="bottom", dst_t=t_at(refl, ev.cx), route="straight",
        label="fitness", label_side="right")
d.arrow(refl, gen, src_side="bottom", dst_side="top", src_t=t_at(refl, rl.cx), dst_t=t_at(gen, rl.cx), route="straight",
        label="reflections", label_side="left", label_color="purple")
low = max(frame(n).bottom for n in (pop, gen, off, evn, eli)) + 14
d.arrow(eli, pop, src_side="bottom", dst_side="bottom", route="ortho",
        via=[(frame(eli).cx, low), (frame(pop).cx, low)], label="\u2002survivors\u2002", label_side="on")

d.save(os.path.join(os.path.dirname(__file__), "out", "04_llm_evolution.graffle"))
