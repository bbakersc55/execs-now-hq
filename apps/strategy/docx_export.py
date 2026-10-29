"""The strategy session as an editable Word file (2026-10-15).

Beside the PDF, not instead of it: the same sections, in the same order and
under the same headings (the two-page design of 2026-10-15), built from the
same `pdf.context_for(session)` and the same words, so
**everything the PDF leaves out is left out here too** — the private notes,
the observation never asked aloud and the money, each until its flag is on.
What differs is only what paper forces: the PDF's chart is a table of ratings,
its cards are table rows, and text the PDF shortens to fit a card is whole
here, because this file is for editing.

The practice's branding: its logo at the top (or its name), its header colour
on the headings and table heads, its accent on the lowest rating, and its
footer text in the page footer.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from apps.strategy import pdf as pdf_service

CONTENT_TYPE = ("application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document")


def _rgb(hex_color: str) -> RGBColor:
    value = (hex_color or "#1F2933").lstrip("#")
    try:
        return RGBColor.from_string(value.upper())
    except ValueError:
        return RGBColor.from_string("1F2933")


def _shade(cell, hex_color: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), (hex_color or "#1F2933").lstrip("#"))
    cell._tc.get_or_add_tcPr().append(shading)


class _Writer:
    def __init__(self, context: dict):
        self.c = context
        self.brand = context["brand"]
        self.header = _rgb(self.brand.header_color)
        self.accent = _rgb(self.brand.accent_color)
        self.doc = Document()
        style = self.doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10.5)
        for name in ("Title", "Heading 1", "Heading 2"):
            self.doc.styles[name].font.color.rgb = self.header

    # ------------------------------------------------------------- pieces
    def heading(self, text: str, level: int = 1):
        return self.doc.add_heading(text, level=level)

    def para(self, text: str = "", *, bold: bool = False, italic: bool = False,
             muted: bool = False, size: float | None = None):
        p = self.doc.add_paragraph()
        if text:
            run = p.add_run(text)
            run.bold, run.italic = bold, italic
            if muted:
                run.font.color.rgb = RGBColor(0x6D, 0x6E, 0x71)
            if size:
                run.font.size = Pt(size)
        return p

    def bullets(self, items):
        for item in items:
            self.doc.add_paragraph(str(item), style="List Bullet")

    def table(self, head: list[str], rows: list[list[str]], widths: list[float] | None = None):
        """A Word table. A head of empty strings is no head row at all;
        `widths` are inches, one a column."""
        headed = any(head)
        table = self.doc.add_table(rows=1 if headed else 0, cols=len(head))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        if headed:
            for cell, text in zip(table.rows[0].cells, head):
                cell.text = ""
                run = cell.paragraphs[0].add_run(text)
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                _shade(cell, self.brand.header_color)
        for values in rows:
            cells = table.add_row().cells
            for cell, text in zip(cells, values):
                cell.text = str(text or "")
        if widths:
            table.autofit = False
            # Word reads the cells' widths, LibreOffice the grid's: set both.
            for column, width in zip(table.columns, widths):
                column.width = Inches(width)
            for row in table.rows:
                for cell, width in zip(row.cells, widths):
                    cell.width = Inches(width)
        self.doc.add_paragraph()
        return table

    # ----------------------------------------------------------- the file
    def write(self) -> bytes:
        """The two-page design's sections, in its order (2026-10-15): the
        header and headline, the tiles, the mirror, the components; then the
        30/60/90 map, the two paths, the next moves and the sign-off; then,
        as on paper, anything the practice asked to print beyond the two."""
        c, doc = self.c, self.c["doc"]
        self.logo()
        self.para(f"Strategy session · {doc['long_date']}", muted=True, size=9)
        eyebrow = " · ".join(x for x in (c["company"], f"Prepared for {c['prospect']}") if x)
        self.para(eyebrow, bold=True, size=9).runs[0].font.color.rgb = self.accent
        if doc["headline"]:
            self.doc.add_heading(doc["headline"], level=0)
        if doc["intro"]:
            self.para(doc["intro"])
        if doc["tiles"]:
            table = self.table(["", ""], [[t["number"], t["label"]] for t in doc["tiles"]],
                               [0.9, 5.6])
            for row in table.rows:
                for run in row.cells[0].paragraphs[0].runs:
                    run.bold, run.font.size = True, Pt(16)
                    run.font.color.rgb = self.header
        self.mirror()
        self.components()
        self.map()
        self.paths()
        self.next_moves()
        self.signoff()
        for part in c.get("custom_sections") or []:
            self.heading(part["title"])
            self.table(["", ""], [[item["prompt"], self._custom_answer(item)]
                                  for item in part["answers"]], [2.6, 3.9])
        if c.get("mechanics_notes"):
            self.heading("Notes from experience")
            self.table(["", ""], [[item["header"], item["note"]]
                                  for item in c["mechanics_notes"]], [2.6, 3.9])
        if c.get("scorecard"):
            self.heading(c["scorecard_heading"])
            self.table(["", ""], [[item["name"] + (f" ({'; '.join(item['moves'])})"
                                                    if item["moves"] else ""),
                                   " · ".join(x for x in (
                                       ", ".join(x for x in (item["value"], item["period"])
                                                 if x),
                                       item["target"], item["status_label"]) if x)]
                                  for item in c["scorecard"]], [2.6, 3.9])
        if c["money"]:
            self.heading("Scope and investment")
            self.table(["", "", ""],
                       [["✓" if (item["value"] or {}).get("agreed") else "☐",
                         item["prompt"], item["text"]] for item in c["money"]], [0.4, 3.6, 2.5])
        self.footer()
        out = io.BytesIO()
        self.doc.save(out)
        return out.getvalue()

    @staticmethod
    def _custom_answer(item) -> str:
        text = ("✓ " if item.get("is_agreed_note") and item.get("agreed") else "") \
            + (item.get("text") or "")
        return text + (f"\n{item['note']}" if item.get("note") else "")

    def logo(self):
        from apps.tenancy import storage

        tenant = self.c["session"].tenant
        content = None
        if tenant.email_logo_id:
            try:
                content = storage.read(tenant.email_logo)
            except storage.StorageError:
                content = None
        if content:
            try:
                self.doc.add_picture(io.BytesIO(content), height=Pt(26))
                return
            except Exception:  # an image Word cannot take: the name instead
                pass
        self.para(self.c["practice"], bold=True, size=12)

    def mirror(self):
        mirror = self.c["doc"]["mirror"]
        if not mirror:
            return
        self.heading("The mirror")
        self.para("What we heard, in your words", muted=True, size=9)
        if mirror["headline"]:
            self.para(mirror["headline"], bold=True, size=13)
        if mirror["body"]:
            self.para(mirror["body"])
        if mirror["working"] or mirror["not_yet"]:
            self.table(["Working", "Not yet"], [[mirror["working"], mirror["not_yet"]]],
                       [3.25, 3.25])

    def components(self):
        doc = self.c["doc"]
        if not doc["components"]:
            return
        self.heading(f"The {doc['components_count']} components: where the company stands")
        self.table(["", "", ""], [[c["pill_label"], c["name"], c.get("line") or ""]
                                  for c in doc["components"]], [0.8, 1.7, 4.0])
        if doc["also_rated"]:
            self.para(f"Also rated: {'; '.join(doc['also_rated'])}.", muted=True, size=9)

    def map(self):
        doc = self.c["doc"]
        if not doc["boxes"]:
            return
        self.heading("The next ninety days: the map")
        head = [f"Day {box['days']} · {box['date']}" for box in doc["boxes"]]
        table = self.table(head, [[""] * len(head)], [2.17] * len(head))
        for cell, box in zip(table.rows[1].cells, doc["boxes"]):
            cell.text = ""
            for index, bullet in enumerate(box["bullets"]):
                p = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
                p.add_run(f"• {bullet['text']}")
                if bullet.get("owner"):
                    p.add_run(f" {bullet['owner']}").bold = True
        if doc["undated"]:
            self.para(f"Not dated yet: {'; '.join(doc['undated'])}.", muted=True, size=9)

    def paths(self):
        paths = self.c["doc"]["paths"]
        if not paths:
            return
        self.heading("Two paths: how to get there")
        for path in paths:
            heading = self.heading(path["title"], level=2)
            if path.get("recommended"):
                heading.add_run("  · Recommended")
            if path.get("blurb"):
                self.para(path["blurb"])
            if path.get("for") or path.get("against"):
                points = max(len(path.get("for") or []), len(path.get("against") or []))
                rows = [[(path.get("for") or [])[i] if i < len(path.get("for") or []) else "",
                         (path.get("against") or [])[i]
                         if i < len(path.get("against") or []) else ""]
                        for i in range(points)]
                self.table(["For", "Against"], rows, [3.25, 3.25])

    def next_moves(self):
        moves = self.c["doc"]["next_moves"]
        if not moves:
            return
        self.heading("Before we meet again: your next moves")
        for move in moves:
            p = self.doc.add_paragraph(style="List Bullet")
            if move.get("lead"):
                p.add_run(move["lead"]).bold = True
            if move.get("rest"):
                p.add_run(("" if move.get("tight") else " ") + move["rest"])

    def signoff(self):
        doc = self.c["doc"]
        if doc["closing"]:
            self.para(doc["closing"], italic=True, size=12)
        if self.c.get("signoff"):
            self.para(self.c["signoff"], muted=True, size=9)

    def footer(self):
        text = (getattr(self.c["session"].tenant, "brand_footer_text", "") or "").strip()
        footer = self.doc.sections[0].footer.paragraphs[0]
        footer.text = " · ".join(x for x in [self.c["practice"], *text.splitlines()] if x)
        for run in footer.runs:
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x6D, 0x6E, 0x71)


def render_docx(session) -> bytes:
    """The bytes. Nothing is stored and nothing is sent: generating is not
    sending, as for the PDF."""
    return _Writer(pdf_service.context_for(session)).write()


def filename(session) -> str:
    import re

    from django.utils import timezone

    who = session.company.name if session.company else (
        f"{session.contact.first_name} {session.contact.last_name}")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", who).strip("-").lower() or "session"
    return f"strategy-session-{slug}-{timezone.localdate().isoformat()}.docx"
