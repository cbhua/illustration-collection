"""Encoder–decoder pipeline in the crayon (paper) style."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ogkit import Diagram

d = Diagram(theme="crayon")

# instance panel
inst = d.box("Instance", w=60, h=44, style="frame", color="white", size="label", text_color="secondary")
# encoder
emb = d.box("Init\nEmbedding", color="blue")
layers = d.box("Encoder\nLayers", color="blue").right_of(emb, gap=14)
enc = d.container([emb, layers], "Encoder", color="blue")
enc.right_of(inst, gap=36)
# decoder
ctx = d.box("Context", color="purple")
attn = d.box("Multi-Head\nAttention", color="purple").right_of(ctx, gap=14)
dec = d.container([ctx, attn], "Decoder", color="purple")
dec.right_of(enc, gap=36)
# environment below
env = d.box("Environment", color="red", style="card", text_color="red", size="heading")
env.below(dec, gap=30)

d.arrow(inst, emb)
d.arrow(emb, layers)
d.arrow(layers, ctx)
d.arrow(ctx, attn)
d.arrow(attn, env, src_side="bottom", dst_side="right", label="step()", label_color="red")
d.arrow(env, inst, src_side="left", dst_side="bottom", label="reset()", label_color="green")
d.math(r"\pi_\theta(a_t \mid s_t)", anchor="left").place(left=attn.right + 8, cy=attn.cy)

out = os.path.join(os.path.dirname(__file__), "out", "01_pipeline.graffle")
d.save(out)
print(out)
