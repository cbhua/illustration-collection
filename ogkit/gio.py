"""Read / write OmniGraffle 7 documents (.graffle).

OmniGraffle 7 stores a document in one of three containers:

* ``zip``      – a single zip file holding ``data.plist`` (binary plist),
                 ``preview.jpeg`` and ``image<N>.<ext>`` assets.  This is the
                 default "flat file" format and what every file in the corpus uses.
* ``package``  – a directory bundle with the same members.
* ``flat``     – a bare (optionally gzip-compressed) XML/binary plist; legacy
                 OmniGraffle 5/6 format, still readable by OmniGraffle 7.

``load`` normalises all of them into a :class:`GraffleFile`; ``save`` always
writes the zip form, exactly mirroring what OmniGraffle 7 itself produces.
"""
from __future__ import annotations

import gzip
import io
import os
import plistlib
import zipfile
from dataclasses import dataclass, field


@dataclass
class GraffleFile:
    doc: dict
    assets: dict[str, bytes] = field(default_factory=dict)  # "image1.pdf" -> bytes
    preview: bytes | None = None
    container: str = "zip"
    path: str | None = None

    # -- convenience -------------------------------------------------------
    @property
    def sheets(self) -> list[dict]:
        return self.doc.get("Sheets", [])

    def image_name(self, image_id: int) -> str | None:
        """Map a ShapedGraphic ``ImageID`` to its asset file name."""
        lst = self.doc.get("ImageList", [])
        # ImageList is ordered newest-first; asset names carry the id.
        for name in lst:
            stem = os.path.splitext(name)[0]
            if stem == f"image{image_id}":
                return name
        return None

    def image_bytes(self, image_id: int) -> bytes | None:
        n = self.image_name(image_id)
        return self.assets.get(n) if n else None


def load(path: str) -> GraffleFile:
    if os.path.isdir(path):
        doc = _load_plist(open(os.path.join(path, "data.plist"), "rb").read())
        assets, preview = {}, None
        for n in os.listdir(path):
            p = os.path.join(path, n)
            if n == "data.plist" or not os.path.isfile(p):
                continue
            if n == "preview.jpeg":
                preview = open(p, "rb").read()
            else:
                assets[n] = open(p, "rb").read()
        return GraffleFile(doc, assets, preview, "package", path)

    raw = open(path, "rb").read()
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            doc = _load_plist(z.read("data.plist"))
            assets, preview = {}, None
            for n in z.namelist():
                if n == "data.plist" or n.endswith("/"):
                    continue
                if n == "preview.jpeg":
                    preview = z.read(n)
                else:
                    assets[os.path.basename(n)] = z.read(n)
        return GraffleFile(doc, assets, preview, "zip", path)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return GraffleFile(_load_plist(raw), {}, None, "flat", path)


def _load_plist(raw: bytes) -> dict:
    return plistlib.loads(raw)


def dumps_plist(doc: dict, binary: bool = True) -> bytes:
    fmt = plistlib.FMT_BINARY if binary else plistlib.FMT_XML
    return plistlib.dumps(doc, fmt=fmt, sort_keys=False)


def save(gf: GraffleFile, path: str, binary: bool = True) -> str:
    """Write ``gf`` as an OmniGraffle 7 zip-format .graffle file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(gf.assets.items()):
            z.writestr(name, data)
        z.writestr("data.plist", dumps_plist(gf.doc, binary))
        if gf.preview:
            z.writestr(_zinfo("preview.jpeg"), gf.preview)
    os.replace(tmp, path)
    return path


def _zinfo(name: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name)
    zi.compress_type = zipfile.ZIP_DEFLATED
    return zi


# -- graphic tree helpers ---------------------------------------------------

def iter_graphics(graphics: list[dict], depth: int = 0, parent: dict | None = None):
    """Yield ``(graphic, depth, parent)`` for every graphic, recursing into groups/tables."""
    for g in graphics:
        yield g, depth, parent
        if "Graphics" in g:
            yield from iter_graphics(g["Graphics"], depth + 1, g)


def max_id(graphics: list[dict]) -> int:
    m = 0
    for g, _, _ in iter_graphics(graphics):
        m = max(m, int(g.get("ID", 0)))
    return m


# -- geometry string helpers ("{{x, y}, {w, h}}") ----------------------------

def parse_point(s: str) -> tuple[float, float]:
    a, b = s.strip("{} ").split(",")
    return float(a), float(b)


def parse_rect(s: str) -> tuple[float, float, float, float]:
    nums = [float(t) for t in s.replace("{", " ").replace("}", " ").replace(",", " ").split()]
    return nums[0], nums[1], nums[2], nums[3]


def fmt_num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return repr(round(float(v), 6))


def fmt_point(x: float, y: float) -> str:
    return "{%s, %s}" % (fmt_num(x), fmt_num(y))


def fmt_rect(x: float, y: float, w: float, h: float) -> str:
    return "{{%s, %s}, {%s, %s}}" % (fmt_num(x), fmt_num(y), fmt_num(w), fmt_num(h))
