---
name: omnigraffle-figure
description: Generate or edit editable OmniGraffle (.graffle) figures in Chuanbo's personal style — paper overview/architecture diagrams, pipelines, LLM-evolution loops, motivation comparisons, routing/VRP illustrations, posters sections. Use whenever the user asks for an illustration, figure, diagram, 插图, 示意图, 框架图, 流程图, overview, or wants to modify / read / render a .graffle file. Output is a native .graffle (connected lines, real text, recolourable icons) plus a PNG preview.
---

# OmniGraffle figure skill

You generate figures by **writing a short Python script against `ogkit`**, running it, looking at the
PNG it renders, and iterating. The `.graffle` you produce opens in OmniGraffle 7 as fully editable
native objects, so the user can fine-tune it by hand.

Repo root: the folder containing `ogkit/`, `style/`, `library/` (this skill lives in `.claude/skills/`).
Python: always `.venv/bin/python` from the repo root (has pillow, cairosvg, pypdfium2, pyyaml).

## Workflow (follow in order)

1. **Understand the content** before drawing: list the entities (boxes), groups (containers), flows
   (arrows, with labels), and what must be emphasised ("ours"). Decide reading direction (default left→right,
   feedback loops underneath).
2. **Pick the theme**: `crayon` (default; paper figures, 8pt LM Sans labels, Monaco for code) or `soft`
   (2026 pastel look; labels in Maple Mono Light 14pt, container titles LM Sans bold; slides/blog). Colours carry meaning — assign one hue per concept and keep it consistent
   (blue = encoder/main module, purple = decoder/profile, red = environment/failure, green = input/LLM generator/pass,
   yellow = global/evaluation, orange = mutation/secondary, gray/white = neutral panels).
3. **Find references & assets** (cheap, do it):
   - `.venv/bin/python -m ogkit library search <words>` → icons, images (logos, LLM-provider logos), snippets, and
     *similar past figures*. Thumbnails: `library/CATALOG.md`, `library/gallery/*.jpg`.
   - To imitate a past figure closely: `.venv/bin/python -m ogkit inspect "sources/OmniGraffle/<name>.graffle" --max 200`
     shows every element with colours/fonts/sizes.
   - Complete worked scripts to copy patterns from: `examples/01_pipeline.py` (encoder–decoder–env loop),
     `03_transformer_block.py` (residual blocks), `04_llm_evolution.py` (population / LLM / reflection loop),
     `05_motivation_soft.py` (two-panel comparison, soft), `06_routing_solver.py` (instance + matrices + encoder/decoder),
     `07_vrp_variants.py` (multi-panel problem illustration + legend), `08_agents_soft.py` (agent workflow, fan-out,
     logos, soft), `09_edit_hades.py` (editing an existing file).
     Read the one closest to your task before writing yours.
4. **Write the script** at `figures/<slug>/make.py` (create the folder). Use **relative layout**
   (`right_of`, `below`, `row`, `column`, `container`) — never hand-compute dozens of coordinates. Template below.
5. **Run it**: `.venv/bin/python figures/<slug>/make.py` → writes `<slug>.graffle` and `<slug>.png`.
6. **Look at the PNG with the Read tool** and critique it against the checklist. Fix and re-run. Expect 2–4 iterations.
7. **Validate**: `.venv/bin/python -m ogkit validate figures/<slug>/<slug>.graffle` must print `OK`.
8. Report the `.graffle` and `.png` paths. Mention fonts needed on the Mac (LM Sans 10, Monaco/Maple Mono) only if
   you used something unusual.

## Script template

```python
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram

d = Diagram(theme="crayon")

# --- nodes (auto-sized to their text) ---
inst = d.box("Instance", style="frame", color="white", w=60, h=44, text_color="secondary")
emb  = d.box("Init\nEmbedding", color="blue")
enc  = d.box("Encoder\nLayers", color="blue").right_of(emb, gap=14)
E    = d.container([emb, enc], "Encoder", color="blue").right_of(inst, gap=36)
ctx  = d.box("Context", color="purple")
attn = d.box("Multi-Head\nAttention", color="purple").right_of(ctx, gap=14)
D    = d.container([ctx, attn], "Decoder", color="purple").right_of(E, gap=36)
env  = d.box("Environment", color="red", style="card", size="heading").below(D, gap=30)

# --- connections (bound to shapes; routed at save time) ---
d.arrow(inst, emb); d.arrow(emb, enc); d.arrow(enc, ctx); d.arrow(ctx, attn)
d.arrow(attn, env, src_side="bottom", dst_side="top", label="`step()`", label_color="red")
d.arrow(env, inst, src_side="left", dst_side="bottom", route="ortho", label="`reset()`", label_color="green")

d.save(os.path.join(os.path.dirname(__file__), "pipeline.graffle"))   # also writes pipeline.png
```

Text supports mini-markup: `**bold**`, `*italic*`, `` `mono` ``, `^{sup}`, `_{sub}`, `[red]{coloured}`, `\n` = new line.
Real math: `d.math(r"\mathcal{L}_{\mathrm{RL}}", x, y, size="label", anchor="left")` (LaTeX → vector PDF).

Full API: see `reference.md` next to this file. Most-used calls:

| need | call |
|---|---|
| themed element | `d.box(text, color=, tone="light"/"medium", style="box"/"card"/"tag"/"frame", w=, h=, size=)` |
| free label | `d.text(text, x, y, size="label"/"small"/"heading"/"title", color="secondary"/hue, anchor=)` |
| label attached to a node | `d.caption(node, text, side="top"/"bottom"/"left"/"right")` |
| group frame with title | `d.container(nodes, "Title", color=, dash=True, title_pos="top"/"top-left"/"inside-top")`, lighter: `d.panel(...)` |
| one→many / many→one | `d.fan_out(src, [a, b, c])`, `d.fan_in([a, b, c], dst)` (shared bus, like your planner→tasks combs) |
| arrow | `d.arrow(a, b, route="auto"/"straight"/"ortho"/"curved", src_side=, dst_side=, via=[(x,y)], label=, dash=True, color=, head="FilledArrow"/"StickArrow"/None)` |
| layout | `n.right_of(m, gap)`, `.below()`, `.left_of()`, `.above()`, `.place(cx=, top=, ...)`, `d.row(nodes)`, `d.column(nodes)`, `d.grid(nodes, cols)`, `d.align(nodes, "cy")`, `d.same_size(nodes)` |
| motifs | `d.badge("memory", color=)`, `d.icon(name, x, y, size)`, `d.code_chip()`, `d.population(4, title=)`, `d.matrix(r, c, row_labels=)`, `d.vector(n)`, `d.bar()`, `d.trapezoid()`, `d.stack(node)`, `d.op("+")`, `d.vrp_instance(routes=)`, `d.legend([...])`, `d.section_bar()`, `d.gauge()` |
| library | `d.snippet("tile-mlp", x, y, width=40)`, `d.image("library/images/logo/llm/openai.png", x, y, w=14)` |
| edit existing file | `d = Diagram.open("x.graffle")` (style auto-derived from the file); `d.find("Encoder")`, `d.find_frame("Decoder")`, `d.find(near=(x, y))`; add things; `d.save("figures/x_v2/x_v2.graffle")` — inspect + render the original first |

## Style rules (from 120 past figures — see docs/style-guide.md)

- White background; **light fill + same-hue dark stroke** for elements; containers are white with a coloured
  outline and a coloured title centred above. No shadows, no gradients, no thick black borders.
- Connectors are thin grey (`#A9A9A9`, 1pt) with small arrow heads; colour a connector only when it carries
  meaning (e.g. red `step()`, green `reset()`). Prefer straight/orthogonal lines, keep them axis-aligned.
- Fonts: LM Sans 10 for text; mono (`` `...` `` or `font="mono"`) for code, variables, tensor shapes, file names,
  `</>`; LaTeX (`d.math`) for real formulas. Sizes by role, not numbers: title > heading > label > small.
- Annotations in grey (`color="secondary"`), placed outside boxes; keep box texts to 1–3 words per line.
- Repeated structures: show 2–3 items + an ellipsis (`......` or `...`) + the last item (Node 1 … Node N).
- Same-role elements share size and alignment (`d.same_size`, `d.align`). Gaps: siblings ~10–20pt, containers ~30–40pt.
- Max ~5 hues per figure. "Ours"/highlight = `tone="medium"` or a coloured title, not a new hue.

## Review checklist (apply to the PNG every iteration)

1. Nothing overlaps unintentionally (text vs lines, titles vs other containers); labels readable.
2. Arrows start/end on the correct sides, no line crosses through an unrelated box; loops go around, not through.
3. Alignment: rows share a centre line, columns share x; equal gaps; containers padded evenly.
4. Colour semantics consistent; grey for neutral; ≤5 hues.
5. Reading order obvious (left→right / top→bottom); the key contribution stands out.
6. Canvas is tight (no huge empty areas); figure width suits its use (one column ≈ 240pt, full width ≈ 500pt at crayon scale).

## Other tools

- Render any file: `.venv/bin/python -m ogkit render file.graffle -o out.png --scale 3` (`--all-sheets` for multi-page).
- Compare two files: `.venv/bin/python -m ogkit compare a.graffle b.graffle -o cmp.png`.
- Themes: `.venv/bin/python -m ogkit themes`. Overrides: `Diagram(theme="crayon", theme_overrides={"fonts": {"mono": "MapleMono-NF-CN-Regular"}})`.
- Rebuild the asset library after the user adds new figures: `.venv/bin/python -m ogkit library build sources/OmniGraffle`
  (curation in `library/curation.yaml`), refresh stats: `.venv/bin/python -m ogkit analyze sources/OmniGraffle`.
- macOS final export with OmniGraffle itself: `osascript tools/og_export.applescript in.graffle out.pdf`.

## Pitfalls

- Never write raw plist by hand; always go through `ogkit` (IDs, RTF, image registration, z-order are handled).
- `container()` frames are refitted to their children at save time — position children first or move the container
  (moving a container moves its children). A container's `top/cy/h/...` are its frame; `.extent` includes the title.
- Background boxes you draw yourself should get `z="container"` so lines stay visible on top.
- For vertical/horizontal arrows between offset boxes use `src_at=`/`dst_at=` instead of computing `src_t`.
- `route="auto"` picks straight when ports align, otherwise orthogonal; specify `src_side/dst_side` for loops.
- Arrow labels default beside the line (`label_side="auto"`); use `label_side="on"` to sit on the line with a white mask.
- The Linux PNG is a faithful preview, but emoji are not rendered; avoid emoji in labels (use icons instead).
