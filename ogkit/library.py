"""Asset library: build it from a corpus of .graffle files, and use it at runtime.

Build (one-off, re-run when you add new figures)::

    python -m ogkit.library build sources/OmniGraffle

produces::

    library/
      icons/icons.json            vector icons (OmniGraffle custom shapes) + thumbnails
      images/<category>/...        reusable bitmaps / PDFs (icons, logos, shared figures)
      images/images.json
      snippets/<name>.json         reusable components (groups) + thumbnails
      snippets/index.json
      gallery/<figure>.jpg         one thumbnail per source figure
      gallery/gallery.json         metadata/tags of every source figure
      CATALOG.md                   human-readable overview with thumbnails

Runtime (used by ogkit.Diagram)::

    python -m ogkit.library search "llm"        # find icons / snippets / images
    d.icon("memory", x, y, 14, color="blue")
    d.snippet("chip-code-blue", x, y)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import statistics
from collections import Counter, defaultdict

from . import gio, rtf
from .colors import ColorContext, to_hex

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "library")


def slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", s.strip().lower()).strip("-")
    return re.sub(r"-+", "-", s)[:60] or "item"


# ===========================================================================
# building
# ===========================================================================

def _path_sig(es: dict) -> str:
    els = es.get("StrokePath", {}).get("elements", [])
    norm = []
    for e in els:
        norm.append((e.get("element"), e.get("point"), e.get("control1"), e.get("control2")))
    return hashlib.sha1(repr(norm).encode()).hexdigest()[:12]


def build_icons(corpus: str, out: str):
    defs, uses, names, aspects, sources = {}, Counter(), defaultdict(Counter), defaultdict(list), defaultdict(set)
    for f in sorted(os.listdir(corpus)):
        if not f.endswith(".graffle"):
            continue
        gf = gio.load(os.path.join(corpus, f))
        for s in gf.sheets:
            local = {}
            for es in s.get("ExportShapes", []) or []:
                sig = _path_sig(es)
                local[es["ShapeName"]] = sig
                defs.setdefault(sig, es)
            for g, _, _ in gio.iter_graphics(s.get("GraphicsList", [])):
                sh = g.get("Shape")
                if sh in local:
                    sig = local[sh]
                    uses[sig] += 1
                    sources[sig].add(f[:-8])
                    if g.get("Name"):
                        names[sig][g["Name"]] += 1
                    x, y, w, h = gio.parse_rect(g["Bounds"])
                    if w > 0:
                        aspects[sig].append(h / w)
    icons = {}
    for sig, es in defs.items():
        nm = names[sig].most_common(1)[0][0] if names[sig] else es["ShapeName"]
        key = slug(nm)
        if key in icons:
            key = f"{key}-{sig[:4]}"
        d = copy.deepcopy(es)
        # keep OmniGraffle's own name (pdfImport-N): proven to open; names are unique across the corpus
        icons[key] = {"name": nm, "def": d, "uses": uses[sig], "files": sorted(sources[sig])[:8],
                      "aspect": round(statistics.median(aspects[sig]), 3) if aspects[sig] else 1.0}
    os.makedirs(out, exist_ok=True)
    json.dump(dict(sorted(icons.items(), key=lambda kv: -kv[1]["uses"])), open(os.path.join(out, "icons.json"), "w"),
              indent=1)
    _icon_sheet(icons, os.path.join(out, "icons.png"))
    return icons


def _icon_sheet(icons: dict, path: str):
    import cairosvg
    from .render import SVGRenderer  # noqa
    items = sorted(icons.items(), key=lambda kv: -kv[1]["uses"])
    cols, cell = 8, 96
    rows = (len(items) + cols - 1) // cols
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols * cell}" height="{rows * cell}">'
             f'<rect width="100%" height="100%" fill="white"/>']
    for i, (key, ic) in enumerate(items):
        r, c = divmod(i, cols)
        x, y = c * cell + 28, r * cell + 14
        s = 40
        d = _svg_path(ic["def"]["StrokePath"]["elements"], x, y, s, s * ic.get("aspect", 1))
        parts.append(f'<path d="{d}" fill="#005493" fill-rule="evenodd"/>')
        parts.append(f'<text x="{c * cell + cell / 2}" y="{r * cell + 78}" font-size="10" text-anchor="middle" '
                     f'font-family="Latin Modern Sans">{key[:16]}</text>')
        parts.append(f'<text x="{c * cell + cell / 2}" y="{r * cell + 90}" font-size="8" fill="#999" text-anchor="middle" '
                     f'font-family="Latin Modern Sans">×{ic["uses"]}</text>')
    parts.append("</svg>")
    cairosvg.svg2png(bytestring="".join(parts).encode(), write_to=path)


def _svg_path(elements, x, y, w, h):
    def P(s):
        px, py = gio.parse_point(s)
        return f"{x + (px + 0.5) * w:.2f} {y + (py + 0.5) * h:.2f}"
    out = []
    for e in elements:
        el = e.get("element")
        if el == "MOVETO":
            out.append("M " + P(e["point"]))
        elif el == "LINETO":
            out.append("L " + P(e["point"]))
        elif el == "CURVETO":
            out.append(f"C {P(e['control1'])} {P(e['control2'])} {P(e['point'])}")
        elif el == "CLOSE":
            out.append("Z")
    return " ".join(out)


# ---------------------------------------------------------------- images

def _classify_image(data: bytes, ext: str, disp: tuple[float, float]) -> str:
    w, h = disp
    if ext == "pdf":
        if b"Matplotlib" in data or b"matplotlib" in data:
            return "plot"
        if re.search(rb"/(CMMI|CMR|CMSY|CMEX|CMBX|LMRoman|LMMath|MSBM|EUSM|CMMIB)\d*", data) or re.search(
                rb"\+(CM|LM)[A-Z]+\d", data):
            return "math"
    if max(w, h) <= 48:
        return "icon"
    if max(w, h) <= 140 and ext in ("png", "pdf", "tiff"):
        return "logo"
    if ext in ("jpg", "jpeg"):
        return "photo"
    return "figure"


def build_images(corpus: str, out: str, min_files: int = 2):
    seen: dict[str, dict] = {}
    for f in sorted(os.listdir(corpus)):
        if not f.endswith(".graffle"):
            continue
        gf = gio.load(os.path.join(corpus, f))
        for s in gf.sheets:
            for g, _, _ in gio.iter_graphics(s.get("GraphicsList", [])):
                iid = g.get("ImageID")
                if iid is None:
                    continue
                name = gf.image_name(iid)
                data = gf.assets.get(name) if name else None
                if not data:
                    continue
                h = hashlib.sha1(data).hexdigest()[:12]
                x, y, w, hh = gio.parse_rect(g["Bounds"])
                e = seen.setdefault(h, {"hash": h, "ext": os.path.splitext(name)[1].lstrip(".").lower(),
                                        "files": set(), "uses": 0, "sizes": [], "names": Counter(), "data": data})
                e["files"].add(f[:-8])
                e["uses"] += 1
                e["sizes"].append((w, hh))
                if g.get("Name"):
                    e["names"][g["Name"]] += 1
    import shutil
    import yaml
    cur_path = os.path.join(os.path.dirname(out), "curation.yaml")
    cur = yaml.safe_load(open(cur_path)) if os.path.exists(cur_path) else {}
    keep_map = {str(k): v for k, v in (cur.get("keep") or {}).items()}
    drop = {str(x) for x in (cur.get("drop") or [])}
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    index = {}
    counts = Counter()
    for h, e in seen.items():
        ws = statistics.median(s[0] for s in e["sizes"])
        hs = statistics.median(s[1] for s in e["sizes"])
        cat = _classify_image(e["data"], e["ext"], (ws, hs))
        counts[cat] += 1
        h8 = h[:8]
        if h8 in drop:
            continue
        if h8 in keep_map:
            key = keep_map[h8]
            category = key.split("/")[0]
        else:
            reusable = cat == "icon" or ((len(e["files"]) >= min_files or e["names"])
                                         and cat not in ("math", "plot", "figure"))
            if not reusable or len(e["data"]) > 3_000_000:
                continue
            base = e["names"].most_common(1)[0][0] if e["names"] else f"{sorted(e['files'])[0]}-{h[:6]}"
            key = "_candidates/" + slug(base)
            category = "_candidates"
        data, ext = e["data"], e["ext"]
        if key.split("/")[0] in ("logo", "icon", "avatar") and ext in ("png", "jpg", "jpeg", "tiff"):
            data, ext = _clean_raster(data, ext)
        rel = f"{key}.{ext}"
        os.makedirs(os.path.dirname(os.path.join(out, rel)), exist_ok=True)
        open(os.path.join(out, rel), "wb").write(data)
        index[key] = {"file": rel, "category": category, "uses": e["uses"], "files": sorted(e["files"])[:10],
                      "display_size": [round(ws, 1), round(hs, 1)],
                      "name": key.split("/")[-1], "hash": h}
    json.dump(dict(sorted(index.items())), open(os.path.join(out, "images.json"), "w"), indent=1)
    _image_sheet(index, out)
    return index, counts


def _clean_raster(data: bytes, ext: str):
    """Logos/icons: white JPEG backgrounds -> transparent, trim empty margins, save as PNG."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return data, ext
    px = im.load()
    w, h = im.size
    if ext in ("jpg", "jpeg"):
        for yy in range(h):
            for xx in range(w):
                r, g, b, a = px[xx, yy]
                m = min(r, g, b)
                if m > 235:  # near white -> fade out (keeps anti-aliasing soft)
                    px[xx, yy] = (r, g, b, int(255 * (255 - m) / 20))
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        m = 2
        im = im.crop((max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m)))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), "png"


def _image_sheet(index: dict, out: str):
    from PIL import Image, ImageDraw
    from .render import _pdf_to_png
    for cat in sorted({v["category"] for v in index.values()}):
        items = [(k, v) for k, v in index.items() if v["category"] == cat]
        items.sort(key=lambda kv: -kv[1]["uses"])
        cols, cell = 8, 120
        rows = (len(items) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell, max(1, rows) * cell), "white")
        d = ImageDraw.Draw(sheet)
        for i, (k, v) in enumerate(items):
            r, c = divmod(i, cols)
            try:
                data = open(os.path.join(out, v["file"]), "rb").read()
                if v["file"].endswith(".pdf"):
                    data = _pdf_to_png(data, 2)
                im = Image.open(io.BytesIO(data)).convert("RGBA")
                im.thumbnail((cell - 16, cell - 34))
                bg = Image.new("RGBA", im.size, "white")
                bg.alpha_composite(im)
                sheet.paste(bg.convert("RGB"), (c * cell + (cell - im.width) // 2, r * cell + 6))
            except Exception:
                pass
            d.text((c * cell + 4, r * cell + cell - 24), k.split("/", 1)[-1][-22:], fill="black")
            d.text((c * cell + 4, r * cell + cell - 13), f"x{v['uses']}", fill="gray")
        sheet.save(os.path.join(out, f"_sheet_{cat.strip('_')}.jpg"), quality=85)


# ---------------------------------------------------------------- snippets

def _norm_group(g: dict, cc: ColorContext):
    """Signature of a group: classes, shapes, relative geometry, colours, texts."""
    x0, y0, _, _ = _gbounds(g)
    sig = []
    for c, _, _ in gio.iter_graphics(g.get("Graphics", [])):
        if "Bounds" in c:
            x, y, w, h = gio.parse_rect(c["Bounds"])
            geo = (round((x - x0) / 2), round((y - y0) / 2), round(w / 2), round(h / 2))
        else:
            geo = tuple(round(v / 2) for p in c.get("Points", []) for v in gio.parse_point(p))
        st = c.get("Style", {})
        col = to_hex(cc.to_rgba(st.get("fill", {}).get("Color"), (1, 1, 1, 1)))
        txt = rtf.parse(c["Text"]["Text"]).plain if c.get("Text", {}).get("Text") else ""
        sig.append((c.get("Class"), c.get("Shape"), geo, col, txt))
    return hashlib.sha1(repr(sig).encode()).hexdigest()[:12]


def _gbounds(g: dict):
    xs, ys, xe, ye = [], [], [], []
    for c, _, _ in gio.iter_graphics([g]):
        if "Bounds" in c and c.get("Class") != "Group":
            x, y, w, h = gio.parse_rect(c["Bounds"])
            xs.append(x)
            ys.append(y)
            xe.append(x + w)
            ye.append(y + h)
        for p in c.get("Points", []):
            px, py = gio.parse_point(p)
            xs.append(px)
            ys.append(py)
            xe.append(px)
            ye.append(py)
    if not xs:
        return (0, 0, 0, 0)
    return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))


def _snippet_texts(g):
    out = []
    for c, _, _ in gio.iter_graphics([g]):
        t = c.get("Text", {}).get("Text")
        if t:
            p = rtf.parse(t).plain.strip()
            if p:
                out.append(p)
    return out


def build_snippets(corpus: str, out: str, max_children: int = 60):
    found: dict[str, dict] = {}
    for f in sorted(os.listdir(corpus)):
        if not f.endswith(".graffle"):
            continue
        gf = gio.load(os.path.join(corpus, f))
        cc = ColorContext(gf.doc)
        mod = str(gf.doc.get("ModificationDate"))[:10]
        for si, s in enumerate(gf.sheets):
            for g, depth, _ in gio.iter_graphics(s.get("GraphicsList", [])):
                if g.get("Class") != "Group":
                    continue
                n = sum(1 for _ in gio.iter_graphics(g["Graphics"]))
                if n < 2 or n > max_children:
                    continue
                sig = _norm_group(g, cc)
                e = found.setdefault(sig, {"sig": sig, "files": set(), "count": 0, "group": g, "gf": gf,
                                           "sheet": si, "name": g.get("Name"), "modified": mod, "n": n})
                e["files"].add(f[:-8])
                e["count"] += 1
                if g.get("Name") and not e["name"]:
                    e["name"] = g["Name"]
    # keep: named, or repeated (>=2 occurrences), or a top-level component with text
    keep = [e for e in found.values() if e["name"] or e["count"] >= 2]
    keep.sort(key=lambda e: (-len(e["files"]), -e["count"], e["sig"]))
    import shutil
    import yaml
    cur_path = os.path.join(os.path.dirname(out), "curation.yaml")
    cur = (yaml.safe_load(open(cur_path)) or {}).get("snippets") if os.path.exists(cur_path) else None
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    if cur:
        cur = {str(k): v for k, v in cur.items()}
        cands = [e for e in keep if e["sig"][:8] not in cur]
        json.dump([{"sig": e["sig"][:8], "name": e["name"], "texts": _snippet_texts(e["group"])[:6],
                    "files": sorted(e["files"]), "count": e["count"], "children": e["n"]} for e in cands],
                  open(os.path.join(out, "_candidates.json"), "w"), indent=1, ensure_ascii=False)
        keep = [e for e in keep if e["sig"][:8] in cur]
        for e in keep:
            e["curated"] = cur[e["sig"][:8]]
    index = {}
    for e in keep[:400]:
        g = copy.deepcopy(e["group"])
        texts = _snippet_texts(g)
        nm = e["name"] if e["name"] and not re.match(r"(?i)^group\b", e["name"]) else None
        base = e.get("curated") or nm or (texts[0] if texts else f"group-{e['sig'][:6]}")
        key = slug(f"{base}")
        if key in index or not key:
            key = f"{key}-{e['sig'][:4]}"
        x, y, w, h = _gbounds(g)
        _translate(g, -x, -y)
        # carry referenced images and custom shapes
        assets, shapes = {}, []
        gf = e["gf"]
        es = {d["ShapeName"]: d for d in gf.sheets[e["sheet"]].get("ExportShapes", []) or []}
        for c, _, _ in gio.iter_graphics([g]):
            if c.get("ImageID") is not None:
                nm = gf.image_name(c["ImageID"])
                if nm and nm in gf.assets:
                    import base64
                    assets[str(c["ImageID"])] = {"ext": os.path.splitext(nm)[1].lstrip("."),
                                                 "data": base64.b64encode(gf.assets[nm]).decode()}
            if c.get("Shape") in es:
                shapes.append(es[c["Shape"]])
        cc = ColorContext(gf.doc)
        _normalize_colors(g, cc)
        snip = {"name": key, "title": base, "texts": texts[:20], "size": [round(w, 1), round(h, 1)],
                "files": sorted(e["files"]), "count": e["count"], "modified": e["modified"],
                "graphics": [g], "assets": assets, "export_shapes": shapes}
        json.dump(snip, open(os.path.join(out, f"{key}.json"), "w"))
        index[key] = {k: snip[k] for k in ("title", "texts", "size", "files", "count", "modified")}
        index[key]["children"] = e["n"]
        index[key]["sig"] = e["sig"][:8]
        try:
            _render_snippet(snip, os.path.join(out, f"{key}.png"))
        except Exception as ex:  # noqa
            index[key]["render_error"] = str(ex)[:200]
    json.dump(index, open(os.path.join(out, "index.json"), "w"), indent=1, ensure_ascii=False)
    return index


def _normalize_colors(g, cc):
    """Rewrite P3/ICC colours as sRGB so snippets are self-contained."""
    from .colors import og_color
    for c, _, _ in gio.iter_graphics([g]):
        for sec in ("fill", "stroke", "shadow"):
            d = c.get("Style", {}).get(sec, {})
            for k in ("Color", "GradientColor"):
                if isinstance(d.get(k), dict):
                    r = cc.to_rgba(d[k])
                    d[k] = og_color(r[:3], r[3])


def _translate(g, dx, dy):
    for c, _, _ in gio.iter_graphics([g]):
        if "Bounds" in c:
            x, y, w, h = gio.parse_rect(c["Bounds"])
            c["Bounds"] = gio.fmt_rect(x + dx, y + dy, w, h)
        if "Points" in c:
            c["Points"] = [gio.fmt_point(*(lambda p: (p[0] + dx, p[1] + dy))(gio.parse_point(p))) for p in c["Points"]]
        lp = c.get("LogicalPath", {}).get("elements")
        if lp:
            for e in lp:
                for k in ("point", "control1", "control2"):
                    if k in e:
                        px, py = gio.parse_point(e[k])
                        e[k] = gio.fmt_point(px + dx, py + dy)
        if "OrthogonalBarPoint" in c and c["OrthogonalBarPoint"] != "{0, 0}":
            px, py = gio.parse_point(c["OrthogonalBarPoint"])
            c["OrthogonalBarPoint"] = gio.fmt_point(px + dx, py + dy)


def _snippet_doc(snip: dict) -> gio.GraffleFile:
    import base64
    import plistlib
    tdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    doc = plistlib.load(open(os.path.join(tdir, "document.plist"), "rb"))
    sheet = plistlib.load(open(os.path.join(tdir, "sheet.plist"), "rb"))
    sheet["GraphicsList"] = copy.deepcopy(snip["graphics"])
    if snip.get("export_shapes"):
        sheet["ExportShapes"] = snip["export_shapes"]
    doc["Sheets"] = [sheet]
    assets = {}
    for iid, a in snip.get("assets", {}).items():
        nm = f"image{iid}.{a['ext']}"
        assets[nm] = base64.b64decode(a["data"])
        doc["ImageList"].append(nm)
    return gio.GraffleFile(doc, assets)


def _render_snippet(snip, path):
    from . import render
    gf = _snippet_doc(snip)
    w, h = snip["size"]
    scale = max(1.0, min(4.0, 220.0 / max(w, h, 1)))
    render.to_png(gf, path, 0, scale=scale, margin=4)


# ---------------------------------------------------------------- gallery

_KIND_RULES = [
    (r"poster", "poster"), (r"logo|icon|cover", "logo/cover"), (r"\bui\b|demo|cheatsheet", "ui/cheatsheet"),
    (r"statistic|plot|pareto|result|baselines|visualization|experiment|cynobactera", "plot/visualization"),
    (r"motivation|compare|rebuttal|new ideas", "motivation/comparison"),
    (r"overview|overall|model|structure|policy|uml|process|blueprint|framework|copilot|agent", "overview/architecture"),
    (r"illustration|example|description|sampling|map|squeeze|hitree", "illustration"),
]


def build_gallery(corpus: str, out: str, stats_path: str | None = None):
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    gal = {}
    for f in sorted(os.listdir(corpus)):
        if not f.endswith(".graffle"):
            continue
        name = f[:-8].strip()
        gf = gio.load(os.path.join(corpus, f))
        kind = next((k for pat, k in _KIND_RULES if re.search(pat, name.lower())), "illustration")
        fonts = Counter()
        for s in gf.sheets[:1]:
            for g, _, _ in gio.iter_graphics(s.get("GraphicsList", [])):
                t = g.get("Text", {}).get("Text")
                if t:
                    for r in rtf.parse(t).runs():
                        fonts[r.font] += len(r.text)
        thumb = f"{slug(name)}.jpg"
        im = None
        try:  # full first sheet (OmniGraffle's own preview is often cropped to the window)
            from . import render
            im = Image.open(io.BytesIO(render.to_png(gf, None, 0, scale=1.5, max_pixels=1400))).convert("RGB")
        except Exception:
            if gf.preview:
                im = Image.open(io.BytesIO(gf.preview)).convert("RGB")
        if im is not None:
            im.thumbnail((800, 800))
            im.save(os.path.join(out, thumb), quality=82)
        gal[name] = {"file": f"sources/OmniGraffle/{f}", "thumb": thumb, "kind": kind,
                     "modified": str(gf.doc.get("ModificationDate"))[:10],
                     "sheets": [s.get("SheetTitle") for s in gf.sheets],
                     "graphics": sum(1 for s in gf.sheets for _ in gio.iter_graphics(s.get("GraphicsList", []))),
                     "fonts": [k for k, _ in fonts.most_common(3)]}
    json.dump(gal, open(os.path.join(out, "gallery.json"), "w"), indent=1, ensure_ascii=False)
    return gal


def write_catalog(lib: str, icons, images, snippets, gallery, counts):
    L = ["# Asset library catalog", "",
         "Auto-generated by `python -m ogkit.library build sources/OmniGraffle` — do not edit by hand.", "",
         f"* **{len(icons)} vector icons** (OmniGraffle custom shapes, recolourable) — `d.icon(name, x, y, size, color=...)`",
         f"* **{len(images)} reusable images** — `d.image('library/images/<file>', ...)`  "
         f"(corpus totals by category: {dict(counts)})",
         f"* **{len(snippets)} snippets** (components = groups reused or named in your files) — `d.snippet(name, x, y)`",
         f"* **{len(gallery)} source figures** in `gallery/` — references to imitate", "",
         "Search from the shell: `python -m ogkit.library search <words>`", "",
         "## Icons", "", "![icons](icons/icons.png)", "",
         "| name | uses | aspect | example files |", "|---|---|---|---|"]
    for k, v in list(icons.items()):
        L.append(f"| `{k}` | {v['uses']} | {v['aspect']} | {', '.join(v['files'][:3])} |")
    L += ["", "## Images", ""]
    for cat in sorted({v["category"] for v in images.values()}):
        L.append(f"### {cat}\n\n![{cat}](images/_sheet_{cat.strip('_')}.jpg)\n")
        L.append("| key | file | uses | display size (pt) |")
        L.append("|---|---|---|---|")
        for k, v in images.items():
            if v["category"] == cat:
                L.append(f"| `{k}` | `images/{v['file']}` | {v['uses']} | {v['display_size'][0]}×{v['display_size'][1]} |")
        L.append("")
    L += ["## Snippets", "", "| preview | name | size (pt) | texts | used in |", "|---|---|---|---|---|"]
    for k, v in snippets.items():
        t = "; ".join(v["texts"][:4]).replace("|", "/").replace("\n", " ")[:70]
        L.append(f"| ![](snippets/{k}.png) | `{k}` | {v['size'][0]:.0f}×{v['size'][1]:.0f} | {t} | "
                 f"{len(v['files'])} file(s) ×{v['count']} |")
    L += ["", "## Gallery (source figures)", "", "| preview | figure | kind | modified | fonts |", "|---|---|---|---|---|"]
    for k, v in sorted(gallery.items(), key=lambda kv: kv[1]["modified"], reverse=True):
        L.append(f"| ![](gallery/{v['thumb']}) | {k} | {v['kind']} | {v['modified']} | {', '.join(v['fonts'])} |")
    open(os.path.join(lib, "CATALOG.md"), "w").write("\n".join(L) + "\n")


def build(corpus: str, lib: str = LIB):
    os.makedirs(lib, exist_ok=True)
    icons = build_icons(corpus, os.path.join(lib, "icons"))
    print(f"icons: {len(icons)}")
    images, counts = build_images(corpus, os.path.join(lib, "images"))
    print(f"images kept: {len(images)}  (all unique by category: {dict(counts)})")
    snippets = build_snippets(corpus, os.path.join(lib, "snippets"))
    print(f"snippets: {len(snippets)}")
    gallery = build_gallery(corpus, os.path.join(lib, "gallery"))
    print(f"gallery: {len(gallery)}")
    write_catalog(lib, icons, images, snippets, gallery, counts)


# ===========================================================================
# runtime
# ===========================================================================
_icons_cache = None


def icons() -> dict:
    global _icons_cache
    if _icons_cache is None:
        _icons_cache = json.load(open(os.path.join(LIB, "icons", "icons.json")))
    return _icons_cache


def icon_def(name: str) -> dict:
    ic = icons()
    key = slug(name)
    if key not in ic:
        cands = [k for k in ic if key in k]
        if not cands:
            raise KeyError(f"icon {name!r} not found; try: python -m ogkit.library search {name}")
        key = cands[0]
    d = copy.deepcopy(ic[key]["def"])
    d["aspect"] = ic[key].get("aspect", 1.0)
    out = {k: v for k, v in d.items() if k != "aspect"}
    out["aspect"] = d["aspect"]
    return out


def _scale(g, k):
    """Scale geometry, text sizes and stroke widths of a graphic tree about the origin."""
    for c, _, _ in gio.iter_graphics([g]):
        if "Bounds" in c:
            x, y, w, h = gio.parse_rect(c["Bounds"])
            c["Bounds"] = gio.fmt_rect(x * k, y * k, w * k, h * k)
        if "Points" in c:
            c["Points"] = [gio.fmt_point(*(lambda p: (p[0] * k, p[1] * k))(gio.parse_point(p))) for p in c["Points"]]
        for e in c.get("LogicalPath", {}).get("elements", []):
            for kk in ("point", "control1", "control2"):
                if kk in e:
                    px, py = gio.parse_point(e[kk])
                    e[kk] = gio.fmt_point(px * k, py * k)
        if "ControlPoints" in c:
            c["ControlPoints"] = [gio.fmt_point(*(lambda p: (p[0] * k, p[1] * k))(gio.parse_point(p)))
                                  for p in c["ControlPoints"]]
        st = c.get("Style", {}).get("stroke", {})
        if "Width" in st or c.get("Class") in ("ShapedGraphic", "LineGraphic"):
            st["Width"] = round(max(0.25, float(st.get("Width", 1)) * max(k, 0.5)), 3) if k < 1 else float(st.get("Width", 1)) * k
        if "CornerRadius" in st:
            st["CornerRadius"] = float(st["CornerRadius"]) * k
        t = c.get("Text", {})
        if t.get("Text"):
            rt = rtf.parse(t["Text"])
            for p in rt.paragraphs:
                for r in p.runs:
                    r.size = round(r.size * k * 2) / 2
            t["Text"] = rtf.build(rt.paragraphs)
            for kk in ("Pad", "VerticalPad"):
                if kk in t:
                    t[kk] = float(t[kk]) * k
        if "FontInfo" in c and "Size" in c["FontInfo"]:
            c["FontInfo"]["Size"] = round(float(c["FontInfo"]["Size"]) * k * 2) / 2


def load_snippet(diagram, name: str, x: float, y: float, recolor=None, texts=None, scale=1.0, width=None):
    """Insert snippet graphics into ``diagram`` with fresh IDs; returns a group-like Node."""
    import base64
    from .diagram import Node
    path = os.path.join(LIB, "snippets", f"{slug(name)}.json")
    if not os.path.exists(path):
        raise KeyError(f"snippet {name!r} not found; try: python -m ogkit.library search {name}")
    snip = json.load(open(path))
    graphics = copy.deepcopy(snip["graphics"])
    if width:
        scale = width / max(snip["size"][0], 1)
    if scale != 1.0:
        _scale(graphics[0], scale)
    _translate(graphics[0], x, y)
    # images
    idmap_img = {}
    for iid, a in snip.get("assets", {}).items():
        idmap_img[int(iid)] = diagram._register_image(base64.b64decode(a["data"]), a["ext"])
    for es in snip.get("export_shapes", []):
        diagram.export_shapes.setdefault(es["ShapeName"], es)
    # fresh IDs + reference remap
    idmap = {}
    for c, _, _ in gio.iter_graphics(graphics):
        if "ID" in c:
            idmap[c["ID"]] = diagram._id()
    nodes = []
    for c, _, _ in gio.iter_graphics(graphics):
        if "ID" in c:
            c["ID"] = idmap[c["ID"]]
        for end in ("Head", "Tail"):
            if end in c:
                if c[end].get("ID") in idmap:
                    c[end]["ID"] = idmap[c[end]["ID"]]
                else:
                    del c[end]
        if "Line" in c and c["Line"].get("ID") in idmap:
            c["Line"]["ID"] = idmap[c["Line"]["ID"]]
        if c.get("ImageID") in idmap_img:
            c["ImageID"] = idmap_img[c["ImageID"]]
        if c.get("Layer") is not None:
            c.pop("Layer")
        t = c.get("Text", {}).get("Text")
        if t and texts:
            rt = rtf.parse(t)
            if rt.plain.strip() in texts:
                newtxt = texts[rt.plain.strip()]
                r0 = next(rt.runs())
                c["Text"]["Text"] = rtf.from_runs([rtf.Run(newtxt, r0.font, r0.size, r0.color, r0.bold, r0.italic)],
                                                  rt.paragraphs[0].align)
        if recolor:
            for sec in ("fill", "stroke"):
                col = c.get("Style", {}).get(sec, {}).get("Color")
                if isinstance(col, dict) and "r" in col:
                    hx = to_hex((float(col["r"]), float(col["g"]), float(col["b"])))
                    if hx in recolor:
                        from .colors import og_color
                        c["Style"][sec]["Color"] = og_color(recolor[hx], float(col.get("a", 1)))
    top = graphics[0]
    diagram._add(top, "node")
    n = Node(diagram, None, "snippet")
    # wrap leaf graphics as members so the snippet can be moved as a whole
    for c, _, _ in gio.iter_graphics([top]):
        if c.get("Class") != "Group" and ("Bounds" in c or "Points" in c):
            m = Node(diagram, c, "part")
            n.members.append(m) if "Bounds" in c else n.meta.setdefault("lines", []).append(c)
    n.meta["graphic"] = top
    _patch_snippet_move(n)
    return n


def _patch_snippet_move(n):
    orig = n.move

    def move(dx, dy):
        orig(dx, dy)
        for c in n.meta.get("lines", []):
            _translate(c, dx, dy)
        return n
    n.move = move


def search(words: str, limit: int = 30):
    """Rank icons / images / snippets / figures by how many query words match (prefix-aware)."""
    q = [w.lower() for w in words.split() if w.strip()]
    tags = {}
    cp = os.path.join(LIB, "curation.yaml")
    if os.path.exists(cp):
        import yaml
        tags = (yaml.safe_load(open(cp)) or {}).get("icon_tags") or {}

    syn = {"evolution": "evo evolve reevo", "evolutionary": "evo evolve", "routing": "route vrp",
           "vehicle": "vrp car truck", "llm": "language gpt agent", "agent": "agents llm", "transformer": "attention",
           "attention": "transformer mha", "graph": "gnn hypergraph", "robot": "navigation crowd",
           "navigation": "nav robot", "poster": "kaist", "time": "timeseries temporal", "series": "timeseries"}

    def score(hay: str) -> int:
        hay_l = hay.lower()
        toks = set(re.findall(r"[a-z0-9]+", hay_l))
        sc = 0
        for w in q:
            alts = [w] + syn.get(w, "").split()
            if any(a in hay_l for a in alts) or any(
                    len(t) >= 3 and (t.startswith(w) or w.startswith(t) or os.path.commonprefix([t, w]).__len__() >= 4)
                    for t in toks):
                sc += 1
        return sc

    res = []
    for k, v in icons().items():
        res.append((score(f"{k} {v['name']} {tags.get(k, '')}"), "icon", k, f"uses={v['uses']}"))
    ip = os.path.join(LIB, "images", "images.json")
    if os.path.exists(ip):
        for k, v in json.load(open(ip)).items():
            res.append((score(f"{k} {v['name']} {v['category']} {' '.join(v['files'])}"), "image", k,
                        f"library/images/{v['file']}  {v['display_size']}pt uses={v['uses']}"))
    sp = os.path.join(LIB, "snippets", "index.json")
    if os.path.exists(sp):
        for k, v in json.load(open(sp)).items():
            res.append((score(f"{k} {v['title']} {' '.join(v['texts'])} {' '.join(v['files'])}"), "snippet", k,
                        f"{v['size'][0]:.0f}x{v['size'][1]:.0f}pt  {'; '.join(v['texts'][:3])[:60]}"))
    gp = os.path.join(LIB, "gallery", "gallery.json")
    if os.path.exists(gp):
        for k, v in json.load(open(gp)).items():
            res.append((score(f"{k} {v['kind']}"), "figure", k, f"{v['kind']} {v['modified']} {v['file']}"))
    res = [r for r in res if r[0] > 0]
    res.sort(key=lambda r: -r[0])
    return [(kind, k, info + (f"  [{sc}/{len(q)} words]" if len(q) > 1 else "")) for sc, kind, k, info in res[:limit]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("corpus")
    b.add_argument("--out", default=LIB)
    s = sub.add_parser("search")
    s.add_argument("words", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.corpus, a.out)
    else:
        res = search(" ".join(a.words))
        if not res:
            print("no results — try fewer/shorter words, or browse library/CATALOG.md")
        for kind, k, info in res:
            print(f"{kind:8s} {k:40s} {info}")


if __name__ == "__main__":
    main()
