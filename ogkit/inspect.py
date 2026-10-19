"""Print a compact, token-cheap outline of a .graffle document.

Designed for agents: one line per graphic with id, kind, geometry, resolved colours,
font and text.  Use it to *read* an existing figure before editing or imitating it.

    python -m ogkit.inspect figure.graffle [--sheet 0] [--max 400] [--no-text]
"""
from __future__ import annotations

import argparse

from . import gio, rtf
from .colors import ColorContext, to_hex


def _yes(v, d=True):
    if v is None:
        return d
    return v is True or str(v).upper() in ("YES", "TRUE", "1")


def _c(cc, c, default=(0, 0, 0, 1)):
    r = cc.to_rgba(c, default)
    h = to_hex(r)
    return h if r[3] >= 0.999 else f"{h}@{round(r[3], 2)}"


def describe(g, cc, depth=0, show_text=True) -> list[str]:
    ind = "  " * depth
    cls = g.get("Class")
    st = g.get("Style", {})
    fill, stroke = st.get("fill", {}), st.get("stroke", {})
    gid = g.get("ID")
    lines = []
    if cls in ("Group", "TableGroup"):
        name = f' "{g["Name"]}"' if g.get("Name") else ""
        lines.append(f"{ind}#{gid} {cls}{name} ({len(g.get('Graphics', []))} children)")
        for c in g.get("Graphics", []):
            lines += describe(c, cc, depth + 1, show_text)
        return lines
    if cls == "LineGraphic":
        pts = [gio.parse_point(p) for p in g.get("Points", [])]
        lt = {None: "straight", 1: "curved", 2: "ortho"}.get(stroke.get("LineType"), "?")
        tail = g.get("Tail", {}).get("ID")
        head = g.get("Head", {}).get("ID")
        conn = f" {tail if tail is not None else '·'}->{head if head is not None else '·'}"
        arrows = ""
        if stroke.get("HeadArrow") not in (None, "0"):
            arrows += f" head={stroke['HeadArrow']}x{stroke.get('HeadScale', 1)}"
        if stroke.get("TailArrow") not in (None, "0"):
            arrows += f" tail={stroke['TailArrow']}x{stroke.get('TailScale', 1)}"
        dash = f" dash={stroke['Pattern']}" if stroke.get("Pattern") else ""
        rad = f" r={stroke['CornerRadius']}" if stroke.get("CornerRadius") else ""
        p = " ".join(f"({x:.0f},{y:.0f})" for x, y in pts)
        lines.append(f"{ind}#{gid} line[{lt}]{conn} {_c(cc, stroke.get('Color'))} w={stroke.get('Width', 1)}{arrows}{dash}{rad} {p}")
        return lines
    x, y, w, h = gio.parse_rect(g.get("Bounds", "{{0,0},{0,0}}"))
    shape = g.get("Shape", "Rect")
    if g.get("ImageID") is not None:
        shape = f"Image({g.get('ImageID')})"
    f = _c(cc, fill.get("Color"), (1, 1, 1, 1)) if _yes(fill.get("Draws")) else "-"
    s = _c(cc, stroke.get("Color")) if _yes(stroke.get("Draws")) else "-"
    extra = []
    if _yes(stroke.get("Draws")) and stroke.get("Width", 1) != 1:
        extra.append(f"w={stroke.get('Width')}")
    if stroke.get("CornerRadius"):
        extra.append(f"r={stroke['CornerRadius']}")
    if stroke.get("Pattern"):
        extra.append(f"dash={stroke['Pattern']}")
    if g.get("Rotation"):
        extra.append(f"rot={g['Rotation']}")
    if g.get("Line"):
        extra.append(f"label-on-line={g['Line'].get('ID')}")
    if _yes(st.get("shadow", {}).get("Draws"), False) and "shadow" in st:
        extra.append("shadow")
    txt = ""
    if show_text and g.get("Text", {}).get("Text"):
        rt = rtf.parse(g["Text"]["Text"])
        if rt.plain.strip():
            r0 = next((r for r in rt.runs() if r.text.strip()), None)
            fs = f"{r0.font} {r0.size:g}{' b' if r0.bold else ''}{' i' if r0.italic else ''} {r0.color}" if r0 else ""
            al = rt.paragraphs[0].align[0] if rt.paragraphs else "?"
            t = rt.plain.replace("\n", "⏎")
            if len(t) > 80:
                t = t[:77] + "..."
            txt = f' [{fs} {al}] "{t}"'
    lines.append(f"{ind}#{g.get('ID')} {shape} ({x:.0f},{y:.0f} {w:.0f}x{h:.0f}) fill={f} stroke={s}"
                 + (" " + " ".join(extra) if extra else "") + txt)
    return lines


def outline(gf: gio.GraffleFile, sheet: int = 0, show_text=True, limit: int | None = None) -> str:
    cc = ColorContext(gf.doc)
    s = gf.sheets[sheet]
    out = [f"# sheet {sheet}: {s.get('SheetTitle')}  canvas={s.get('CanvasSize')}  "
           f"layers={[l.get('Name') for l in s.get('Layers', [])]}  (list is front-to-back)"]
    for g in s.get("GraphicsList", []):
        out += describe(g, cc, 0, show_text)
    if limit and len(out) > limit:
        out = out[:limit] + [f"... ({len(out) - limit} more lines)"]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("graffle")
    ap.add_argument("--sheet", type=int, default=0)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--no-text", action="store_true")
    a = ap.parse_args(argv)
    gf = gio.load(a.graffle)
    print(f"{len(gf.sheets)} sheet(s); assets={sorted(gf.assets)[:12]}{'...' if len(gf.assets) > 12 else ''}")
    print(outline(gf, a.sheet, not a.no_text, a.max))


if __name__ == "__main__":
    main()
