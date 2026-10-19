"""Structural validation of a .graffle against what real OmniGraffle 7 files contain.

Checks: plist loads; required document/sheet keys; unique graphic IDs; Head/Tail/Line
references resolve; ImageID references exist in ImageList + assets; every key used per
graphic class (and per style section) was observed in the reference corpus; geometry
strings parse; RTF parses.

    python -m ogkit.validate out/figure.graffle
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import gio, rtf

_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "schema.json")

REQUIRED_DOC = ["GraphDocumentVersion", "ApplicationVersion", "Sheets"]
REQUIRED_SHEET = ["GraphicsList", "Layers", "SheetTitle", "UniqueID", "CanvasSize", "BackgroundGraphic"]


def build_schema(corpus_dir: str) -> dict:
    """Collect observed keys per class from a folder of real .graffle files."""
    keys: dict[str, set] = {}
    style: dict[str, set] = {}
    doc_keys, sheet_keys = set(), set()
    for f in sorted(os.listdir(corpus_dir)):
        if not f.endswith(".graffle"):
            continue
        gf = gio.load(os.path.join(corpus_dir, f))
        doc_keys |= set(gf.doc)
        for s in gf.sheets:
            sheet_keys |= set(s)
            for g, _, _ in gio.iter_graphics(s.get("GraphicsList", [])):
                keys.setdefault(g.get("Class", "?"), set()).update(g)
                for sec, d in g.get("Style", {}).items():
                    if isinstance(d, dict):
                        style.setdefault(sec, set()).update(d)
    return {"doc": sorted(doc_keys), "sheet": sorted(sheet_keys),
            "graphic": {k: sorted(v) for k, v in keys.items()},
            "style": {k: sorted(v) for k, v in style.items()}}


def validate(gf: gio.GraffleFile, schema: dict | None = None) -> list[str]:
    if schema is None and os.path.exists(_SCHEMA):
        schema = json.load(open(_SCHEMA))
    errs: list[str] = []
    doc = gf.doc
    for k in REQUIRED_DOC:
        if k not in doc:
            errs.append(f"doc: missing {k}")
    if schema:
        for k in doc:
            if k not in schema["doc"]:
                errs.append(f"doc: unknown key {k}")
    images = set(doc.get("ImageList", []))
    for n in images:
        if n not in gf.assets:
            errs.append(f"ImageList entry {n} has no asset")
    for si, s in enumerate(gf.sheets):
        for k in REQUIRED_SHEET:
            if k not in s:
                errs.append(f"sheet {si}: missing {k}")
        if schema:
            for k in s:
                if k not in schema["sheet"]:
                    errs.append(f"sheet {si}: unknown key {k}")
        ids = {}
        allg = list(gio.iter_graphics(s.get("GraphicsList", [])))
        for g, _, _ in allg:
            gid = g.get("ID")
            if gid is None:
                errs.append(f"sheet {si}: graphic without ID ({g.get('Class')})")
            elif gid in ids:
                errs.append(f"sheet {si}: duplicate ID {gid}")
            ids[gid] = g
        if s.get("BackgroundGraphic", {}).get("ID") in ids:
            errs.append(f"sheet {si}: BackgroundGraphic ID collides")
        shapes = {e.get("ShapeName") for e in s.get("ExportShapes", [])}
        for g, _, _ in allg:
            cls = g.get("Class")
            gid = g.get("ID")
            if schema:
                known = set(schema["graphic"].get(cls, []))
                if not known:
                    errs.append(f"#{gid}: unknown class {cls}")
                for k in g:
                    if known and k not in known:
                        errs.append(f"#{gid} {cls}: key {k} never seen in corpus")
                for sec, d in g.get("Style", {}).items():
                    sk = set(schema["style"].get(sec, []))
                    if not sk:
                        errs.append(f"#{gid}: unknown style section {sec}")
                    elif isinstance(d, dict):
                        for k in d:
                            if k not in sk:
                                errs.append(f"#{gid}: style.{sec}.{k} never seen in corpus")
            try:
                if "Bounds" in g:
                    gio.parse_rect(g["Bounds"])
                for p in g.get("Points", []):
                    gio.parse_point(p)
            except Exception as e:  # noqa
                errs.append(f"#{gid}: bad geometry {e}")
            for end in ("Head", "Tail"):
                ref = g.get(end, {}).get("ID")
                if ref is not None and ref not in ids:
                    errs.append(f"#{gid}: {end} -> missing #{ref}")
            if "Line" in g and g["Line"].get("ID") not in ids:
                errs.append(f"#{gid}: label Line -> missing #{g['Line'].get('ID')}")
            if g.get("ImageID") is not None and gf.image_name(g["ImageID"]) not in images:
                errs.append(f"#{gid}: ImageID {g['ImageID']} not in ImageList")
            sh = g.get("Shape")
            if sh and str(sh).startswith("pdfImport") and sh not in shapes:
                errs.append(f"#{gid}: custom shape {sh} has no ExportShapes definition")
            t = g.get("Text", {}).get("Text")
            if t:
                try:
                    rtf.parse(t)
                except Exception as e:  # noqa
                    errs.append(f"#{gid}: RTF parse error {e}")
            if cls == "LineGraphic" and len(g.get("Points", [])) < 2:
                errs.append(f"#{gid}: line with <2 points")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--build-schema", metavar="CORPUS_DIR")
    a = ap.parse_args(argv)
    if a.build_schema:
        sc = build_schema(a.build_schema)
        json.dump(sc, open(_SCHEMA, "w"), indent=1)
        print(f"schema written to {_SCHEMA}")
    bad = 0
    for f in a.files:
        errs = validate(gio.load(f))
        print(f"{'OK ' if not errs else 'ERR'} {f}" + ("" if not errs else f" ({len(errs)} issues)"))
        for e in errs[:40]:
            print("   -", e)
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
