"""Build every Execs NOW HQ brand file from the approved sheet's geometry.

    .venv/bin/python scripts/brand/build_brand.py

Writes, under frontend/public/brand/ (served at /static/brand/):

- svg/  every piece in every colorway, text as paths, transparent;
- png/  each of those at 512 and 2048 px wide, on transparent and on the
        backgrounds it is meant for (docs/brand/README.md);
- the tab icons: favicon.ico (16, 32, 48), favicon-16/32/48.png,
  apple-touch-icon.png (180), icon-192.png, icon-512.png, site.webmanifest;

and docs/brand/contact-sheet.png, every one of those files on one page.

The sources are docs/brand/source/enhq-logo-standard.jpeg and
enhq-logo-reversed.jpeg (2026-11-05). Every number below was measured from
them, as a share of the square's side, and is noted where it is used. The
font is Montserrat ExtraBold (docs/brand/source/fonts, SIL OFL), shaped with
HarfBuzz so its kerning applies, and drawn as outlines: no SVG needs the font.

Needs skia-pathops and uharfbuzz (requirements-dev.txt), Pillow, Node and
Google Chrome (the PNGs are Chrome's renderings of the SVGs, so a PNG is
exactly what a browser shows for its SVG).
"""

from __future__ import annotations

import base64
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pathops
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "docs/brand/source/fonts/Montserrat-ExtraBold.ttf"
OUT = ROOT / "frontend/public/brand"
SHEET = ROOT / "docs/brand/contact-sheet.png"

BLUE, ORANGE, WHITE = "#0D2C54", "#E87722", "#FFFFFF"
NAME = "Execs NOW HQ"

#: The square's side, in drawing units. Everything is placed on this scale.
SIDE = 1000.0

# ---------------------------------------------------------------- the mark
#: The H and the O, together, span 78% of the square, centred (sheet: 0.113
#: to 0.894), with the sheet's space between them (0.105 of the cap height).
#: Montserrat is wider than the sheet's lettering, so at that width its caps
#: are 0.360 of the side where the sheet's were 0.391.
HO_WIDTH = 0.780
HO_GAP = 0.105            # of the cap height
#: The tail: a bar at 45 degrees, 0.284 of the side long and 0.079 thick,
#: square-ended, starting just below and right of the O's centre (sheet:
#: +0.0066, +0.0366) and leaving the bowl at the lower right.
TAIL_ANGLE = 45.0
TAIL_LENGTH = 0.284
TAIL_THICKNESS = 0.079
TAIL_START = (0.0066, 0.0366)

# ------------------------------------------------------- two-line lockup
#: Execs over NOW, each line the same width; the square at the right is the
#: two lines' height: Execs' cap line on its top, NOW's baseline on its
#: bottom, 0.094 of the side between the lines, 0.114 of it before the square.
STACK_LINE_GAP = 0.094
STACK_SQUARE_GAP = 0.114

# ------------------------------------------------------- one-line lockup
#: Execs NOW at the cap height of the square's HQ, on the same baseline; the
#: word space is the sheet's 0.435 of the cap height and the square sits
#: 0.13 of its side after NOW.
LINE_WORD_GAP = 0.435     # of the cap height
LINE_SQUARE_GAP = 0.130

#: Clear space on every side: half the square's width (owner, 2026-11-05).
CLEAR = 0.5

COLORWAYS = {
    # role -> fill; None knocks the shape out of the square.
    "standard": {"word1": BLUE, "word2": ORANGE, "square": BLUE, "letters": WHITE, "tail": ORANGE},
    "reversed": {"word1": WHITE, "word2": ORANGE, "square": WHITE, "letters": BLUE, "tail": ORANGE},
    "blue": {"word1": BLUE, "word2": BLUE, "square": BLUE, "letters": None, "tail": None},
    "white": {"word1": WHITE, "word2": WHITE, "square": WHITE, "letters": None, "tail": None},
}
#: The backgrounds each colorway is drawn for, besides transparent. A
#: colorway is never put where part of it would vanish (standard's dark blue
#: square on dark blue, the reversed white wordmark on white, an orange NOW
#: on orange).
BACKGROUNDS = {"white": WHITE, "blue": BLUE, "orange": ORANGE}
ON = {"standard": ["white"], "reversed": ["blue"], "blue": ["white"],
      "white": ["blue", "orange"]}
WIDTHS = (512, 2048)
ICONS = {"favicon-16.png": 16, "favicon-32.png": 32, "favicon-48.png": 48,
         "apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


# ------------------------------------------------------------------ font

class _ToSkia(BasePen):
    """fontTools outlines (TrueType quadratics included) into a pathops path."""

    def __init__(self, path, transform):
        super().__init__(None)
        self.pen, self.t = path.getPen(), transform

    def _p(self, pt):
        return self.t(*pt)

    def _moveTo(self, pt):
        self.pen.moveTo(self._p(pt))

    def _lineTo(self, pt):
        self.pen.lineTo(self._p(pt))

    def _curveToOne(self, a, b, c):
        self.pen.curveTo(self._p(a), self._p(b), self._p(c))

    def _qCurveToOne(self, a, b):
        self.pen.qCurveTo(self._p(a), self._p(b))

    def _closePath(self):
        self.pen.closePath()


class Font:
    def __init__(self, path: Path):
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        self.cap = self.tt["OS/2"].sCapHeight

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        x, out = 0, []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.tt.getGlyphName(info.codepoint), x + pos.x_offset))
            x += pos.x_advance
        return out

    def ink(self, text):
        """(left, right) of the ink, in font units, from the origin."""
        path = self.outline(text, 1.0, 0.0, 0.0)
        left, _, right, _ = path.bounds
        return left, right

    def outline(self, text, scale, x, baseline):
        """The text as one path: origin at x, baseline at `baseline`, y down."""
        path = pathops.Path()
        for name, gx in self.shape(text):
            ox = x + gx * scale
            self.glyphs[name].draw(_ToSkia(
                path, lambda px, py, ox=ox: (ox + px * scale, baseline - py * scale)))
        return pathops.simplify(path, fix_winding=True)


def union(*paths):
    out = pathops.Path()
    for p in paths:
        out.addPath(p)
    return pathops.simplify(out, fix_winding=True)


def minus(a, b):
    return pathops.op(a, b, pathops.PathOp.DIFFERENCE, fix_winding=True)


def rect(x, y, w, h):
    p = pathops.Path()
    p.moveTo(x, y); p.lineTo(x + w, y); p.lineTo(x + w, y + h); p.lineTo(x, y + h); p.close()
    return p


def bar(start, angle, length, thickness):
    a = math.radians(angle)
    u = (math.cos(a), math.sin(a))
    n = (-math.sin(a) * thickness / 2, math.cos(a) * thickness / 2)
    end = (start[0] + u[0] * length, start[1] + u[1] * length)
    p = pathops.Path()
    p.moveTo(start[0] + n[0], start[1] + n[1])
    p.lineTo(end[0] + n[0], end[1] + n[1])
    p.lineTo(end[0] - n[0], end[1] - n[1])
    p.lineTo(start[0] - n[0], start[1] - n[1])
    p.close()
    return p


# ---------------------------------------------------------------- pieces

def mark(font, x0=0.0, y0=0.0, side=SIDE):
    """{role: path} of the square mark with its top left at (x0, y0)."""
    h_left, h_right = font.ink("H")
    o_left, o_right = font.ink("O")
    # Width of H + gap + O, in font units at scale 1, the gap a share of the cap.
    span = (h_right - h_left) + HO_GAP * font.cap + (o_right - o_left)
    scale = HO_WIDTH * side / span
    cap = font.cap * scale
    left = x0 + (1 - HO_WIDTH) / 2 * side
    baseline = y0 + side / 2 + cap / 2
    h = font.outline("H", scale, left - h_left * scale, baseline)
    o_x = left + (h_right - h_left) * scale + HO_GAP * cap
    o = font.outline("O", scale, o_x - o_left * scale, baseline)
    ox0, oy0, ox1, oy1 = o.bounds
    centre = ((ox0 + ox1) / 2, (oy0 + oy1) / 2)
    start = (centre[0] + TAIL_START[0] * side, centre[1] + TAIL_START[1] * side)
    tail = bar(start, TAIL_ANGLE, TAIL_LENGTH * side, TAIL_THICKNESS * side)
    return {"square": rect(x0, y0, side, side), "letters": minus(union(h, o), tail),
            "tail": tail}, cap, baseline


def stacked(font):
    """Execs over NOW, the square at the right at the two lines' height."""
    e_left, e_right = font.ink("Execs")
    n_left, n_right = font.ink("NOW")
    # Both lines one width w: Execs' cap is w * cap / its ink width, NOW's
    # likewise, and the two caps and the gap make the square's side.
    per_w = font.cap / (e_right - e_left) + font.cap / (n_right - n_left)
    width = SIDE * (1 - STACK_LINE_GAP) / per_w
    e_scale = width / (e_right - e_left)
    n_scale = width / (n_right - n_left)
    execs = font.outline("Execs", e_scale, -e_left * e_scale, font.cap * e_scale)
    now = font.outline("NOW", n_scale, -n_left * n_scale, SIDE)
    pieces, _, _ = mark(font, x0=width + STACK_SQUARE_GAP * SIDE)
    return {"word1": execs, "word2": now, **pieces}


def one_line(font):
    """Execs NOW, the square after it, its HQ at the words' cap height."""
    _, cap, baseline = mark(font)
    scale = cap / font.cap
    e_left, e_right = font.ink("Execs")
    n_left, n_right = font.ink("NOW")
    execs = font.outline("Execs", scale, -e_left * scale, baseline)
    now_x = (e_right - e_left) * scale + LINE_WORD_GAP * cap
    now = font.outline("NOW", scale, now_x - n_left * scale, baseline)
    square_x = now_x + (n_right - n_left) * scale + LINE_SQUARE_GAP * SIDE
    pieces, _, _ = mark(font, x0=square_x)
    return {"word1": execs, "word2": now, **pieces}


PIECES = {"mark": lambda f: mark(f)[0], "stacked": stacked, "line": one_line}
PIECE_NAMES = {"mark": "the square mark", "stacked": "the two-line lockup",
               "line": "the one-line lockup"}


# ------------------------------------------------------------------- SVG

def _d(path) -> str:
    pen = SVGPathPen(None, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    path.draw(pen)
    return pen.getCommands()


def bounds(roles):
    xs0, ys0, xs1, ys1 = zip(*(p.bounds for p in roles.values()))
    return min(xs0), min(ys0), max(xs1), max(ys1)


def svg(roles, colorway) -> str:
    fills = COLORWAYS[colorway]
    layers = []
    if fills["letters"] is None:
        # One color: the HQ and its tail are cut out of the square.
        square = minus(roles["square"], union(roles["letters"], roles["tail"]))
        layers.append((fills["square"], union(*(r for k, r in roles.items()
                                                if k in ("word1", "word2")), square)
                       if "word1" in roles else square))
    else:
        for role in ("word1", "word2", "square", "letters", "tail"):
            if role in roles:
                layers.append((fills[role], roles[role]))
    # One path per color, in drawing order (a later color sits on top).
    merged: list[tuple[str, pathops.Path]] = []
    for fill, path in layers:
        if merged and merged[-1][0] == fill:
            merged[-1] = (fill, union(merged[-1][1], path))
        else:
            merged.append((fill, path))
    x0, y0, x1, y1 = bounds(roles)
    x0, y0 = math.floor(x0), math.floor(y0)
    w, h = math.ceil(x1) - x0, math.ceil(y1) - y0
    body = "\n".join(f'  <path fill="{fill}" d="{_d(path)}"/>' for fill, path in merged)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {w} {h}" '
            f'width="{w / 10:g}" height="{h / 10:g}" role="img" aria-label="{NAME}">\n'
            f"  <title>{NAME}</title>\n{body}\n</svg>\n")


def size_of(svg_text):
    view = svg_text.split('viewBox="', 1)[1].split('"', 1)[0].split()
    return float(view[2]), float(view[3])


# ------------------------------------------------------------------ build

def main():
    font = Font(FONT)
    (OUT / "svg").mkdir(parents=True, exist_ok=True)
    (OUT / "png").mkdir(parents=True, exist_ok=True)
    jobs, files = [], []
    for piece, build in PIECES.items():
        roles = build(font)
        for colorway in COLORWAYS:
            text = svg(roles, colorway)
            name = f"enhq-{piece}-{colorway}"
            (OUT / "svg" / f"{name}.svg").write_text(text)
            files.append(f"svg/{name}.svg")
            w, h = size_of(text)
            for width in WIDTHS:
                for bg in ["transparent", *ON[colorway]]:
                    out = f"png/{name}-{bg}-{width}.png"
                    pad = 0 if bg == "transparent" else CLEAR * SIDE
                    # The PNG's width includes the clear space on a background.
                    k = width / (w + 2 * pad)
                    jobs.append({"svg": text, "out": str(OUT / out), "width": width,
                                 "height": round((h + 2 * pad) * k), "pad": pad * k,
                                 "bg": BACKGROUNDS.get(bg)})
                    files.append(out)
    icon = (OUT / "svg" / "enhq-mark-standard.svg").read_text()
    for name, px in ICONS.items():
        jobs.append({"svg": icon, "out": str(OUT / name), "width": px, "height": px,
                     "pad": 0, "bg": None})
    _render(jobs)

    from PIL import Image

    # Chrome writes a PNG with no transparent pixel (the mark, whose square
    # runs to its edges) as RGB; every "transparent" file carries alpha alike.
    for path in (OUT / "png").glob("*-transparent-*.png"):
        with Image.open(path) as im:
            if im.mode != "RGBA":
                im.convert("RGBA").save(path, optimize=True)

    with Image.open(OUT / "favicon-48.png") as big:
        big.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    (OUT / "site.webmanifest").write_text(json.dumps({
        "name": NAME, "short_name": NAME, "start_url": "/", "display": "browser",
        "background_color": WHITE, "theme_color": BLUE,
        "icons": [{"src": "/static/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/brand/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, indent=2) + "\n")
    files += ["favicon.ico", *ICONS, "site.webmanifest"]
    _contact_sheet(files)
    print(f"{len(files)} files in {OUT.relative_to(ROOT)}; contact sheet {SHEET.relative_to(ROOT)}")


def _render(jobs):
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps(jobs))
        subprocess.run(["node", str(ROOT / "scripts/brand/rasterize.mjs"), str(spec), tmp],
                       check=True)


def _contact_sheet(files):
    """Every file on one page, each loaded from disk, at a size the page can
    hold; transparent ones on a checkerboard so their edges show."""
    import html

    from PIL import Image

    cells = []
    for rel in files:
        path = OUT / rel
        if rel.endswith(".webmanifest"):
            body = f"<pre>{html.escape(json.dumps(json.loads(path.read_text())))}</pre>"
            size = "manifest"
        else:
            data = base64.b64encode(path.read_bytes()).decode()
            kind = {"svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}[rel.rsplit(".", 1)[1]]
            if rel.endswith(".png") or rel.endswith(".ico"):
                with Image.open(path) as im:
                    size = f"{im.width} × {im.height}" + (" (16, 32, 48 inside)" if rel.endswith(".ico") else "")
                    small = im.width <= 64
            else:
                w, h = size_of(path.read_text())
                size, small = f"vector, {w:g} × {h:g}", False
            style = "image-rendering:pixelated;width:64px" if small else ""
            body = f'<img src="data:{kind};base64,{data}" style="{style}">'
        checker = "transparent" in rel or rel.startswith("svg/")
        # White artwork on a dark checkerboard, so it can be seen.
        dark = checker and any(f"-{c}" in rel for c in ("reversed", "white"))
        kind_class = " checker dark" if dark else " checker" if checker else ""
        cells.append(f'<figure><div class="art{kind_class}">{body}</div>'
                     f"<figcaption>{html.escape(rel)}<br><span>{size}</span></figcaption></figure>")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; padding: 32px; background: #fff; font: 13px/1.4 system-ui, sans-serif; color: #222; width: 1736px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; color: {BLUE}; }} p {{ margin: 0 0 24px; color: #555; }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
figure {{ margin: 0; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }}
.art {{ height: 190px; display: flex; align-items: center; justify-content: center; padding: 12px; background: #fafafa; }}
.art img {{ max-width: 100%; max-height: 100%; }}
.checker {{ background: repeating-conic-gradient(#e4e4e4 0% 25%, #fff 0% 50%) 50% / 16px 16px; }}
.checker.dark {{ background: repeating-conic-gradient(#3a3a3a 0% 25%, #555 0% 50%) 50% / 16px 16px; }}
.art.text {{ align-items: flex-start; justify-content: flex-start; overflow: auto; }}
pre {{ font-size: 10px; line-height: 1.35; margin: 0; white-space: pre-wrap; word-break: break-all; }}
figcaption {{ padding: 8px 10px; border-top: 1px solid #eee; word-break: break-all; }}
figcaption span {{ color: #777; }}
</style></head><body><h1>{NAME}: brand files</h1>
<p>{len(files)} files in frontend/public/brand (served at /static/brand/). Checkerboard: transparent background.</p>
<div class="grid">{"".join(cells)}</div></body></html>"""
    _render([{"page": page, "out": str(SHEET), "width": 1800}])


if __name__ == "__main__":
    sys.exit(main())
