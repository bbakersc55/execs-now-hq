"""A run on the practice's letterhead (P12): PDF, through the e-signature's
letterhead (`apps.esign.pdf`), and Word, with the practice's name, the
company and the date at the top. The meeting cadence's agendas are a Word
document of their own."""

from __future__ import annotations

import io
import re
from html import escape

from django.utils import timezone

from . import definition as D
from .services import events_of

_TABLE_CSS = ("<style>table.run{width:100%;border-collapse:collapse;font-size:10px;margin:6px 0 14px}"
              "table.run th,table.run td{border:1px solid #DDE1E6;padding:3px 5px;text-align:left;"
              "vertical-align:top}table.run th{background:#F4F6F8}.cards{margin:8px 0}"
              ".card{margin:2px 0}.card b{display:inline-block;min-width:220px}"
              "ul.org{margin:0 0 0 14px;padding:0}</style>")


def _cell(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value in (None, "") else str(value)


def _rows(run, evaluation, key, table):
    for i, row in enumerate(run.values.get(key) or []):
        computed = evaluation["tables"].get(key, [])
        computed = computed[i] if i < len(computed) else {}
        yield [((computed.get(c["key"]) or {}).get("text", "") if c.get("type") == "computed"
                else _cell(row.get(c["key"]))) for c in table["columns"]]


def _org_html(run, view) -> str:
    rows = run.values.get(view["table"]) or []
    names = {(r.get(view["name"]) or "").strip(): r for r in rows if r.get(view["name"])}

    def children(parent):
        return [r for r in rows if (r.get(view["parent"]) or "").strip() == parent
                and (r.get(view["name"]) or "").strip()]

    roots = [r for r in rows if (r.get(view["name"]) or "").strip()
             and (r.get(view["parent"]) or "").strip() not in names]

    def branch(row, depth=0):
        if depth > 12:
            return ""
        name = (row.get(view["name"]) or "").strip()
        who = (row.get(view["person"]) or "").strip() or "Open"
        kids = "".join(branch(c, depth + 1) for c in children(name))
        return f"<li><b>{escape(name)}</b>: {escape(who)}" + (
            f"<ul class='org'>{kids}</ul>" if kids else "") + "</li>"

    return "<h2>The chart</h2><ul class='org'>" + "".join(branch(r) for r in roots) + "</ul>"


def body_html(run, evaluation=None) -> str:
    evaluation = evaluation or D.evaluate(run.definition, run.values)
    out = [_TABLE_CSS, f"<p class='intro'>{escape(run.tool_name)}, {escape(run.company.name)}, "
                       f"{run.run_date:%B %-d, %Y}.</p>"]
    if evaluation["results"]:
        out.append("<h2>Results</h2><div class='cards'>")
        out += [f"<div class='card'><b>{escape(r['label'])}</b> {escape(r['text'])}</div>"
                for r in evaluation["results"]]
        out.append("</div>")
    for view in run.definition.get("views") or []:
        if view.get("type") == "org_chart":
            out.append(_org_html(run, view))
    for section in run.definition.get("sections") or []:
        out.append(f"<h2>{escape(section['title'])}</h2>")
        for field in section.get("fields") or []:
            key = field["key"]
            if field.get("type") == "table":
                head = "".join(f"<th>{escape(c['label'])}</th>" for c in field["columns"])
                body = "".join("<tr>" + "".join(f"<td>{escape(v).replace(chr(10), '<br>')}</td>"
                                                for v in row) + "</tr>"
                               for row in _rows(run, evaluation, key, field))
                out.append(f"<p><b>{escape(field['label'])}</b></p>"
                           f"<table class='run'><tr>{head}</tr>{body}</table>")
            elif field.get("type") == "computed":
                out.append(f"<p><b>{escape(field['label'])}:</b> "
                           f"{escape(evaluation['computed'][key]['text'])}</p>")
            else:
                value = _cell(run.values.get(key))
                if value:
                    out.append(f"<p><b>{escape(field['label'])}:</b> {escape(value)}</p>")
    return "\n".join(out)


def pdf(run, actor) -> bytes:
    from apps.esign import pdf as letterhead

    return letterhead._render(run.company, prepared_by=letterhead._name_of(actor),
                              day=run.run_date, title=run.name, body=body_html(run))


def _docx_head(document, run, title):
    from apps.crm.services.email_layout import branding

    brand = branding(run.company.tenant)
    header = document.sections[0].header.paragraphs[0]
    header.text = (brand.display_name or brand.practice_name or "") + \
        f"  ·  {run.company.name}  ·  {run.run_date:%B %-d, %Y}"
    document.add_heading(title, level=0)


def _new_document():
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    return document


def docx(run) -> bytes:
    evaluation = D.evaluate(run.definition, run.values)
    document = _new_document()
    _docx_head(document, run, run.name)
    document.add_paragraph(f"{run.tool_name}, {run.company.name}, {run.run_date:%B %-d, %Y}.")
    if evaluation["results"]:
        document.add_heading("Results", level=1)
        for r in evaluation["results"]:
            document.add_paragraph(f"{r['label']}: {r['text']}")
    for section in run.definition.get("sections") or []:
        document.add_heading(section["title"], level=1)
        for field in section.get("fields") or []:
            key = field["key"]
            if field.get("type") == "table":
                document.add_paragraph(field["label"]).runs[0].bold = True
                rows = list(_rows(run, evaluation, key, field))
                table = document.add_table(rows=1 + len(rows), cols=len(field["columns"]))
                table.style = "Table Grid"
                for c, column in enumerate(field["columns"]):
                    table.rows[0].cells[c].text = column["label"]
                for r, row in enumerate(rows, start=1):
                    for c, value in enumerate(row):
                        table.rows[r].cells[c].text = value
            elif field.get("type") == "computed":
                document.add_paragraph(f"{field['label']}: "
                                       f"{evaluation['computed'][key]['text']}")
            else:
                value = _cell(run.values.get(key))
                if value:
                    document.add_paragraph(f"{field['label']}: {value}")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def agenda_docx(run) -> bytes:
    """One page per meeting: when, who, and the agenda with its clock times."""
    document = _new_document()
    _docx_head(document, run, f"Agendas: {run.name}")
    for i, event in enumerate(events_of(run)):
        if i:
            document.add_page_break()
        document.add_heading(event["name"], level=1)
        document.add_paragraph(f"{event['cadence']}, {event['day']} at {event['time']}, "
                               f"{event['minutes']} minutes. First on {event['first']}.")
        if event["attendees"]:
            document.add_paragraph("Who attends: " + ", ".join(event["attendees"]))
        for line in event["agenda"] or ["(No agenda sections yet.)"]:
            document.add_paragraph(line, style="List Bullet")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def filename(run, ext) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", run.name).strip("-") or "run"
    return f"{stem}-{timezone.localdate():%Y%m%d}.{ext}"
