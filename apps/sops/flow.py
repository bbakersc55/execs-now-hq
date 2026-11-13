"""The process map: a flowchart kept as text, drawn the same way in the app,
the PDF and the Word file (P10, "The process map").

The text is a small part of Mermaid's flowchart language, which Claude writes
well and a person can edit by hand:

    flowchart TD
      start([Order arrives]) --> check{In stock?}
      check -->|Yes| pick[Pick and pack]
      check -->|No| back[Back-order and tell the customer]
      pick --> ship([Ship])

- a node is `id[text]` (a step), `id{text}` (a decision), `id([text])` or
  `id((text))` (a start or an end), or `id(text)` (a rounded step); a node
  named again without a shape keeps the one it had;
- an arrow is `-->`, with an optional label as `-->|label|` or `-- label -->`,
  and arrows chain: `a --> b --> c`;
- the first line may be `flowchart TD` or `graph TD` (any direction is drawn
  top to bottom); lines starting `%%` are comments.

`parse` says what it couldn't read, by line. `layout` places the nodes in
ranks, top to bottom, with arrows that go back up drawn round the right-hand
side. `svg` and `png` draw the same layout.
"""

from __future__ import annotations

import io
import re
import textwrap
from dataclasses import dataclass, field
from html import escape

MAX_NODES = 60
MAX_EDGES = 120
MAX_TEXT = 80
WRAP = 22
CHAR_W = 7.2
LINE_H = 17
PAD_X, PAD_Y = 14, 10
GAP_X, GAP_Y = 28, 46
MARGIN = 20

INK = "#0A3A65"
LINE = "#6D6E71"
FILL = {"step": "#FFFFFF", "round": "#FFFFFF", "decision": "#FDEBD9", "terminal": "#E6EEF5"}

_HEADER = re.compile(r"^(?:flowchart|graph)(?:\s+(?:TD|TB|BT|LR|RL))?\s*;?$", re.I)
_ARROW = re.compile(r"\s*(?:--\s+(?P<l1>[^|>]+?)\s+-->|-->\s*(?:\|(?P<l2>[^|]*)\|)?)\s*")
_NODE = re.compile(r"^(?P<id>[A-Za-z][\w]*)\s*(?P<shape>\(\[.*\]\)|\(\(.*\)\)|\[.*\]|\{.*\}|\(.*\))?$")


class FlowError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Node:
    id: str
    text: str
    shape: str = "step"
    rank: int = 0
    order: float = 0
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    lines: list = field(default_factory=list)


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    back: bool = False


@dataclass
class Chart:
    nodes: dict
    edges: list
    width: float = 0
    height: float = 0


def _shape_of(token: str) -> tuple[str, str]:
    if token.startswith("([") or token.startswith("(("):
        return "terminal", token[2:-2]
    if token.startswith("["):
        return "step", token[1:-1]
    if token.startswith("{"):
        return "decision", token[1:-1]
    return "round", token[1:-1]


def _clean(text: str) -> str:
    text = text.strip().strip('"').strip()
    return " ".join(text.split())[:MAX_TEXT]


def parse(text: str) -> Chart:
    """The chart, or FlowError naming each line it couldn't read."""
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    errors: list[str] = []
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip().rstrip(";").strip()
        if not line or line.startswith("%%") or _HEADER.match(line):
            continue
        parts, labels, at = [], [], 0
        for m in _ARROW.finditer(line):
            parts.append(line[at:m.start()])
            labels.append(_clean(m.group("l1") or m.group("l2") or ""))
            at = m.end()
        parts.append(line[at:])
        ids = []
        for part in parts:
            m = _NODE.match(part.strip())
            if not m:
                errors.append(f"Line {number}: couldn't read “{part.strip()[:40]}”.")
                ids = None
                break
            node_id = m.group("id")
            if m.group("shape"):
                shape, label = _shape_of(m.group("shape"))
                label = _clean(label) or node_id
                if node_id in nodes:
                    nodes[node_id].shape, nodes[node_id].text = shape, label
                else:
                    nodes[node_id] = Node(node_id, label, shape)
            elif node_id not in nodes:
                nodes[node_id] = Node(node_id, node_id)
            ids.append(node_id)
        if ids is None:
            continue
        for i, label in enumerate(labels):
            edges.append(Edge(ids[i], ids[i + 1], label))
    if len(nodes) > MAX_NODES:
        errors.append(f"A map holds {MAX_NODES} boxes at most; this has {len(nodes)}.")
    if len(edges) > MAX_EDGES:
        errors.append(f"A map holds {MAX_EDGES} arrows at most; this has {len(edges)}.")
    if errors:
        raise FlowError(errors)
    return Chart(nodes, edges)


def check(text: str) -> list[str]:
    try:
        parse(text)
    except FlowError as exc:
        return exc.errors
    return []


def from_steps(steps: list) -> str:
    """A straight-line map from an SOP's steps: a start, each step (a step
    whose text asks a question is a decision), and a finish. No AI."""
    lines = ["flowchart TD", "  start([Start])"]
    previous = "start"
    for i, step in enumerate(steps or [], start=1):
        text = _clean(str((step or {}).get("text") if isinstance(step, dict) else step or ""))
        if not text:
            continue
        text = text.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")
        shape = f"{{{text}}}" if text.endswith("?") else f"[{text}]"
        lines.append(f"  {previous} --> s{i}{shape}")
        previous = f"s{i}"
    lines.append(f"  {previous} --> finish([Done])")
    return "\n".join(lines)


# ------------------------------------------------------------------ layout

def _size(node: Node) -> None:
    node.lines = textwrap.wrap(node.text, WRAP) or [node.text]
    widest = max(len(line) for line in node.lines)
    node.w = max(110.0, widest * CHAR_W + 2 * PAD_X)
    node.h = len(node.lines) * LINE_H + 2 * PAD_Y
    if node.shape == "decision":
        node.w, node.h = node.w * 1.35, node.h * 1.6


def layout(chart: Chart) -> Chart:
    order = list(chart.nodes)
    outgoing: dict[str, list[Edge]] = {n: [] for n in order}
    for e in chart.edges:
        outgoing[e.src].append(e)
    # Arrows that go back up (a loop) are found depth first and drawn aside.
    state: dict[str, int] = {}

    def visit(n):
        state[n] = 1
        for e in outgoing[n]:
            if state.get(e.dst) == 1:
                e.back = True
            elif e.dst not in state:
                visit(e.dst)
        state[n] = 2

    for n in order:
        if n not in state:
            visit(n)
    # Each box one rank below the lowest box pointing at it.
    incoming = {n: [e for e in chart.edges if e.dst == n and not e.back] for n in order}
    rank: dict[str, int] = {}

    def rank_of(n, depth=0):
        if n in rank:
            return rank[n]
        if depth > MAX_NODES:
            return 0
        rank[n] = max((rank_of(e.src, depth + 1) + 1 for e in incoming[n]), default=0)
        return rank[n]

    for n in order:
        chart.nodes[n].rank = rank_of(n)
        _size(chart.nodes[n])
    ranks: dict[int, list[Node]] = {}
    for n in order:
        ranks.setdefault(chart.nodes[n].rank, []).append(chart.nodes[n])
    # Within a rank, beneath the boxes pointing at them.
    for r in sorted(ranks):
        row = ranks[r]
        for i, node in enumerate(row):
            parents = [chart.nodes[e.src].order for e in incoming[node.id]]
            node.order = sum(parents) / len(parents) if parents else i
        row.sort(key=lambda node: node.order)
        for i, node in enumerate(row):
            node.order = i
    widths = {r: sum(n.w for n in row) + GAP_X * (len(row) - 1) for r, row in ranks.items()}
    widest = max(widths.values(), default=0)
    y = MARGIN
    for r in sorted(ranks):
        row = ranks[r]
        x = MARGIN + (widest - widths[r]) / 2
        tallest = max(n.h for n in row)
        for node in row:
            node.x, node.y = x, y + (tallest - node.h) / 2
            x += node.w + GAP_X
        y += tallest + GAP_Y
    backs = sum(1 for e in chart.edges if e.back)
    chart.width = widest + 2 * MARGIN + (30 + 14 * backs if backs else 0)
    chart.height = max(y - GAP_Y + MARGIN, 2 * MARGIN)
    return chart


def _routes(chart: Chart):
    """Each arrow as points, with where its label goes."""
    right = MARGIN + max((n.x + n.w for n in chart.nodes.values()), default=0)
    k = 0
    for e in chart.edges:
        a, b = chart.nodes[e.src], chart.nodes[e.dst]
        if e.back or b.y <= a.y:
            k += 1
            lane = right + 14 * k
            points = [(a.x + a.w, a.y + a.h / 2), (lane, a.y + a.h / 2),
                      (lane, b.y + b.h / 2), (b.x + b.w, b.y + b.h / 2)]
            label_at = (lane + 4, (a.y + b.y + b.h) / 2)
        else:
            x1, y1 = a.x + a.w / 2, a.y + a.h
            x2, y2 = b.x + b.w / 2, b.y
            mid = y1 + min(GAP_Y / 2, (y2 - y1) / 2)
            points = [(x1, y1), (x1, mid), (x2, mid), (x2, y2)] if abs(x1 - x2) > 1 \
                else [(x1, y1), (x2, y2)]
            label_at = ((x1 + x2) / 2 + 6, mid - 4 if abs(x1 - x2) > 1 else (y1 + y2) / 2)
        yield e, points, label_at


# ------------------------------------------------------------------ drawing

def svg(text: str, *, title: str = "Process map") -> str:
    """The map as an SVG document (escaped; no script). Raises FlowError."""
    chart = layout(parse(text))
    w, h = max(chart.width, 160), max(chart.height, 60)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
           f'width="{w:.0f}" height="{h:.0f}" role="img" aria-label="{escape(title)}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="13">',
           f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
           f'fill="{LINE}"/></marker></defs>',
           f'<rect x="0" y="0" width="{w:.0f}" height="{h:.0f}" fill="#FFFFFF"/>']
    for e, points, (lx, ly) in _routes(chart):
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        out.append(f'<polyline points="{path}" fill="none" stroke="{LINE}" stroke-width="1.4" '
                   'marker-end="url(#arrow)"/>')
        if e.label:
            out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{INK}" font-size="12" '
                       f'font-style="italic">{escape(e.label)}</text>')
    for node in chart.nodes.values():
        x, y, nw, nh = node.x, node.y, node.w, node.h
        fill = FILL[node.shape]
        if node.shape == "decision":
            cx, cy = x + nw / 2, y + nh / 2
            out.append(f'<polygon points="{cx:.1f},{y:.1f} {x + nw:.1f},{cy:.1f} {cx:.1f},'
                       f'{y + nh:.1f} {x:.1f},{cy:.1f}" fill="{fill}" stroke="#F58220" '
                       'stroke-width="1.6"/>')
        else:
            radius = nh / 2 if node.shape == "terminal" else (10 if node.shape == "round" else 4)
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{nw:.1f}" height="{nh:.1f}" '
                       f'rx="{radius:.1f}" fill="{fill}" stroke="{INK}" stroke-width="1.4"/>')
        first = y + nh / 2 - (len(node.lines) - 1) * LINE_H / 2 + 4.5
        for i, line in enumerate(node.lines):
            out.append(f'<text x="{x + nw / 2:.1f}" y="{first + i * LINE_H:.1f}" '
                       f'text-anchor="middle" fill="#1A1A1A">{escape(line)}</text>')
    out.append("</svg>")
    return "".join(out)


def _font(size):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                          # an old Pillow without sizes
        return ImageFont.load_default()


def _hex(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def png(text: str, *, scale: int = 2) -> bytes:
    """The same map as a PNG, for the Word file. Raises FlowError."""
    from PIL import Image, ImageDraw

    chart = layout(parse(text))
    w, h = int(max(chart.width, 160) * scale), int(max(chart.height, 60) * scale)
    image = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12 * scale), _font(11 * scale)

    def s(points):
        return [(x * scale, y * scale) for x, y in points]

    for e, points, (lx, ly) in _routes(chart):
        pts = s(points)
        draw.line(pts, fill=_hex(LINE), width=max(1, int(1.4 * scale)))
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        dx, dy = x2 - x1, y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        size = 6 * scale
        draw.polygon([(x2, y2), (x2 - ux * size - uy * size / 2, y2 - uy * size + ux * size / 2),
                      (x2 - ux * size + uy * size / 2, y2 - uy * size - ux * size / 2)],
                     fill=_hex(LINE))
        if e.label:
            draw.text((lx * scale, ly * scale - 10 * scale), e.label, fill=_hex(INK), font=small)
    for node in chart.nodes.values():
        x, y, nw, nh = node.x * scale, node.y * scale, node.w * scale, node.h * scale
        fill = _hex(FILL[node.shape])
        if node.shape == "decision":
            cx, cy = x + nw / 2, y + nh / 2
            draw.polygon([(cx, y), (x + nw, cy), (cx, y + nh), (x, cy)], fill=fill,
                         outline=_hex("#F58220"), width=max(1, int(1.6 * scale)))
        else:
            radius = nh / 2 if node.shape == "terminal" else (10 if node.shape == "round" else 4) * scale
            draw.rounded_rectangle([x, y, x + nw, y + nh], radius=radius, fill=fill,
                                   outline=_hex(INK), width=max(1, int(1.4 * scale)))
        total = len(node.lines) * LINE_H * scale
        top = y + (nh - total) / 2
        for i, line in enumerate(node.lines):
            box = draw.textbbox((0, 0), line, font=font)
            draw.text((x + (nw - (box[2] - box[0])) / 2, top + i * LINE_H * scale + 2 * scale),
                      line, fill=(26, 26, 26), font=font)
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
