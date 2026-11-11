"""A document template as a Word document (P8): its title, then its body,
a line starting "# " as a heading, merge fields left as written ({Company})
for whoever fills it in."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.shared import Pt


def render_docx(template) -> bytes:
    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    document.add_heading(template.title or template.name, level=0)
    for line in (template.body or "").splitlines():
        if line.startswith("# "):
            document.add_heading(line[2:].strip(), level=1)
        else:
            document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def filename(template) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", template.name).strip("-") or "template"
    return f"{stem}.docx"
