"""The org chart by seat, drawn (P12, 2026-11-14, E1): a conventional top-down
chart, the same drawing on the screen, in the PDF and (as a PNG) in Word.

- **Boxes:** one a seat, each with a header band in the practice's header
  colour holding the seat's title in white, and beneath it the person in the
  seat (or "Open") and the department.
- **What stands out:** an open seat has a dashed border in the practice's
  accent colour and "Open" in that colour; a seat with any "No" among its
  checks has a red outline and a small "A no" marker.
- **The tree:** from the top seat (or seats, side by side) down, each seat
  centred over the seats reporting to it, joined by elbow lines. A seat that
  reports to itself, to a seat that isn't there, or round a loop is drawn as
  a top seat: the drawing always ends.

`layout` places the boxes; `svg` and `png` draw the same layout. Every text
is escaped and the SVG has no script.
"""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass, field
from html import escape

BOX_W = 196
BAND_LINE = 16
BODY_LINE = 18
GAP_X, GAP_Y = 22, 46
ROOT_GAP = 40
MARGIN = 20
TITLE_WRAP = 24
BODY_CHARS = 27
CHECKS = ("knows", "wants", "has_time")

INK = "#1A1A1A"
MUTED = "#6D6E71"
LINE = "#939598"
EDGE = "#C9CED6"
NO = "#C0392B"


@dataclass
class Seat:
    index: int
    title: str
    person: str
    department: str
    is_open: bool
    has_no: bool
    reports_to: str = ""
    parent: int | None = None
    children: list = field(default_factory=list)
    title_lines: list = field(default_factory=list)
    depth: int = 0
    span: float = 0
    x: float = 0
    y: float = 0


@dataclass
class Chart:
    seats: list
    roots: list
    band_h: float = 0
    box_h: float = 0
    width: float = 0
    height: float = 0


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _fit(text, chars) -> str:
    return text if len(text) <= chars else text[:chars - 1].rstrip() + "…"


def seats_of(rows, view) -> list[Seat]:
    """The seats with a name, in the table's order, each knowing the seat it
    reports to (None at the top)."""
    view = view or {}
    name_key, parent_key = view.get("name") or "seat", view.get("parent") or "reports_to"
    person_key = view.get("person") or "person"
    department_key = view.get("department") or "department"
    checks = view.get("checks") or CHECKS
    seats = []
    for row in rows or []:
        row = row if isinstance(row, dict) else {}
        title = _text(row.get(name_key))
        if not title:
            continue
        person = _text(row.get(person_key))
        seats.append(Seat(
            index=len(seats), title=title,
            person="" if person.lower() == "open" else person,
            department=_text(row.get(department_key)),
            is_open=person == "" or person.lower() == "open",
            has_no=any(_text(row.get(c)).lower() == "no" for c in checks),
            reports_to=_text(row.get(parent_key))))
    first = {}
    for seat in seats:
        first.setdefault(seat.title.lower(), seat.index)
    for seat in seats:
        boss = first.get(seat.reports_to.lower()) if seat.reports_to else None
        seat.parent = boss if boss is not None and boss != seat.index else None
    return seats


def _claim(seats, roots):
    """Each seat's children, from the top down. A seat no top seat reaches (it
    is on a loop) becomes a top seat itself, so the walk always ends."""
    claimed = set()
    kids = {s.index: [] for s in seats}
    for s in seats:
        if s.parent is not None:
            kids[s.parent].append(s.index)

    def walk(start):
        stack = [start]
        claimed.add(start.index)
        while stack:
            seat = stack.pop()
            seat.children = [seats[i] for i in kids[seat.index] if i not in claimed]
            for child in seat.children:
                claimed.add(child.index)
                child.depth = seat.depth + 1
            stack.extend(reversed(seat.children))

    for seat in seats:
        if seat.parent is None:
            roots.append(seat)
            walk(seat)
    for seat in seats:
        if seat.index not in claimed:
            seat.parent, seat.depth = None, 0
            roots.append(seat)
            walk(seat)


def _spans(seat) -> float:
    # Leaves first, without recursion: a deep chart never meets Python's limit.
    order, stack = [], [seat]
    while stack:
        s = stack.pop()
        order.append(s)
        stack.extend(s.children)
    for s in reversed(order):
        inner = sum(c.span for c in s.children) + GAP_X * (len(s.children) - 1)
        s.span = max(BOX_W, inner) if s.children else BOX_W
    return seat.span


def _place(root, left, row_h):
    stack = [(root, left)]
    order = []
    while stack:
        seat, at = stack.pop()
        order.append(seat)
        seat.y = MARGIN + seat.depth * row_h
        if seat.children:
            inner = sum(c.span for c in seat.children) + GAP_X * (len(seat.children) - 1)
            x = at + (seat.span - inner) / 2
            for child in seat.children:
                stack.append((child, x))
                x += child.span + GAP_X
        else:
            seat.x = at + (seat.span - BOX_W) / 2
    for seat in reversed(order):           # a parent sits centred over its children
        if seat.children:
            first, last = seat.children[0], seat.children[-1]
            seat.x = (first.x + last.x) / 2


def layout(rows, view=None) -> Chart:
    seats = seats_of(rows, view)
    chart = Chart(seats=seats, roots=[])
    _claim(seats, chart.roots)
    chart.roots.sort(key=lambda seat: seat.index)
    for seat in seats:
        seat.title_lines = textwrap.wrap(seat.title, TITLE_WRAP)[:2] or [seat.title]
        if len(textwrap.wrap(seat.title, TITLE_WRAP)) > 2:
            seat.title_lines[1] = _fit(seat.title_lines[1] + " …", TITLE_WRAP)
    lines = max((len(s.title_lines) for s in seats), default=1)
    chart.band_h = lines * BAND_LINE + 12
    body_lines = 2 if any(s.department for s in seats) else 1
    chart.box_h = chart.band_h + body_lines * BODY_LINE + 14
    row_h = chart.box_h + GAP_Y
    left = MARGIN
    for root in chart.roots:
        _spans(root)
        _place(root, left, row_h)
        left += root.span + ROOT_GAP
    deepest = max((s.depth for s in seats), default=0)
    chart.width = max(left - ROOT_GAP + MARGIN, 2 * MARGIN + BOX_W) if seats else 0
    chart.height = 2 * MARGIN + (deepest + 1) * chart.box_h + deepest * GAP_Y if seats else 0
    return chart


def _links(chart):
    """Each parent's elbow: down from its middle, across its children, down to each."""
    for seat in chart.seats:
        if not seat.children:
            continue
        x = seat.x + BOX_W / 2
        top = seat.y + chart.box_h
        mid = top + GAP_Y / 2
        centres = [c.x + BOX_W / 2 for c in seat.children]
        yield (x, top, mid, min(centres + [x]), max(centres + [x]),
               [(c.x + BOX_W / 2, c.y) for c in seat.children])


def tint(color, share=0.1) -> str:
    """The colour mixed into white: `share` of it."""
    r, g, b = _hex(color)
    return "#{:02X}{:02X}{:02X}".format(*(round(255 - (255 - v) * share) for v in (r, g, b)))


def summary(chart) -> str:
    seats = len(chart.seats)
    opened = sum(s.is_open for s in chart.seats)
    nos = sum(s.has_no for s in chart.seats)
    return (f"Org chart: {seats} {'seat' if seats == 1 else 'seats'}, {opened} open, "
            f"{nos} with a no.")


def svg(rows, view=None, *, header="#0A3A65", accent="#F58220", width=None) -> str:
    """The chart as an SVG document. `width` draws it that wide (scaled to fit),
    never wider than it is; empty text when there is no seat."""
    chart = layout(rows, view)
    if not chart.seats:
        return ""
    w, h = chart.width, chart.height
    shown_w = min(w, width) if width else w
    shown_h = h * shown_w / w
    label = summary(chart)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
           f'width="{shown_w:.0f}" height="{shown_h:.0f}" role="img" '
           f'aria-label="{escape(label)}" font-family="Helvetica, Arial, sans-serif" '
           'font-size="13">',
           f"<title>{escape(label)}</title>",
           f'<rect x="0" y="0" width="{w:.0f}" height="{h:.0f}" fill="#FFFFFF"/>']
    for x, top, mid, left, right, drops in _links(chart):
        d = f"M{x:.1f},{top:.1f} V{mid:.1f} M{left:.1f},{mid:.1f} H{right:.1f}"
        d += "".join(f" M{cx:.1f},{mid:.1f} V{cy:.1f}" for cx, cy in drops)
        out.append(f'<path class="link" d="{d}" fill="none" stroke="{LINE}" '
                   'stroke-width="1.4"/>')
    band, box = chart.band_h, chart.box_h
    open_fill = tint(accent, 0.08)
    for s in chart.seats:
        x, y = s.x, s.y
        kinds = "seat" + (" open" if s.is_open else "") + (" no" if s.has_no else "")
        out.append(f'<g class="{kinds}" data-seat="{escape(s.title)}">')
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{BOX_W}" height="{box:.1f}" rx="6" '
                   f'fill="{open_fill if s.is_open else "#FFFFFF"}"/>')
        out.append(f'<path class="band" d="M{x:.1f},{y + band:.1f} V{y + 6:.1f} '
                   f'Q{x:.1f},{y:.1f} {x + 6:.1f},{y:.1f} H{x + BOX_W - 6:.1f} '
                   f'Q{x + BOX_W:.1f},{y:.1f} {x + BOX_W:.1f},{y + 6:.1f} V{y + band:.1f} Z" '
                   f'fill="{header}"/>')
        first = y + band / 2 - (len(s.title_lines) - 1) * BAND_LINE / 2 + 4.5
        for i, line in enumerate(s.title_lines):
            out.append(f'<text x="{x + BOX_W / 2:.1f}" y="{first + i * BAND_LINE:.1f}" '
                       'text-anchor="middle" fill="#FFFFFF" font-weight="700" '
                       f'font-size="12.5">{escape(line)}</text>')
        line_y = y + band + BODY_LINE
        if s.is_open:
            out.append(f'<text class="person" x="{x + BOX_W / 2:.1f}" y="{line_y:.1f}" '
                       f'text-anchor="middle" fill="{accent}" font-weight="700">Open</text>')
        else:
            out.append(f'<text class="person" x="{x + BOX_W / 2:.1f}" y="{line_y:.1f}" '
                       f'text-anchor="middle" fill="{INK}">'
                       f'{escape(_fit(s.person, BODY_CHARS))}</text>')
        if s.department:
            out.append(f'<text class="department" x="{x + BOX_W / 2:.1f}" '
                       f'y="{line_y + BODY_LINE:.1f}" text-anchor="middle" fill="{MUTED}" '
                       f'font-size="12">{escape(_fit(s.department, BODY_CHARS + 2))}</text>')
        stroke = NO if s.has_no else (accent if s.is_open else EDGE)
        dash = ' stroke-dasharray="6 4"' if s.is_open else ""
        out.append(f'<rect class="outline" x="{x:.1f}" y="{y:.1f}" width="{BOX_W}" '
                   f'height="{box:.1f}" rx="6" fill="none" stroke="{stroke}" '
                   f'stroke-width="{2.4 if s.has_no or s.is_open else 1.2}"{dash}/>')
        if s.has_no:
            px, py = x + BOX_W - 50, y + box - 9
            out.append(f'<rect class="marker" x="{px:.1f}" y="{py:.1f}" width="42" '
                       f'height="18" rx="9" fill="{NO}"/>')
            out.append(f'<text x="{px + 21:.1f}" y="{py + 12.5:.1f}" text-anchor="middle" '
                       'fill="#FFFFFF" font-size="10.5" font-weight="700">A no</text>')
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def drawing(rows, view, brand) -> dict:
    """What the screen gets: the SVG, its own size, and a sentence for its alt
    text. `brand` is `email_layout.branding` of the practice."""
    chart = layout(rows, view)
    header = getattr(brand, "header_color", "") or "#0A3A65"
    accent = getattr(brand, "accent_color", "") or "#F58220"
    return {"type": "org_chart", "svg": svg(rows, view, header=header, accent=accent) or None,
            "width": round(chart.width), "height": round(chart.height),
            "label": summary(chart) if chart.seats else "No seats yet."}


# ------------------------------------------------------------------ the PNG, for Word

def _hex(color):
    color = (color or "#000000").lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _font(size, bold=False):
    from PIL import ImageFont

    names = (("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "Arial Bold.ttf", "LiberationSans-Bold.ttf") if bold else ()) + (
        "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "Arial.ttf",
        "LiberationSans-Regular.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                          # an old Pillow without sizes
        return ImageFont.load_default()


def _dashed(draw, box, color, width, dash=12, gap=8):
    x1, y1, x2, y2 = box
    for (ax, ay, bx, by) in ((x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2),
                             (x1, y2, x1, y1)):
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        ux, uy = (bx - ax) / length, (by - ay) / length
        at = 0.0
        while at < length:
            end = min(at + dash, length)
            draw.line([(ax + ux * at, ay + uy * at), (ax + ux * end, ay + uy * end)],
                      fill=color, width=width)
            at = end + gap


def png(rows, view=None, *, header="#0A3A65", accent="#F58220", scale=2) -> bytes:
    """The same chart as a PNG. Empty bytes when there is no seat."""
    from PIL import Image, ImageDraw

    chart = layout(rows, view)
    if not chart.seats:
        return b""
    image = Image.new("RGB", (int(chart.width * scale), int(chart.height * scale)), "white")
    draw = ImageDraw.Draw(image)
    title, body, small, tag = (_font(int(12 * scale), bold=True), _font(int(12.5 * scale)),
                               _font(int(11.5 * scale)), _font(int(10 * scale), bold=True))
    line = max(1, int(1.4 * scale))
    for x, top, mid, left, right, drops in _links(chart):
        draw.line([(x * scale, top * scale), (x * scale, mid * scale)], fill=_hex(LINE),
                  width=line)
        draw.line([(left * scale, mid * scale), (right * scale, mid * scale)], fill=_hex(LINE),
                  width=line)
        for cx, cy in drops:
            draw.line([(cx * scale, mid * scale), (cx * scale, cy * scale)], fill=_hex(LINE),
                      width=line)

    def centred(text, cx, cy, font, fill):
        try:                                   # the font's own middle: every line level
            draw.text((cx, cy), text, fill=fill, font=font, anchor="mm")
        except (ValueError, TypeError):        # a bitmap font has no anchors
            box = draw.textbbox((0, 0), text, font=font)
            draw.text((cx - (box[2] - box[0]) / 2, cy - (box[3] - box[1]) / 2 - box[1]),
                      text, fill=fill, font=font)

    band, height = chart.band_h * scale, chart.box_h * scale
    for s in chart.seats:
        x, y, w = s.x * scale, s.y * scale, BOX_W * scale
        fill = _hex(tint(accent, 0.08)) if s.is_open else (255, 255, 255)
        draw.rounded_rectangle([x, y, x + w, y + height], radius=6 * scale, fill=fill)
        draw.rounded_rectangle([x, y, x + w, y + band], radius=6 * scale, fill=_hex(header))
        draw.rectangle([x, y + band - 6 * scale, x + w, y + band], fill=_hex(header))
        first = y + band / 2 - (len(s.title_lines) - 1) * BAND_LINE * scale / 2
        for i, text in enumerate(s.title_lines):
            centred(text, x + w / 2, first + i * BAND_LINE * scale, title, (255, 255, 255))
        line_y = y + band + (BODY_LINE - 4.5) * scale
        if s.is_open:
            centred("Open", x + w / 2, line_y, _font(int(12.5 * scale), bold=True),
                    _hex(accent))
        else:
            centred(_fit(s.person, BODY_CHARS), x + w / 2, line_y, body, _hex(INK))
        if s.department:
            centred(_fit(s.department, BODY_CHARS + 2), x + w / 2,
                    line_y + BODY_LINE * scale, small, _hex(MUTED))
        stroke = _hex(NO if s.has_no else (accent if s.is_open else EDGE))
        weight = max(1, int((2.4 if s.has_no or s.is_open else 1.2) * scale))
        if s.is_open:
            _dashed(draw, (x, y, x + w, y + height), stroke, weight)
        else:
            draw.rounded_rectangle([x, y, x + w, y + height], radius=6 * scale,
                                   outline=stroke, width=weight)
        if s.has_no:
            px, py = x + w - 50 * scale, y + height - 9 * scale
            draw.rounded_rectangle([px, py, px + 42 * scale, py + 18 * scale],
                                   radius=9 * scale, fill=_hex(NO))
            centred("A no", px + 21 * scale, py + 9 * scale, tag, (255, 255, 255))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
