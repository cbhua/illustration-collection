# ogkit API reference

All coordinates are points (pt), origin top-left, y down. Any `x, y` argument can be left at 0 and the node placed
afterwards with relative layout. Colours: palette hue names from the theme
(`blue red purple green yellow orange teal lime gray silver white dark ffn norm attn block`), a text role
(`primary secondary dim muted strong`, for text only) or `#RRGGBB`. Line colours accept an alpha suffix:
`"blue@0.5"`, `"#005493@0.5"`.
Sizes: `title heading label small tiny` or a number (pt).

## Diagram

```python
Diagram(theme="crayon" | "soft" | path.yaml | dict, title="Canvas 1", theme_overrides={...})
Diagram.open(path, theme="crayon", sheet=0)      # append to an existing .graffle
```

### Elements

| signature | notes |
|---|---|
| `box(text="", x=0, y=0, w=None, h=None, *, color="blue", tone=None, style="box", size=None, text_color=None, font=None, bold=False, italic=False, align="center", radius=None, stroke_width=None, dash=None, shadow=False, min_w=None, min_h=None, fill=None, stroke=None, shape="Rectangle", wrap_width=None, valign="middle", name=None)` | Themed element; auto-sizes to text. `style`: `box` (square, crayon@10%), `card` (rounded), `tag` (mono chip), `chip`, `frame` (white, grey outline; drawn behind lines). `tone`: `light` / `medium` (20%) / `strong` / `solid`. `wrap_width` wraps long text. |
| `text(text, x=0, y=0, *, size="label", color="secondary", font=None, bold, italic, align="center", width=None, anchor="topleft", rotation=None)` | Free auto-sized label. `anchor`: topleft, center, top, bottom, left, right, topright, bottomleft, bottomright. `font`: `sans` / `mono` / `serif` / PostScript name. |
| `caption(node, text, side="top", gap=2, size="label", color="secondary")` | Label outside a node that moves with it (`top`, `bottom`, `left`, `right`, `top-left`). |
| `tag(text, x, y, color=None)` | Mono chip (file names, tensor shapes, `</>`). |
| `circle(x, y, d=10, *, color, tone, text=None, cx=None, cy=None, fill=None, stroke=None)` | Dot / node marker. |
| `polygon(kind, x, y, w, h, *, color, tone, rotation)` | `HorizontalTriangle VerticalTriangle RightTriangle Diamond Parallelogram AdjustableStar AdjustableArrow`. `HorizontalTriangle` points right; rotation 90 = down, 180 = left, 270 = up. |
| `triangle(cx, cy, size=8, *, direction="up"/"down"/"left"/"right", color, tone)` | Marker triangle by centre (linehaul ▽ / backhaul △). |
| `shape(x, y, w, h, *, shape, fill="#hex", alpha, stroke="#hex", stroke_width, radius, dash, text, ...)` | Low level, explicit colours. |
| `image(path_or_bytes, x, y, w=None, h=None)` | PNG / JPEG / PDF / TIFF; keeps aspect when only w or h given. |
| `math(latex, x, y, *, size, color, anchor="topleft", display=False)` | LaTeX math (no `$`) → vector PDF. `size` scales from 10 pt. |
| `icon(name, x, y, size=12, *, color="blue", tone="solid")` | Library vector icon (`memory`, `message`, `settings`, `dns`, `insert-chart`, `person`, `directions-car`, `local-shipping`, `bug-report`, `check-circle`, `cancel`, `wb-incandescent`, …). |
| `snippet(name, x, y, *, width=None, scale=1, texts={old: new}, recolor={"#OLD": "#NEW"})` | Insert a library component; `width` rescales geometry and text. |

### Grouping

| signature | notes |
|---|---|
| `container(children, title=None, *, color="blue", style="container", pad=None, pad_top=None, title_pos="top", title_size=None, title_color=None, title_bold=None, dash=None, fill=None, tone=None, radius=None, stroke_width=None, min_w=None, min_h=None, w=None, h=None, stroke=None)` | Frame behind children, refitted at save. `title_pos`: `top` (centred above), `top-left`, `inside-top`, `inside-top-left`, `bottom`, `none`. `tone="light"` tints the frame. `w/h` (or `min_w/min_h`) force a minimum frame size (equal-size side-by-side panels; extra height is split evenly above/below). `pad_top`, `pad_bottom`, `pad_x` override `pad` per side. Children's captions/stack copies are included when fitting. In the `soft` theme container titles are bold by default (`title_bold=False` to disable). Returns a node you can move / connect to. |
| `panel(children, title=None, **kw)` | Lighter sub-container (grey outline). |
| `group(nodes, name=None)` | Real OmniGraffle group in the saved file. |
| `compound(nodes)` | Move several nodes as one (no group in the file). |

### Connectors

```python
line(src, dst, *, route="auto", src_side="auto", dst_side="auto", via=None, color=None, width=None,
     head="theme", tail=None, head_scale=None, dash=None, label=None, label_pos=0.5, label_side="auto",
     label_size=None, label_color=None, label_bg=None, label_offset=(0, 0), src_t=0.5, dst_t=0.5,
     src_at=None, dst_at=None, src_gap=None, dst_gap=None, curve=0.35)
arrow(src, dst, **same)          # alias
connect_chain([a, b, c], **kw)   # a→b→c
fan_out(src, [t1, t2, t3], side="right", bus=None, **kw)   # one → many through a shared vertical bus (comb)
fan_in([s1, s2, s3], dst, side="left", bus=None, **kw)     # many → one
free_line((x1, y1), (x2, y2), color=, width=, head=, tail=, dash=, via=[...])   # unconnected decoration
# e.g. a time-window bar |—|:  d.free_line((x0, y), (x1, y), color="blue@0.5", head="NegativeControls", tail="NegativeControls")
```

- `src`/`dst`: a node or an `(x, y)` point. Lines are *bound* to nodes (they follow when moved in OmniGraffle).
- `route`: `auto` (straight if the facing sides overlap, else orthogonal), `straight`, `ortho`, `curved`.
- `src_side`/`dst_side`: `left right top bottom center auto`; `src_t`/`dst_t` slide the port along the side (0…1, clamped);
  `src_at`/`dst_at` give the port as an absolute coordinate (y on left/right sides, x on top/bottom) — e.g. a vertical
  arrow between two boxes: `d.arrow(a, b, src_side="bottom", dst_side="top", src_at=x, dst_at=x)`.
- `src_gap`/`dst_gap`: pt left free between the line end and the node (default 3 when the node is a text label).
- `label_pos` defaults to the middle of the longest segment (never on a corner); `label_side="on"` masks the line with a
  padded white background.
- Connections are *bound* (Head/Tail IDs) for simple nodes, containers (frame), badges and `vrp_instance` (frame).
  Other compounds (`matrix`, `legend`, `compound`) and `(x, y)` points give unbound lines.
- `via`: waypoints, e.g. a loop under everything: `via=[(x0, y_low), (x1, y_low)]`.
- `head`/`tail`: `FilledArrow StickArrow Arrow FilledBall Ball FilledDiamond Diamond None`; theme default otherwise.
- `dash=True` uses the theme pattern. `label_side`: `auto above below left right on`.
- `curve`: bend for `route="curved"` (sign flips the side).

### Layout

```python
node.right_of(other, gap=None, align="center"|"top"|"bottom")
node.left_of(...); node.below(other, gap, align="center"|"left"|"right"); node.above(...)
node.place(x=, y=, left=, right=, top=, bottom=, cx=, cy=)   # absolute, by any edge/centre
node.move(dx, dy); node.resize(w=, h=)
d.row(nodes, gap=None, align="center", x=None, y=None)
d.column(nodes, gap=None, align="center", x=None, y=None)
d.grid(nodes, cols, gap_x=None, gap_y=None, x=0, y=0)
d.align(nodes, "left"|"right"|"top"|"bottom"|"cx"|"cy", to=None)
d.distribute(nodes, axis="x"|"y", start=None, end=None)
d.same_size(nodes, w=True, h=True)
```

Node geometry: `x y w h left right top bottom cx cy center` and `anchor(side, t)` refer to the **layout box** —
for a container that is its *frame* (title excluded), for a badge its square, for a `vrp_instance` its frame.
`node.extent` is the full bbox including titles/captions; `right_of/below/...` keep extents apart (titles never collide)
and align layout boxes (frames line up). `node.geom` is the node lines attach to.
Gaps default to the theme spacing (`crayon`: 16, `soft`: 24).

**z-order** (every element takes `z=`): `back < container < line < under < node < text < front`.
Containers nest automatically (outer frame behind inner). Give a background box `z="container"` so connectors
show on top of it; `box(style="frame")` without text does this by default.

### Motifs (components)

| call | draws |
|---|---|
| `badge(icon, x, y, size=16, color, tone, frame=True, label=None)` | Material icon in a rounded square (icon = 64 % of `size`, also when `frame=False`), optional caption |
| `code_chip("</>", x, y, color, w, h)` | code chip |
| `population(items=3 or [labels], x, y, *, color, title, frame=True, ellipsis=True)` | column of chips with `......` |
| `matrix(rows, cols, x, y, *, cell=9, color, tone, row_labels, col_labels, highlight=[(r,c)], highlight_color=None, highlight_tone="strong", label_font="mono")` | feature grid (highlight defaults to a stronger tone of the same hue); `.meta["cells"]` |
| `vector(n, x, y, *, cell=9, color, vertical=False, highlight=[i])` | 1×n cells |
| `bar(x, y, w=38, h=9, *, color, text=None)` | embedding bar |
| `trapezoid(x, y, w=20, h=56, *, narrow="right"/"left"/"top"/"bottom", ratio=.6, color="gray")` | encoder funnel |
| `stack(node, n=2, dx=4, dy=-4)` | offset copies behind a box |
| `op("+"|"x", cx=, cy=, d=10)` | ⊕ / ⊗ |
| `vrp_instance(x, y, w=60, h=60, *, n=8, seed=0, routes=[[i,...],...], labels=False, points=[(u,v)...], depot_at=(0.5,0.5), open_routes=False, route_colors=("gray",))` | routing instance; returns node with `.meta["depot"]`, `.meta["customers"]` (for custom markers use `circle`/`triangle` + `arrow(..., src_side="center", dst_side="center")`) |
| `legend([(kind, color, label[, tone]), ...], x, y, horizontal=True, frame=False/True/"pill", tone="medium")` | kinds: `box square circle triangle-up triangle-down line arrow dashed`; `arrow` uses the theme head; `frame="pill"` = rounded light-grey bar |
| `section_bar(text, x, y, w=300, color)` | poster section header |
| `gauge(x, y, w=15, level="high"/"low")` | performance gauge |
| `ellipsis(x, y, vertical=False, cx=, cy=)` | `......`, or ⋮ as three dots when `vertical=True` |

### Helpers

```python
d.theme.swatch("blue", "light")   # {'fill', 'alpha', 'stroke', 'text'} of a hue — use for custom shapes
d.theme.text_color("secondary")    # resolve a text role / hue to #hex
d.theme.size("label")              # role -> pt
d.free_line((x1, y1), (x2, y2), color="gray", head=None, dash=True)   # decoration that moves with compounds
```

### Output

```python
d.save("fig.graffle", png=True, preview=True, scale=3)   # .graffle (+ embedded preview) + fig.png
d.render("fig.png", scale=3)
d.to_graffle()                                           # GraffleFile object
```

### Editing existing figures

```python
d = Diagram.open("sources/OmniGraffle/HADES Overview.graffle")   # theme="auto": style derived from the file
d.theme.data["palette"]["green"], d.theme.data["fonts"], d.theme.data["line"]  # what was inferred
dec   = d.find_frame("Decoder")                  # container frame under/around a title label
embed = d.find("Embed.", contains=True)          # label search: exact | contains=True | regex=True
near  = d.find(near=(1300, 560), radius=20)      # shapes by position (nearest first); d.find(id=454)
crit  = d.box("Critic", color="green").right_of(dec, gap=12)   # "green" = this file's green pair
d.arrow(dec, crit)
dec.resize(w=dec.w + 40, anchor="topleft")       # found nodes are LIVE: move/resize edits the original shapes
d.save("figures/hades_v2/hades_v2.graffle")      # never overwrite sources/
```

- `Diagram.open(path, theme="auto" | "crayon" | ..., theme_overrides={...}, base_theme="crayon", sheet=0)`.
  Auto-theme infers: main sans + mono font, label/small/heading sizes, connector colour/width/head/head-scale/
  corner radius, and for each colour family the file's most common (fill, alpha, stroke, text). Hues missing from
  the file fall back to `base_theme`.
- New graphics go on top of the existing ones; `z="back"`/`"container"` items go behind them.
- The canvas grows automatically to include new content.
- Labels split over two shapes ("All Nodes" + "Embed.") must be searched by one part (`contains=True`).
- Per-line `corner_radius=` overrides the theme (match an original's r=4 elbows).
- Container fills accept alpha: `fill="#D5EFD7@0.3"`.

## Library & CLI

```bash
.venv/bin/python -m ogkit library search <words>       # icons / images / snippets / past figures (ranked, OR + synonyms)
.venv/bin/python -m ogkit inspect FILE.graffle --max 200 # read a figure (colours, fonts, geometry)
.venv/bin/python -m ogkit render FILE.graffle -o out.png --scale 3
.venv/bin/python -m ogkit validate FILE.graffle
.venv/bin/python -m ogkit compare A.graffle B.graffle -o cmp.png
.venv/bin/python -m ogkit themes
```

Images worth knowing (`library/images/...`): `logo/llm/{openai,anthropic,gemini}`, `logo/org/{kaist,ai4co,rl4co,omelet,stanford}`,
`logo/framework/{pytorch,pytorch-lightning,torchrl,hydra}`, `logo/venue/{neurips,aamas-2025}`,
`icon/service/*` (data-collection, data-lake, dashboard, …), `icon/gauge-{low,high}`, `texture/*` (scalar fields, signals,
turbulence, loss landscape) and `avatar/{pear,duck}`.
