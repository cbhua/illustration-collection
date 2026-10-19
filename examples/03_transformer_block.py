"""Rebuild of 'RouteFinder Transformer Structure' with the API (fidelity test)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ogkit import Diagram

d = Diagram(theme="crayon")
BW = 60  # block width


def block(x, title, layers):
    """layers: bottom-to-top list of (label, palette, height) or '+' for a residual add."""
    nodes = []
    y = 360
    for item in layers:
        if item == "+":
            n = d.op("+", cx=x + BW / 2, cy=y - 9, d=10, color="gray")
            y -= 18
        else:
            label, col, h = item
            n = d.box(label, x, y - h, w=BW, h=h, color=col, radius=5, size=9, stroke_width=1)
            y -= h + 12
        nodes.append(n)
    frame = d.container(nodes, None, color="gray", fill="#EBEBEB", tone=None, radius=8, pad=10)
    frame.meta["frame"].g["Style"]["fill"]["Color"]["a"] = 0.25
    d.text(title, size=10, bold=True, color="primary").place(cx=frame.cx, bottom=frame.top - 13)
    d.text("N×", size=10, color="primary").place(left=frame.meta["frame"].right - 15, top=frame.meta["frame"].bottom)
    # main path: input -> through every layer -> output
    inp = (x + BW / 2, frame.meta["frame"].bottom + 16)
    out = (x + BW / 2, frame.meta["frame"].top - 12)
    chain = [inp] + nodes + [out]
    for a, b in zip(chain, chain[1:]):
        d.arrow(a, b, head="FilledArrow", head_scale=0.5, src_side="top", dst_side="bottom", route="straight")
    # residual skips: from just below each sub-layer group, around the left, into the ⊕
    ops = [i for i, n in enumerate(nodes) if n.kind == "circle"]
    starts = [-1] + ops[:-1]
    for s_i, o_i in zip(starts, ops):
        src = chain[s_i + 1]  # the input to this sub-layer group (point or node)
        base_y = (src[1] - 6) if isinstance(src, tuple) else src.top - 6
        sx = x + BW / 2
        op = nodes[o_i]
        d.arrow((sx, base_y), op, src_side="center", dst_side="left", via=[(x - 3, base_y), (x - 3, op.cy)],
                route="ortho", head="FilledArrow", head_scale=0.5)
    return frame


a = block(0, "Attention Model", [("Multi-Head\nAttention", "attn", 29), "+", ("Norm", "norm", 15),
                                 ("Feed\nForward", "ffn", 29), "+", ("Norm", "norm", 15)])
b = block(125, "RouteFinder Transformer", [("RMS Norm", "norm", 15), ("Multi-Head\nAttention", "attn", 29), "+",
                                          ("RMS Norm", "norm", 15), ("Feed Forward\nSwiGLU", "ffn", 29), "+"])
sep = d.free_line((95, 165), (95, 390), color="#797979")

out = os.path.join(os.path.dirname(__file__), "out", "03_transformer_block.graffle")
d.save(out)
print(out)
