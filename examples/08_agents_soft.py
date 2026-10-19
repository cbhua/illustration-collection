"""Multi-agent research assistant workflow, soft theme (written by an agent from a one-paragraph request using the skill)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram

d = Diagram(theme="soft")
HERE = os.path.dirname(__file__)
LOGO = os.path.join(ROOT, "library", "images", "logo", "llm")


def agent(name, icon, color, frame=True):
    """Agent = tinted card holding a badge icon + its name (one hue per agent)."""
    b = d.badge(icon, size=30, color=color, tone="light", frame=frame)
    t = d.text(name, size="label", color=color, align="left")
    t.right_of(b, gap=8)
    return d.container([b, t], None, color=color, tone="light", title_pos="none", pad=10)


# ---------------- user ----------------
user_ic = d.icon("person", size=40, color="gray")
user = d.compound([user_ic])
d.caption(user_ic, "User", side="bottom", gap=4, color="secondary")

# ---------------- planner ----------------
planner = agent("Planner\nAgent", "assignment", "blue").right_of(user, gap=110)

# ---------------- sub-tasks ----------------
tasks = [d.box(f"Task {i}", color="blue", style="card", w=86) for i in (1, 2, 3)]
d.column(tasks, gap=10)
dots = d.ellipsis(vertical=True, cx=tasks[-1].cx, cy=tasks[-1].bottom + 16)
tasks_p = d.panel(tasks + [dots], "Sub-tasks", pad=10).right_of(planner, gap=40)

# ---------------- per-task execution ----------------
coder = agent("Coder\nAgent", "create", "orange")
code = d.code_chip("</>", color="orange", w=44, h=26, size="label").right_of(coder, gap=34)
sandbox = agent("Sandbox", "dns", "gray", frame=False).right_of(code, gap=34)
reviewer = agent("Reviewer\nAgent", "rate-review", "yellow").right_of(sandbox, gap=40)
loop = d.container([coder, code, sandbox, reviewer], "for each sub-task", color="gray", dash=True,
                   title_pos="top-left", title_bold=False, title_size="small", pad=16,
                   pad_top=16 + 26, pad_bottom=16 + 26)   # symmetric room for the fail loop
loop.right_of(tasks_p, gap=40)

# ---------------- writer ----------------
writer = agent("Report\nWriter", "subject", "purple").right_of(loop, gap=50)
report = d.tag("report.md", color="purple").right_of(writer, gap=30)

# ---------------- LLM backends (top-right) ----------------
def logo(fname, h=20):
    return d.image(os.path.join(LOGO, fname), h=h)   # library logos are trimmed + transparent


logos = [logo("openai.png", 20), logo("anthropic.png", 15), logo("gemini.png", 22)]
d.row(logos, gap=34)
d.align(logos, "cy")
caps = [d.caption(img, name, side="bottom", gap=5, size="tiny")   # captions count when fitting the panel
        for img, name in zip(logos, ("OpenAI", "Anthropic", "Gemini"))]
d.align(caps, "top", to=max(c.top for c in caps))
llm = d.panel(logos, "LLM backend (swappable)", pad=10, title_size="small")
llm.place(right=report.right, bottom=writer.top - 18)

# ---------------- flows ----------------
d.arrow(user_ic, planner, label="research\nquestion", label_side="above")
d.fan_out(planner, tasks, bus=planner.right + 20)
d.arrow(tasks_p, loop)
d.arrow(coder, code)
d.arrow(code, sandbox, label="run")
d.arrow(sandbox, reviewer, label="result")
y_loop = coder.bottom + 20
d.arrow(reviewer, coder, src_side="bottom", dst_side="bottom", route="ortho", color="red", dash=True,
        via=[(reviewer.cx, y_loop), (coder.cx, y_loop)], label="fail → revise", label_color="red",
        label_side="below")
d.arrow(reviewer, writer, label="pass", label_color="green", color="green")
d.arrow(writer, report)

d.save(os.path.join(HERE, "out/08_agents_soft.graffle"))
