"""ogkit command line.

    python -m ogkit render   FILE.graffle [-o out.png|out.svg] [--sheet N] [--scale 3] [--all-sheets]
    python -m ogkit inspect  FILE.graffle [--sheet N] [--max 300]
    python -m ogkit validate FILE.graffle ...
    python -m ogkit analyze  CORPUS_DIR [-o style/corpus_stats.json]
    python -m ogkit library  build CORPUS_DIR | search WORDS...
    python -m ogkit themes                      # list themes + palettes
    python -m ogkit compare  A.graffle B.graffle -o side_by_side.png   # render two files side by side
"""
from __future__ import annotations

import sys


def _themes(argv):
    from .theme import Theme, list_themes
    for name in list_themes():
        t = Theme.load(name)
        print(f"{name}: {t.data.get('description', '').strip()[:160]}")
        print(f"   fonts: {t.data['fonts']}")
        print(f"   sizes: {t.data['sizes']}")
        print(f"   palette: {', '.join(t.palette_names())}")


def _compare(argv):
    import argparse
    import io
    from PIL import Image
    from . import gio, render
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("-o", "--out", default="compare.png")
    a = ap.parse_args(argv)
    ims = []
    for f in (a.a, a.b):
        im = Image.open(io.BytesIO(render.to_png(gio.load(f), None, 0, scale=2))).convert("RGB")
        im.thumbnail((1200, 1200))
        ims.append(im)
    s = Image.new("RGB", (ims[0].width + ims[1].width + 30, max(i.height for i in ims)), "white")
    s.paste(ims[0], (0, 0))
    s.paste(ims[1], (ims[0].width + 30, 0))
    s.save(a.out)
    print(a.out)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, argv = sys.argv[1], sys.argv[2:]
    if cmd == "render":
        from .render import main as m
        m(argv)
    elif cmd == "inspect":
        from .inspect import main as m
        m(argv)
    elif cmd == "validate":
        from .validate import main as m
        m(argv)
    elif cmd == "analyze":
        from .analyze import main as m
        m(argv)
    elif cmd == "library":
        from .library import main as m
        m(argv)
    elif cmd == "themes":
        _themes(argv)
    elif cmd == "compare":
        _compare(argv)
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        sys.exit(2)


if __name__ == "__main__":
    main()
