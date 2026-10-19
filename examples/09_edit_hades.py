"""Editing an existing figure: add a Critic to HADES Overview (written by an agent from a one-paragraph request using the skill)."""
"""HADES Overview v2: add a green 'Critic' module right of the Decoder and a 'Reward' box
at the right end of the Improvement row.  Original file is NOT modified."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from ogkit import Diagram, gio

SRC = os.path.join(ROOT, "sources", "OmniGraffle", "HADES Overview.graffle")
OUT = os.path.join(os.path.dirname(__file__), "out/09_edit_hades.graffle")
if not os.path.exists(SRC):  # sources/ is private and not in git
    print("skip: " + SRC + " not found")
    sys.exit(0)

# Match the HADES pastel look (not the stock crayon colours): green = #D5EFD7 / #9FBCA4,
# connectors 0.8pt #A9A9A9 with small filled heads, FiraCode for in-figure labels.
d = Diagram.open(SRC, theme="crayon")
# Diagram.open() has no theme_overrides parameter -> reload the theme by hand
from ogkit.theme import Theme
d.theme = Theme.load("crayon", {"components": {"container": {"title_gap": 0}}})

GREEN_FILL, GREEN_STROKE, GREEN_TITLE = "#D5EFD7", "#9FBCA4", "#008F00"
BOX_STROKE, TXT = "#C0C0C0", "#797979"
LINE = dict(color="#A9A9A9", width=0.8, head="FilledArrow", head_scale=0.5)
MONO, MONO_L = "FiraCode-Regular", "FiraCode-Light"

# ---- handles on existing graphics -------------------------------------------------------
dec = d.find("Decoder")[0]                 # the title text "Decoder" (not the frame!)
dec_frame = d.find(id=454)[0]               # Decoder frame (no text -> only findable by id)
impr_frame = d.find(id=532)[0]              # Improvement frame
embed_lbl = d.find("Embed.")                # "All Nodes Embed." is split into two shapes
all_nodes = [n for n in embed_lbl if 1220 < n.cx < 1270 and n.cy > 550][0]   # #459 "Embed."
print("decoder title", dec, "frame", dec_frame, "impr", impr_frame, "src", all_nodes)

# ---- Critic module ------------------------------------------------------------------------
attn = d.find(id=421)[0]; logits = d.find(id=442)[0]; nxt = d.find(id=447)[0]
CW = 74                                          # Critic frame width
C = dec_frame.right + 14 + CW / 2                # column centre
BOX = dict(w=30, h=17, fill="#FFFFFF", stroke=BOX_STROKE, radius=5, stroke_width=1,
           font=MONO, size=8, text_color=TXT)
pool = d.box("Pool", **BOX).place(cx=C, cy=attn.cy)          # rows aligned with the Decoder column
mlp = d.box("MLP", **BOX).place(cx=C, cy=logits.cy)
val = d.shape(0, 0, 7, 7, fill=GREEN_FILL, stroke=GREEN_STROKE, stroke_width=1).place(cx=C, cy=nxt.cy)
val_lbl = d.text("Value", 0, 0, size=8, font=MONO_L, color=TXT, anchor="left")
val_lbl.place(left=val.right + 3, cy=val.cy)

# frame: pin top/bottom via pad_top/pad_bottom (min_h growth direction is not documented)
critic = d.container([pool, mlp, val], "Critic", fill="#F2FAF3", stroke=GREEN_STROKE,
                     radius=10, stroke_width=1, title_color=GREEN_TITLE, title_bold=True,
                     title_size=10, w=CW, pad_top=pool.top - dec_frame.top,
                     pad_bottom=dec_frame.bottom - val.bottom)   # exact frame height, no min_h growth

d.arrow(pool, mlp, src_side="bottom", dst_side="top", **LINE)
d.arrow(mlp, val, src_side="bottom", dst_side="top", **LINE)

# All Nodes Embed. -> Critic: leave the label downwards, run in the gap between Decoder and
# Improvement, climb in the gutter between Decoder and Critic, enter Pool from the left.
gap_y = (dec_frame.bottom + impr_frame.top) / 2
gutter_x = dec_frame.right + 7
d.arrow(all_nodes, pool, route="ortho", src_side="bottom", dst_side="left",
        via=[(all_nodes.cx, gap_y), (gutter_x, gap_y), (gutter_x, pool.cy)], **LINE)

# ---- Reward box at the right end of the Improvement row -------------------------------
reward = d.box("Reward", w=40, h=18, fill="#FFFFFF", stroke=BOX_STROKE, radius=5, stroke_width=1,
               font=MONO, size=8, text_color=TXT)
reward.place(cx=val.cx, cy=impr_frame.cy)
d.arrow(val, reward, src_side="bottom", dst_side="top", **LINE)

# widen the existing Improvement frame so the row ends under the Critic
# (critic.right is only final after save-time refit -> compute from the known frame width)
crit_right = dec_frame.right + 14 + CW
impr_frame.resize(w=crit_right - impr_frame.left, anchor="topleft")

# ---- canvas: Diagram.open keeps the original fixed canvas size -> extend it -------------
sheet = d.base_doc["Sheets"][0]
ox, oy = gio.parse_point(sheet["CanvasDimensionsOrigin"])
cw, chh = gio.parse_point(sheet["CanvasSize"])
sheet["CanvasSize"] = gio.fmt_point(int(crit_right + 1 - ox), chh)
print("canvas", sheet["CanvasDimensionsOrigin"], sheet["CanvasSize"])

d.save(OUT)
print("saved", OUT)
