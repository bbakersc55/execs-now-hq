"""An SOP on the practice's letterhead (P10): PDF through the e-signature's
letterhead (`apps.esign.pdf`), with the process map drawn inline, and Word,
with the map as a picture. Either the working copy (the practice's) or a
published version's snapshot (what the portal shows)."""

from __future__ import annotations

import io
import re
from html import escape

from django.utils import timezone

from . import flow

_CSS = ("<style>.sop h2{margin:14px 0 6px}.sop ol.steps{padding-left:18px}"
        ".sop ol.steps li{margin:0 0 8px}.sop .role{color:#6D6E71;font-size:10px}"
        ".sop .warn{border-left:3px solid #F58220;background:#FDF3E8;padding:4px 8px;"
        "margin:4px 0;font-size:10px}.sop .map{margin:6px 0 10px;text-align:center}"
        ".sop .map svg{max-width:100%;height:auto}.sop img.step{max-width:60%;"
        "margin:4px 0;border:1px solid #DDE1E6}.sop table{border-collapse:collapse;width:100%;"
        "font-size:10px}.sop td,.sop th{border:1px solid #DDE1E6;padding:3px 5px;"
        "text-align:left;vertical-align:top}</style>")


def record_of(sop, version=None) -> dict:
    from .services import snapshot

    return version.snapshot if version is not None else snapshot(sop)


def _image_data(sop, attachment_id):
    import base64

    from apps.tenancy import storage

    from .models import SopAttachment

    a = SopAttachment.objects.filter(sop=sop, pk=attachment_id,
                                     kind=SopAttachment.Kind.IMAGE).select_related("file").first()
    if a is None:
        return None, None
    try:
        content = storage.read(a.file)
    except storage.StorageError:
        return None, None
    return content, f"data:{a.file.content_type};base64,{base64.b64encode(content).decode()}"


def _p(text) -> str:
    return escape(str(text or "")).replace("\n", "<br>")


def overview_rows(r) -> list[tuple[str, str]]:
    """The overview's facts, as label and value, in order."""
    from .services import review_label

    rows = [("SOP number", r.get("number") or ""),
            ("Effective date", _day(r.get("effective_date"))),
            ("Owner", r.get("owner") or ""),
            ("Review frequency", review_label(r.get("review_months"))),
            ("Next review", _day(r.get("review_date"))),
            ("Category", r.get("category") or "")]
    return [(label, value) for label, value in rows if value]


def _day(value) -> str:
    from datetime import date

    if not value:
        return ""
    try:
        return f"{date.fromisoformat(str(value)[:10]):%B %-d, %Y}"
    except ValueError:
        return str(value)


def body_html(sop, version=None) -> str:
    from .services import layout_of, revisions, training_rows

    r = record_of(sop, version)
    out = [_CSS, "<div class='sop'>"]
    out.append(f"<p class='intro'>{escape(f'Version {version.number}' if version else 'Working copy')}</p>")
    for section in layout_of(sop.tenant_id):
        key, title = section["key"], escape(section["title"])
        if key == "overview":
            rows = overview_rows(r)
            out.append(f"<h2>{title}</h2>" + ("<table>" + "".join(
                f"<tr><th>{escape(a)}</th><td>{escape(b)}</td></tr>" for a, b in rows)
                + "</table>" if rows else "<p class='none'>Not filled in yet.</p>"))
        elif key in ("purpose", "scope", "training", "metrics"):
            field = {"scope": "applies_when"}.get(key, key)
            text = r.get(field) or ""
            extra = ""
            if key == "training":
                assets = training_rows(sop)
                if assets:
                    extra = "<ul>" + "".join(
                        f"<li>{escape(a['label'])}: {escape(a['title'])}</li>" for a in assets) \
                        + "</ul>"
            if key == "metrics" and r.get("kpis"):
                extra = "<p>The numbers it should move:</p><ul>" + "".join(
                    f"<li>{escape(k['name'])}</li>" for k in r["kpis"]) + "</ul>"
            out.append(f"<h2>{title}</h2>"
                       + (f"<p>{_p(text)}</p>" if text else "")
                       + extra + ("" if text or extra else "<p class='none'>None.</p>"))
        elif key == "definitions":
            rows = r.get("definitions") or []
            out.append(f"<h2>{title}</h2>" + ("<table><tr><th>Term</th><th>Definition</th></tr>"
                       + "".join(f"<tr><td>{escape(d['term'])}</td><td>{_p(d.get('definition'))}"
                                 "</td></tr>" for d in rows) + "</table>"
                       if rows else "<p class='none'>None.</p>"))
        elif key == "roles":
            rows = r.get("roles") or []
            out.append(f"<h2>{title}</h2>" + ("<table><tr><th>Role</th><th>Responsibility</th>"
                       "</tr>" + "".join(f"<tr><td>{escape(x['name'])}</td><td>"
                                         f"{_p(x.get('does'))}</td></tr>" for x in rows)
                       + "</table>" if rows else "<p class='none'>None.</p>"))
        elif key == "steps":
            out.append(f"<h2>{title}</h2><ol class='steps'>")
            for step in r.get("steps") or []:
                bits = []
                if step.get("when"):
                    bits.append(f"<div class='when'>{_p(step['when'])}</div>")
                bits.append(_p(step["text"]))
                if step.get("role"):
                    bits.append(f"<div class='role'>{escape(step['role'])}</div>")
                if step.get("warning"):
                    bits.append(f"<div class='warn'>{escape(step['warning'])}</div>")
                for image in step.get("images") or []:
                    _, uri = _image_data(sop, image)
                    if uri:
                        bits.append(f"<img class='step' src='{uri}'>")
                out.append(f"<li>{''.join(bits)}</li>")
            out.append("</ol>")
        elif key == "flowchart":
            drawn = ""
            if r.get("process_map"):
                try:
                    drawn = flow.svg(r["process_map"], title=section["title"])
                except flow.FlowError:
                    drawn = ""
            out.append(f"<h2>{title}</h2>" + (f"<div class='map'>{drawn}</div>" if drawn
                                              else "<p class='none'>No flowchart yet.</p>"))
        elif key == "related":
            rows = r.get("related") or []
            out.append(f"<h2>{title}</h2>" + ("<ul>" + "".join(
                f"<li>{escape(x['title'])}{_related_note(x)}</li>" for x in rows) + "</ul>"
                if rows else "<p class='none'>None.</p>"))
        elif key == "revisions":
            rows = revisions(sop, up_to=version.number if version else None)
            out.append(f"<h2>{title}</h2>" + ("<table><tr><th>Date</th><th>Version</th>"
                       "<th>Description of change</th><th>Author</th></tr>" + "".join(
                           f"<tr><td>{escape(_day(x['date']))}</td><td>{x['version']}</td>"
                           f"<td>{_p(x['change'])}</td><td>{escape(x['author'])}</td></tr>"
                           for x in rows) + "</table>"
                       if rows else "<p class='none'>Not published yet.</p>"))
        elif key == "custom":
            body = next((s.get("body") for s in r.get("sections") or []
                         if s.get("title") == section["title"]), "")
            if body:
                out.append(f"<h2>{title}</h2><p>{_p(body)}</p>")
    out.append("</div>")
    return "\n".join(out)


def _related_note(x) -> str:
    if x.get("kind") == "sop":
        return f" <span class='role'>(SOP{' ' + escape(x['number']) if x.get('number') else ''})</span>"
    if x.get("kind") == "document":
        return " <span class='role'>(a document in Execs NOW HQ)</span>"
    if x.get("url"):
        return f" <span class='role'>{escape(x['url'])}</span>"
    return ""


def pdf(sop, actor, version=None) -> bytes:
    from apps.esign import pdf as letterhead

    r = record_of(sop, version)
    day = (version.published_at if version else timezone.now()).date()
    return letterhead._render(sop.company, prepared_by=letterhead._name_of(actor),
                              day=day, title=r["title"], body=body_html(sop, version))


def docx(sop, version=None) -> bytes:
    from docx import Document
    from docx.shared import Inches, Pt

    from apps.crm.services.email_layout import branding

    r = record_of(sop, version)
    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    brand = branding(sop.company.tenant)
    day = (version.published_at if version else timezone.now()).date()
    document.sections[0].header.paragraphs[0].text = \
        (brand.display_name or brand.practice_name or "") + \
        f"  ·  {sop.company.name}  ·  {day:%B %-d, %Y}"
    document.add_heading(r["title"], level=0)
    document.add_paragraph(f"Version {version.number}" if version else "Working copy")
    from .services import layout_of, revisions, training_rows

    def table(head, rows):
        t = document.add_table(rows=1 + len(rows), cols=len(head))
        t.style = "Table Grid"
        for j, h in enumerate(head):
            t.rows[0].cells[j].text = h
        for i, row in enumerate(rows, start=1):
            for j, value in enumerate(row):
                t.rows[i].cells[j].text = str(value or "")

    def none(text="None."):
        document.add_paragraph(text).italic = True

    for section in layout_of(sop.tenant_id):
        key, title = section["key"], section["title"]
        if key == "custom":
            body = next((x.get("body") for x in r.get("sections") or []
                         if x.get("title") == title), "")
            if body:
                document.add_heading(title, level=1)
                document.add_paragraph(body)
            continue
        document.add_heading(title, level=1)
        if key == "overview":
            rows = overview_rows(r)
            table(["", ""], rows) if rows else none("Not filled in yet.")
        elif key in ("purpose", "scope", "training", "metrics"):
            text = r.get({"scope": "applies_when"}.get(key, key)) or ""
            if text:
                document.add_paragraph(text)
            extra = []
            if key == "training":
                extra = [f"{a['label']}: {a['title']}" for a in training_rows(sop)]
            if key == "metrics":
                extra = [k["name"] for k in r.get("kpis") or []]
            for line in extra:
                document.add_paragraph(line, style="List Bullet")
            if not text and not extra:
                none()
        elif key == "definitions":
            rows = [(d["term"], d.get("definition", "")) for d in r.get("definitions") or []]
            table(["Term", "Definition"], rows) if rows else none()
        elif key == "roles":
            rows = [(x["name"], x.get("does", "")) for x in r.get("roles") or []]
            table(["Role", "Responsibility"], rows) if rows else none()
        elif key == "steps":
            for step in r.get("steps") or []:
                if step.get("when"):
                    document.add_paragraph(step["when"]).runs[0].bold = True
                paragraph = document.add_paragraph(step["text"], style="List Number")
                if step.get("role"):
                    paragraph.add_run(f"  ({step['role']})").italic = True
                if step.get("warning"):
                    document.add_paragraph(f"Watch out: {step['warning']}")
                for image in step.get("images") or []:
                    content, _ = _image_data(sop, image)
                    if content:
                        try:
                            document.add_picture(io.BytesIO(content), width=Inches(3.5))
                        except Exception:  # noqa: BLE001  (a picture Word can't take is left out)
                            pass
        elif key == "flowchart":
            drawn = False
            if r.get("process_map"):
                try:
                    document.add_picture(io.BytesIO(flow.png(r["process_map"])), width=Inches(6))
                    drawn = True
                except flow.FlowError:
                    pass
            if not drawn:
                none("No flowchart yet.")
        elif key == "related":
            rows = r.get("related") or []
            for x in rows:
                document.add_paragraph(x["title"] + (f" ({x['url']})" if x.get("url") else ""),
                                       style="List Bullet")
            if not rows:
                none()
        elif key == "revisions":
            rows = [(_day(x["date"]), x["version"], x["change"], x["author"])
                    for x in revisions(sop, up_to=version.number if version else None)]
            table(["Date", "Version", "Description of change", "Author"], rows) if rows \
                else none("Not published yet.")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def filename(sop, ext, version=None) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", sop.title).strip("-") or "SOP"
    suffix = f"-v{version.number}" if version else ""
    return f"{stem}{suffix}-{timezone.localdate():%Y%m%d}.{ext}"
