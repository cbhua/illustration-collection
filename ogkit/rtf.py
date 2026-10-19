"""Minimal Cocoa-RTF reader / writer for OmniGraffle text.

OmniGraffle stores every label as a Cocoa RTF string in ``graphic["Text"]["Text"]``.
The reader turns it into paragraphs of styled runs; the writer produces RTF that is
byte-for-byte in the same dialect OmniGraffle 7 writes (``\\cocoartf`` header,
``expandedcolortbl`` with ``\\cssrgb`` values, ``\\uc0\\uNNNN`` unicode escapes).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from .colors import p3_to_srgb, to_hex, hex_to_rgb

ALIGN_CODES = {"ql": "left", "qc": "center", "qr": "right", "qj": "justify"}
CHARSET_CODEC = {0: "cp1252", 77: "mac_roman", 128: "shift_jis", 129: "cp949", 134: "gbk", 136: "big5",
                 161: "cp1253", 162: "cp1254", 204: "cp1251", 238: "cp1250"}


@dataclass
class Run:
    text: str
    font: str = "Helvetica"
    size: float = 12.0
    color: str = "#000000"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    baseline: str = ""  # "super" | "sub" | ""
    background: str | None = None
    kern: float = 0.0  # extra letter spacing (pt)


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)
    align: str = "left"

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class RichText:
    paragraphs: list[Paragraph]

    @property
    def plain(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    def runs(self):
        for p in self.paragraphs:
            yield from p.runs


# --------------------------------------------------------------------------
# reader
# --------------------------------------------------------------------------
_TOKEN = re.compile(
    r"(\\[a-zA-Z]+-?\d* ?)|(\\'[0-9a-fA-F]{2})|(\\[^a-zA-Z])|([{}])|([^\\{}\r\n]+)|([\r\n]+)"
)


def _tokens(src: str):
    for m in _TOKEN.finditer(src):
        cw, hx, sym, br, txt, nl = m.groups()
        if cw:
            mm = re.match(r"\\([a-zA-Z]+)(-?\d+)?", cw)
            yield ("cw", mm.group(1), int(mm.group(2)) if mm.group(2) is not None else None)
        elif hx:
            yield ("hex", int(hx[2:], 16), None)
        elif sym:
            yield ("sym", sym[1], None)
        elif br:
            yield (br, None, None)
        elif txt:
            yield ("text", txt, None)
        # bare newlines are ignored by RTF


def _cs_color(words: list[tuple[str, int | None]]) -> str | None:
    """Decode an expandedcolortbl entry such as \\cssrgb\\c100\\c50\\c0."""
    if not words:
        return None
    kind = words[0][0]
    vals = [v / 100000 for w, v in words[1:] if w == "c" and v is not None]
    if kind in ("cssrgb", "csgenericrgb") and len(vals) >= 3:
        return to_hex(vals[:3])
    if kind == "cspthree" and len(vals) >= 3:
        return to_hex(p3_to_srgb(*vals[:3]))
    if kind in ("csgray", "csgenericgray") and vals:
        return to_hex((vals[0],) * 3)
    return None


def parse(src: str | None, default_font="Helvetica", default_size=12.0) -> RichText:
    if not src:
        return RichText([])
    if not src.lstrip().startswith("{\\rtf"):
        return RichText([Paragraph([Run(src, default_font, default_size)], "center")])

    fonts: dict[int, str] = {}
    charsets: dict[int, int] = {}
    hexbuf = bytearray()
    colors: list[str | None] = []
    xcolors: list[str | None] = []

    base = {"f": 0, "fs": default_size * 2, "cf": 0, "cb": None, "b": False, "i": False,
            "ul": False, "strike": False, "base": "", "expnd": 0.0, "uc": 1}
    stack: list[dict] = []
    st = dict(base)
    dest_stack: list[str | None] = []
    dest: str | None = None
    align = "left"
    paragraphs: list[Paragraph] = [Paragraph(align=align)]
    skip_chars = 0

    # destination-local buffers
    font_idx = None
    font_name_buf = ""
    color_buf: dict[str, int] = {}
    xcolor_buf: list[tuple[str, int | None]] = []
    pending_surrogate = None

    def emit(text: str):
        nonlocal pending_surrogate
        if not text:
            return
        p = paragraphs[-1]
        p.align = align
        run = Run(
            text,
            fonts.get(st["f"], default_font),
            st["fs"] / 2,
            _color_at(st["cf"]),
            st["b"], st["i"], st["ul"], st["strike"], st["base"],
            _color_at(st["cb"]) if st["cb"] else None,
            st["expnd"],
        )
        if p.runs and _same_style(p.runs[-1], run):
            p.runs[-1].text += text
        else:
            p.runs.append(run)

    def _color_at(i):
        if i is None or i <= 0:
            return "#000000"
        if i < len(xcolors) and xcolors[i]:
            return xcolors[i]  # type: ignore[return-value]
        if i < len(colors) and colors[i]:
            return colors[i]  # type: ignore[return-value]
        return "#000000"

    def new_paragraph():
        paragraphs.append(Paragraph(align=align))

    toks = list(_tokens(src))
    i = 0
    first_in_group = False
    while i < len(toks):
        kind, val, param = toks[i]
        i += 1
        if hexbuf and kind != "hex":
            codec = CHARSET_CODEC.get(charsets.get(st["f"], 0), "cp1252")
            emit(bytes(hexbuf).decode(codec, "replace"))
            hexbuf.clear()
        if kind == "{":
            stack.append(dict(st))
            dest_stack.append(dest)
            first_in_group = True
            continue
        if kind == "}":
            if dest == "fonttbl" and font_idx is not None and font_name_buf.strip():
                fonts[font_idx] = font_name_buf.strip().rstrip(";")
            st = stack.pop() if stack else dict(base)
            dest = dest_stack.pop() if dest_stack else None
            first_in_group = False
            continue
        was_first = first_in_group
        first_in_group = False

        if dest == "skip":
            continue
        if kind == "sym" and val == "*":
            dest = "star"
            continue
        if kind == "cw":
            w = val
            if dest == "star":
                dest = "expandedcolortbl" if w == "expandedcolortbl" else "skip"
                if dest == "expandedcolortbl":
                    xcolors = []
                    xcolor_buf = []
                continue
            if was_first and w in ("fonttbl", "colortbl", "stylesheet", "info", "pict", "listtable",
                                   "listoverridetable"):
                dest = w if w in ("fonttbl", "colortbl") else "skip"
                if w == "colortbl":
                    colors = []
                    color_buf = {}
                font_idx = None
                font_name_buf = ""
                continue
            if dest == "fonttbl":
                if w == "fcharset" and font_idx is not None:
                    charsets[font_idx] = param or 0
                if w == "f":
                    if font_idx is not None and font_name_buf.strip():
                        fonts[font_idx] = font_name_buf.strip().rstrip(";")
                    font_idx, font_name_buf = param, ""
                continue
            if dest == "colortbl":
                if w in ("red", "green", "blue"):
                    color_buf[w] = param or 0
                continue
            if dest == "expandedcolortbl":
                xcolor_buf.append((w, param))
                continue
            # --- body control words -------------------------------------
            if w == "f":
                st["f"] = param or 0
            elif w == "fs":
                st["fs"] = param or 24
            elif w == "cf":
                st["cf"] = param or 0
            elif w == "cb":
                st["cb"] = param or None
            elif w == "b":
                st["b"] = param != 0
            elif w == "i":
                st["i"] = param != 0
            elif w == "ul":
                st["ul"] = param != 0
            elif w == "ulnone":
                st["ul"] = False
            elif w == "strike":
                st["strike"] = param != 0
            elif w == "super":
                st["base"] = "super"
            elif w == "sub":
                st["base"] = "sub"
            elif w == "nosupersub":
                st["base"] = ""
            elif w == "up":
                st["base"] = "super" if (param or 0) > 0 else ""
            elif w == "dn":
                st["base"] = "sub" if (param or 0) > 0 else ""
            elif w == "expnd":
                st["expnd"] = (param or 0) / 4  # quarter points
            elif w == "plain":
                st.update(b=False, i=False, ul=False, strike=False, base="")
            elif w in ALIGN_CODES:
                align = ALIGN_CODES[w]
                paragraphs[-1].align = align
            elif w == "pard":
                align = "left"
                paragraphs[-1].align = align
            elif w in ("par",):
                new_paragraph()
            elif w == "line":
                emit("\n")
            elif w == "tab":
                emit("\t")
            elif w == "uc":
                st["uc"] = param or 0
            elif w == "u":
                cp = param or 0
                if cp < 0:
                    cp += 65536
                if 0xD800 <= cp <= 0xDBFF:
                    pending_surrogate = cp
                elif 0xDC00 <= cp <= 0xDFFF and pending_surrogate:
                    emit(chr(0x10000 + ((pending_surrogate - 0xD800) << 10) + (cp - 0xDC00)))
                    pending_surrogate = None
                else:
                    emit(chr(cp))
                skip_chars = st["uc"]
            elif w in ("emdash",):
                emit("\u2014")
            elif w in ("endash",):
                emit("\u2013")
            elif w in ("bullet",):
                emit("\u2022")
            continue
        if kind == "sym":
            if dest in ("fonttbl", "colortbl", "expandedcolortbl"):
                continue
            if val == "\n" or val == "\r":
                new_paragraph()
            elif val in "\\{}":
                emit(val)
            elif val == "~":
                emit("\u00a0")
            elif val == "-":
                pass
            elif val == "_":
                emit("\u2011")
            continue
        if kind == "hex":
            if skip_chars:
                skip_chars -= 1
                continue
            if dest == "fonttbl":
                font_name_buf += bytes([val]).decode("cp1252", "replace")
                continue
            hexbuf.append(val)
            continue
        if kind == "text":
            if dest == "fonttbl":
                for ch in val:
                    if ch == ";":
                        if font_idx is not None and font_name_buf.strip():
                            fonts[font_idx] = font_name_buf.strip()
                        font_name_buf = ""
                        font_idx = None
                    else:
                        font_name_buf += ch
                continue
            if dest == "colortbl":
                for _ in range(val.count(";")):
                    if color_buf:
                        colors.append(to_hex([color_buf.get(k, 0) / 255 for k in ("red", "green", "blue")]))
                    else:
                        colors.append(None)
                    color_buf = {}
                continue
            if dest == "expandedcolortbl":
                for _ in range(val.count(";")):
                    xcolors.append(_cs_color(xcolor_buf))
                    xcolor_buf = []
                continue
            if dest is not None:
                continue
            if skip_chars:
                n = min(skip_chars, len(val))
                val = val[n:]
                skip_chars -= n
            emit(val)

    # Drop empty trailing paragraph created by a final "\\\n"
    while len(paragraphs) > 1 and not paragraphs[-1].runs:
        paragraphs.pop()
    return RichText(paragraphs)


def _same_style(a: Run, b: Run) -> bool:
    return (a.font, a.size, a.color, a.bold, a.italic, a.underline, a.strike, a.baseline,
            a.background, a.kern) == (b.font, b.size, b.color, b.bold, b.italic, b.underline,
                                      b.strike, b.baseline, b.background, b.kern)


# --------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------
_ALIGN_TO_CODE = {"left": "", "center": "\\qc", "right": "\\qr", "justify": "\\qj"}


def _esc(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\n":
            out.append("\\\n")
        elif ch == "\t":
            out.append("\t")
        elif o < 128:
            out.append(ch)
        elif o < 0x10000:
            out.append("\\uc0\\u%d " % o)
        else:
            o -= 0x10000
            out.append("\\uc0\\u%d \\u%d " % (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)))
    return "".join(out)


def build(paragraphs: list[Paragraph]) -> str:
    """Serialise paragraphs to OmniGraffle-flavoured Cocoa RTF."""
    fonts: list[str] = []
    colors: list[str] = ["#FFFFFF"]  # Cocoa always emits white as colour #1
    for p in paragraphs:
        for r in p.runs:
            if r.font not in fonts:
                fonts.append(r.font)
            for c in (r.color, r.background):
                if c and c.upper() not in colors:
                    colors.append(c.upper())
    if not fonts:
        fonts = ["Helvetica"]

    head = ["{\\rtf1\\ansi\\ansicpg1252\\cocoartf2870\n",
            "\\cocoatextscaling0\\cocoaplatform0{\\fonttbl",
            "".join("\\f%d\\fnil\\fcharset0 %s;" % (i, f) for i, f in enumerate(fonts)), "}\n"]
    ct = "{\\colortbl;" + "".join(
        "\\red%d\\green%d\\blue%d;" % tuple(int(round(v * 255)) for v in hex_to_rgb(c)) for c in colors) + "}\n"
    # entry 0 is the "auto" colour, white (#1) is left empty exactly like Cocoa does
    xentries = ["" if c == "#FFFFFF" else "\\cssrgb\\c%d\\c%d\\c%d" % tuple(
        int(round(v * 100000)) for v in hex_to_rgb(c)) for c in colors]
    xct = "{\\*\\expandedcolortbl;" + "".join(e + ";" for e in xentries) + "}\n"
    body = ["\\deftab720\n"]
    prev = None
    cur: dict = {}  # character state carries over paragraph breaks
    for pi, p in enumerate(paragraphs):
        if p.align != (prev.align if prev else None):
            body.append("\\pard\\pardeftab720%s\\partightenfactor0\n\n" % _ALIGN_TO_CODE.get(p.align, ""))
        for r in p.runs:
            codes = []
            fi = fonts.index(r.font)
            if cur.get("f") != fi:
                codes.append("\\f%d" % fi)
            if cur.get("b", False) != r.bold:
                codes.append("\\b" if r.bold else "\\b0")
            if cur.get("i", False) != r.italic:
                codes.append("\\i" if r.italic else "\\i0")
            fs = int(round(r.size * 2))
            if cur.get("fs") != fs:
                codes.append("\\fs%d" % fs)
            if cur.get("cf") != r.color.upper():
                codes.append("\\cf%d" % (colors.index(r.color.upper()) + 1))
            bg = r.background.upper() if r.background else None
            if cur.get("cb") != bg:
                codes.append("\\cb%d" % (colors.index(bg) + 1) if bg else "\\cb1")
            if cur.get("ul", False) != r.underline:
                codes.append("\\ul\\ulc0" if r.underline else "\\ulnone")
            if cur.get("strike", False) != r.strike:
                codes.append("\\strike\\strikec0" if r.strike else "\\strike0\\striked0")
            if cur.get("base", "") != r.baseline:
                codes.append({"super": "\\super", "sub": "\\sub", "": "\\nosupersub"}[r.baseline])
            if cur.get("kern", 0) != r.kern:
                codes.append("\\expnd%d\\expndtw%d\\kerning0" % (int(r.kern * 4), int(r.kern * 20)))
            cur = {"f": fi, "b": r.bold, "i": r.italic, "fs": fs, "cf": r.color.upper(), "cb": bg,
                   "ul": r.underline, "strike": r.strike, "base": r.baseline, "kern": r.kern}
            body.append(("".join(codes) + " " if codes else "") + _esc(r.text))
        if pi < len(paragraphs) - 1:
            body.append("\\\n")
        prev = p
    return "".join(head) + ct + xct + "".join(body) + "}"


def simple(text: str, font: str, size: float, color: str = "#000000", align: str = "center",
           bold: bool = False, italic: bool = False) -> str:
    """One-style text; ``\\n`` separates paragraphs."""
    paras = [Paragraph([Run(line, font, size, color, bold, italic)] if line else [], align)
             for line in text.split("\n")]
    for p in paras:  # keep empty lines sized
        if not p.runs:
            p.runs.append(Run("", font, size, color))
    return build(paras)


def from_runs(runs: list[Run], align: str = "center") -> str:
    """Build from runs; a run containing ``\\n`` breaks into new paragraphs."""
    paras = [Paragraph([], align)]
    for r in runs:
        parts = r.text.split("\n")
        for k, part in enumerate(parts):
            if k:
                paras.append(Paragraph([], align))
            if part:
                paras[-1].runs.append(replace(r, text=part))
    for p in paras:
        if not p.runs:
            p.runs.append(replace(runs[0], text=""))
    return build(paras)
