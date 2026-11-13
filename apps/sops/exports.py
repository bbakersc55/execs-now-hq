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


def body_html(sop, version=None) -> str:
    r = record_of(sop, version)
    out = [_CSS, "<div class='sop'>"]
    meta = [bit for bit in (
        f"Version {version.number}" if version else "Working copy",
        f"Owner: {r['owner']}" if r.get("owner") else "",
        f"Category: {r['category']}" if r.get("category") else "",
        f"Review by {r['review_date']}" if r.get("review_date") else "") if bit]
    out.append(f"<p class='intro'>{escape(' · '.join(meta))}</p>")
    if r.get("purpose"):
        out.append(f"<h2>Purpose</h2><p>{escape(r['purpose']).replace(chr(10), '<br>')}</p>")
    if r.get("applies_when"):
        out.append("<h2>When it applies</h2>"
                   f"<p>{escape(r['applies_when']).replace(chr(10), '<br>')}</p>")
    if r.get("roles"):
        out.append("<h2>Roles</h2><table><tr><th>Role</th><th>What they do</th></tr>"
                   + "".join(f"<tr><td>{escape(x['name'])}</td><td>{escape(x.get('does', ''))}"
                             "</td></tr>" for x in r["roles"]) + "</table>")
    if r.get("process_map"):
        try:
            drawn = flow.svg(r["process_map"], title="Process map")
            out.append(f"<h2>Process map</h2><div class='map'>{drawn}</div>")
        except flow.FlowError:
            pass
    out.append("<h2>Steps</h2><ol class='steps'>")
    for step in r.get("steps") or []:
        bits = [escape(step["text"]).replace("\n", "<br>")]
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
    if r.get("kpis"):
        out.append("<h2>The numbers it should move</h2><ul>"
                   + "".join(f"<li>{escape(k['name'])}</li>" for k in r["kpis"]) + "</ul>")
    for section in r.get("sections") or []:
        if section.get("body"):
            out.append(f"<h2>{escape(section['title'])}</h2>"
                       f"<p>{escape(section['body']).replace(chr(10), '<br>')}</p>")
    out.append("</div>")
    return "\n".join(out)


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
    meta = [bit for bit in (
        f"Version {version.number}" if version else "Working copy",
        f"Owner: {r['owner']}" if r.get("owner") else "",
        f"Category: {r['category']}" if r.get("category") else "",
        f"Review by {r['review_date']}" if r.get("review_date") else "") if bit]
    document.add_paragraph(" · ".join(meta))
    if r.get("purpose"):
        document.add_heading("Purpose", level=1)
        document.add_paragraph(r["purpose"])
    if r.get("applies_when"):
        document.add_heading("When it applies", level=1)
        document.add_paragraph(r["applies_when"])
    if r.get("roles"):
        document.add_heading("Roles", level=1)
        table = document.add_table(rows=1 + len(r["roles"]), cols=2)
        table.style = "Table Grid"
        table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Role", "What they do"
        for i, role in enumerate(r["roles"], start=1):
            table.rows[i].cells[0].text = role["name"]
            table.rows[i].cells[1].text = role.get("does", "")
    if r.get("process_map"):
        try:
            picture = flow.png(r["process_map"])
            document.add_heading("Process map", level=1)
            document.add_picture(io.BytesIO(picture), width=Inches(6))
        except flow.FlowError:
            pass
    document.add_heading("Steps", level=1)
    for step in r.get("steps") or []:
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
    if r.get("kpis"):
        document.add_heading("The numbers it should move", level=1)
        for k in r["kpis"]:
            document.add_paragraph(k["name"], style="List Bullet")
    for section in r.get("sections") or []:
        if section.get("body"):
            document.add_heading(section["title"], level=1)
            document.add_paragraph(section["body"])
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def filename(sop, ext, version=None) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", sop.title).strip("-") or "SOP"
    suffix = f"-v{version.number}" if version else ""
    return f"{stem}{suffix}-{timezone.localdate():%Y%m%d}.{ext}"
