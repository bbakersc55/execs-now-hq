"""The strategy session as an editable Word file (2026-10-15).

Beside the PDF, not instead of it: the same sections, in the same order and
under the same headings, built from the same `pdf.context_for(session)`, so
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
        c = self.c
        self.logo()
        self.doc.add_heading("Strategy session", level=0)
        who = " · ".join(x for x in (c["company"], c["prospect"], c["session_date"]) if x)
        if c["fractional"]:
            who += f" · with {c['fractional']}"
        self.para(who, muted=True)
        chips = [item for item in (c["snapshot"] or [])[:4] if item.get("text")]
        if chips:
            self.table(["", ""], [[item["label"], item["text"]] for item in chips], [2.2, 4.3])

        self.ratings()
        self.mirror()
        self.map()
        self.paths()
        if c["values"]:
            rows = [[v["value"], v["why"]] for v in c["values"] if v["value"]]
            if rows:
                self.heading("What you told us matters")
                self.table(["What matters", "Why"], rows, [2.6, 3.9])
        for part in c.get("custom_sections") or []:
            self.heading(part["title"])
            self.table(["", ""], [[item["prompt"], self._custom_answer(item)]
                                  for item in part["answers"]], [2.6, 3.9])
        steps = [s for s in c["next_steps"] if s.get("agreed") or s.get("detail")]
        if steps:
            self.heading("What happens next")
            self.table(["", "Next", "When"],
                       [["✓" if s.get("agreed") else "☐", s["label"], s.get("detail") or ""]
                        for s in steps], [0.4, 3.6, 2.5])
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

    def ratings(self):
        six = self.c["six_key"]
        if not six["ratings"]:
            return
        self.heading(self.c.get("ratings_title") or "The six key components")
        table = self.table(["", "Score", "In their words"],
                           [[r["label"], f"{r['rating']} of 10", r["comment"]]
                            for r in six["ratings"]], [1.8, 0.8, 3.9])
        for row, rating in zip(table.rows[1:], six["ratings"]):
            if rating["is_lowest"]:
                for run in row.cells[1].paragraphs[0].runs:
                    run.bold = True
                    run.font.color.rgb = self.accent
        line = f"{six['scale']}."
        if six["complete"]:
            line += f" Average {six['average']} of 10."
        self.para(line + " The lowest score is where we look first.", muted=True, size=9)

    def mirror(self):
        c = self.c
        if not (c["mirror_goal"] or c["mirror_unlocks"]):
            return
        self.heading("The mirror")
        for label, whole, points in (
                ("Where you said you want to go", c["mirror_goal"], c["mirror_goal_points"]),
                ("What unlocks it", c["mirror_unlocks"], c["mirror_unlocks_points"])):
            if not whole:
                continue
            self.para(label, bold=True)
            if c["focused"]:
                self.bullets(points)
            else:
                self.para(whole)

    def map(self):
        c = self.c
        if not c["map_rows"]:
            return
        self.heading("The strategy map — what we would change, and when")
        if c["focused"]:
            self.table(["When", "", ""],
                       [[card["label"], card["header"], card.get("statement") or ""]
                        for card in c["focused_cards"]], [0.9, 2.2, 3.4])
            return
        head = ["When", "Bottleneck", "The fix", "Owner", "Measurable"]
        if c["show_mechanics"]:
            head.append("Notes from experience")
        rows, also = [], []
        for bucket in c["horizons"]:
            for row in bucket["cards"]:
                line = [bucket["label"], row["bottleneck"], row["the_fix"], row["owner_text"],
                        row["measurable"] or "measure to be agreed"]
                if c["show_mechanics"]:
                    line.append(row.get("mechanics_note") or "")
                rows.append(line)
            also += [[bucket["label"], row["bottleneck"]] for row in bucket.get("also") or []]
        self.table(head, rows, [0.8, 1.5, 1.7, 1.0, 1.5] + ([1.5] if c["show_mechanics"] else []))
        if also:
            self.para("Also noted — lower priority", bold=True)
            self.table(["When", "Bottleneck"], also, [0.8, 5.7])

    def paths(self):
        pair = self.c["path_pair"]
        if not pair:
            return
        self.heading("Two ways forward")
        for path in pair:
            self.heading(f"{path['label']}: {path['title']}", level=2)
            for move in path.get("moves") or []:
                p = self.para(move["headline"], bold=True)
                if move.get("detail"):
                    p.add_run(f"\n{move['detail']}")
            if path.get("pros"):
                self.para("What is good about it", bold=True)
                self.bullets(path["pros"])
            if path.get("cons"):
                self.para("What it costs you", bold=True)
                self.bullets(path["cons"])
            if path.get("leaning"):
                p = self.para("Your leaning", bold=True)
                p.add_run(f" · {path['leaning']}")

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
