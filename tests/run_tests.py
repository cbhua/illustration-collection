"""Regression tests (no pytest needed):  .venv/bin/python tests/run_tests.py [--full]

--full also round-trips and renders every file in sources/OmniGraffle (slow, ~1 min)."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ogkit import Diagram, gio, render, rtf  # noqa: E402
from ogkit.validate import validate  # noqa: E402

SRC = os.path.join(ROOT, "sources", "OmniGraffle")
FULL = "--full" in sys.argv
results = []


def test(fn):
    try:
        fn()
        results.append((fn.__name__, None))
    except Exception as e:  # noqa
        import traceback
        results.append((fn.__name__, traceback.format_exc(limit=3)))
    return fn


@test
def rtf_roundtrip_unicode_and_styles():
    runs = [rtf.Run("Encoder ", "LMSans10-Regular", 8, "#005493", True),
            rtf.Run("step()", "Monaco", 7, "#941100"), rtf.Run(" 中文…✓ {x}\\", "LMSans10-Regular", 8, "#424242",
                                                                  italic=True)]
    s = rtf.from_runs(runs, "left")
    back = list(rtf.parse(s).runs())
    assert [(r.text, r.font, r.size, r.color, r.bold, r.italic) for r in back] == \
           [(r.text, r.font, r.size, r.color, r.bold, r.italic) for r in runs], back


@test
def generate_validate_render():
    d = Diagram("crayon")
    a = d.box("A", color="blue")
    b = d.box("B **bold** `mono`", color="red").right_of(a)
    c = d.container([a, b], "Group", color="purple")
    e = d.box("E", color="green").below(c, gap=30)
    d.arrow(a, b, label="x")
    d.arrow(b, e, route="ortho")
    d.arrow(e, a, route="curved", src_side="left", dst_side="bottom")
    d.badge("memory", color="blue").below(e)
    d.vrp_instance(n=5, routes=[[0, 1], [2, 3, 4]]).right_of(e, gap=40)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.graffle")
        d.save(p)
        gf = gio.load(p)
        errs = validate(gf)
        assert not errs, errs
        assert gf.preview and os.path.exists(p[:-8] + ".png")
        lines = [g for g in gf.sheets[0]["GraphicsList"] if g["Class"] == "LineGraphic"]
        assert all("Tail" in l and "Head" in l for l in lines[:3])


@test
def soft_theme_and_math():
    d = Diagram("soft")
    m = d.math(r"\mathcal{L}=\sum_i x_i^2", 0, 0)
    t = d.text("Maple Mono label", font="mono").right_of(m)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "s.graffle")
        d.save(p, png=False)
        gf = gio.load(p)
        assert any(n.endswith(".pdf") for n in gf.assets)
        assert not validate(gf)


@test
def edit_existing_file():
    src = os.path.join(SRC, "RouteFinder Transformer Structure.graffle")
    if not os.path.exists(src):
        return
    d = Diagram.open(src)
    n = d.find("Norm")
    assert n, "expected to find 'Norm'"
    x = d.box("Added", color="green").below(n[0], gap=10)
    d.arrow(n[0], x)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "e.graffle")
        d.save(p, png=False)
        gf = gio.load(p)
        assert not validate(gf)
        orig = gio.load(src)
        assert len(gf.sheets) == len(orig.sheets)


@test
def auto_theme_and_find_frame():
    src = os.path.join(SRC, "HADES Overview.graffle")
    if not os.path.exists(src):
        return
    d = Diagram.open(src)
    assert d.theme.data["palette"]["green"]["fill"] == "#D5EFD7", d.theme.data["palette"]["green"]
    assert d.theme.data["fonts"]["mono"].startswith("FiraCode")
    f = d.find_frame("Decoder")
    assert f is not None and f.g["ID"] == 454, f
    c = d.box("Critic", color="green").right_of(f, gap=12)
    d.arrow(f, c)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "h.graffle")
        d.save(p, png=False)
        gf = gio.load(p)
        assert not validate(gf)
        cw, _ = gio.parse_point(gf.sheets[0]["CanvasSize"])
        ox, _ = gio.parse_point(gf.sheets[0]["CanvasDimensionsOrigin"])
        assert ox + cw >= c.right, "canvas must grow to include new content"


@test
def layout_box_vs_extent():
    d = Diagram("crayon")
    a = d.box("A", color="blue")
    c = d.container([a], "Title", color="blue")
    b = d.box("B", color="red").right_of(c)
    assert abs(b.cy - c.cy) < 0.01  # aligned to frame, not frame+title
    e = d.box("E", color="red").below(c)
    assert e.top > c.extent[1] + c.extent[3] - 0.01


@test
def examples_run():
    for f in sorted(os.listdir(os.path.join(ROOT, "examples"))):
        if f.endswith(".py"):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "examples", f)], capture_output=True, text=True)
            assert r.returncode == 0, f + "\n" + r.stderr[-1500:]


if FULL:
    @test
    def corpus_roundtrip_and_render():
        with tempfile.TemporaryDirectory() as td:
            for f in sorted(os.listdir(SRC)):
                if not f.endswith(".graffle"):
                    continue
                a = gio.load(os.path.join(SRC, f))
                gio.save(a, os.path.join(td, "x.graffle"))
                b = gio.load(os.path.join(td, "x.graffle"))
                assert a.doc == b.doc and a.assets == b.assets, f
                render.to_png(a, None, 0, scale=0.5, max_pixels=800)

bad = 0
for name, err in results:
    print(("PASS " if err is None else "FAIL ") + name)
    if err:
        bad += 1
        print(err)
print(f"{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
