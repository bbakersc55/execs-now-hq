"""The Payroll list as a spreadsheet (decision 8): one sheet of people and
the amount each earned for a closed period, a second of the readings and
tiers it was worked out from, so whoever runs payroll keys it in from either.

Written with the standard library: an .xlsx is a zip of a few XML files, and
two plain sheets of text and numbers need nothing more.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

PAYROLL_HEADER = ["Person", "Plan", "Period", "Full-period amount", "Days on the plan",
                  "Amount earned"]
DETAIL_HEADER = ["Person", "Plan", "Period", "Component", "Weight %", "Readings",
                 "Value", "Target", "Expected by the close", "Achievement %", "Tiers",
                 "Share %", "Earned"]


def _col(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell(ref, value) -> str:
    if value is None or value == "":
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _sheet(rows) -> str:
    body = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{_col(c)}{r}", v) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>')


def workbook(sheets) -> bytes:
    """[(name, rows)] as .xlsx bytes."""
    names = [escape(n[:31]) for n, _ in sheets]
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                      'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, len(sheets) + 1))
            + "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>" + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>'
                                 for i, n in enumerate(names, start=1))
            + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
                      'officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
            + "</Relationships>"),
    }
    for i, (_, rows) in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{i}.xml"] = _sheet(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buffer.getvalue()


def _tiers_text(component, straight, cap) -> str:
    if straight:
        return f"Straight line, capped at {cap:g}%"
    return "; ".join(f"from {t['from']:g}%: {t['share']:g}%" for t in component["tiers"])


def rows_for(plans_with_rows) -> list:
    """[(plan_head, [frozen rows])] as the two sheets."""
    payroll, detail = [PAYROLL_HEADER], [DETAIL_HEADER]
    for head, rows in plans_with_rows:
        for row in rows:
            payroll.append([row["name"], head["name"], head["period_label"],
                            row.get("full_amount"), row.get("days_on"), row["earned"]])
            for c in row.get("components", []):
                detail.append([
                    row["name"], head["name"], head["period_label"], c["name"], c["weight"],
                    ", ".join(f"{r['label']}: {r['value']:g}" for r in c.get("readings", [])),
                    c.get("value"), c.get("target"), c.get("expected"), c.get("achievement"),
                    _tiers_text(c, head["straight_line"], head["cap_pct"]), c.get("share"),
                    c.get("earned")])
    return [("Payroll", payroll), ("Readings and tiers", detail)]
