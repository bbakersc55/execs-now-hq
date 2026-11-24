"""The agreement's words, from its locked template, for every reader: the
owner's phone page and the staff preview (blocks as JSON), the PDF (the same
blocks, as HTML), the comparison with the 2014 PDF (`compare_text`), and the
hash of what the owner signed (`signed_text`).

The template's markup (texts/*.txt):

    %% a comment            = a centred title line      ## a heading
    > / >> an indented paragraph   - / "  - " / "    - " list items, 3 levels
    **bold**   {{variable}}   ::section_30  ::owner_section  ::signatures
    ::page_break   (a blank line ends a paragraph)
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from . import exhibit_a, texts
from .texts import rental_management_changes as changes

INLINE = re.compile(r"\*\*(.+?)\*\*|\{\{(\w+)\}\}")

#: The owner's section (A8), line by line: (label, key) pairs, a heading, or a
#: note. Two headed parts on one page (owner, 2026-11-24).
OWNER_LINES = (
    {"heading": "Unit Information"},
    (("PROPERTY ADDRESS:", "property_address"),),
    (("# Bedrooms:", "bedrooms"), ("# Bathrooms:", "bathrooms"), ("Sq Footage:", "square_feet"),
     ("Sleeps:", "sleeps")),
    {"heading": "Owner Information"},
    (("OWNER OF RECORD:", "owner_of_record"),),
    (("SIGNER’S NAME AND TITLE (if the Owner is a company or trust):", "signer"),),
    (("PHONE:", "phone"), ("EMAIL ADDRESS:", "email")),
    (("MAILING ADDRESS:", "mailing_street"),),
    (("CITY:", "mailing_city"), ("STATE:", "mailing_state"), ("ZIP:", "mailing_zip")),
    (("ALTERNATE PHONE (optional):", "business_phone"),),
    "If only one owner, please list another person we could contact in case of an emergency.",
    (("NAME:", "emergency_name"),),
    (("MAILING ADDRESS:", "emergency_address"),),
    (("PHONE:", "emergency_phone"),),
)
PLACEHOLDER = {
    "property_address": "[property address]",
    "bedrooms": "[bedrooms]", "bathrooms": "[bathrooms]", "square_feet": "[square footage]",
    "sleeps": "[sleeps]",
    "owner_of_record": "[owner of record]", "signer": "[signer name and title]",
    "phone": "[phone]", "email": "[email]", "mailing_street": "[mailing address]",
    "mailing_city": "[city]", "mailing_state": "[state]", "mailing_zip": "[zip]",
    "business_phone": "[alternate phone]", "emergency_name": "[emergency contact name]",
    "emergency_address": "[emergency contact address]",
    "emergency_phone": "[emergency contact phone]",
}
#: Before countersigning, the date line reads as dated on SkyRun's signature.
UNDATED = "on the date of Manager’s signature below"


# ------------------------------------------------------------ parsing

def parse(source: str) -> list[dict]:
    """The template's blocks, before any value is filled in."""
    blocks, para, items = [], [], []

    def end_para():
        if para:
            indent = len(re.match(r"^(>*)", para[0]).group(1))
            text = " ".join(line.lstrip(">").strip() for line in para)
            blocks.append({"type": "para", "indent": indent, "text": text})
            para.clear()

    def end_list():
        if items:
            blocks.append({"type": "list", "items": list(items)})
            items.clear()

    for line in source.splitlines():
        if line.startswith("%%"):
            continue
        if not line.strip():
            end_para()
            end_list()
            continue
        m = re.match(r"^( *)- (.*)$", line)
        if m:
            end_para()
            items.append({"level": len(m.group(1)) // 2 + 1, "text": m.group(2).strip()})
            continue
        if line.startswith("::"):
            end_para()
            end_list()
            blocks.append({"type": line[2:].strip()})
            continue
        if line.startswith("= "):
            end_para()
            blocks.append({"type": "title", "text": line[2:].strip()})
            continue
        if line.startswith("## "):
            end_para()
            blocks.append({"type": "heading", "text": line[3:].strip()})
            continue
        para.append(line)
    end_para()
    end_list()
    return blocks


def spans(text: str, values: dict) -> list[dict]:
    """Text, bold runs and filled-in variables. A variable staff set is a
    `term`: the owner's page and the preview show it highlighted."""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append({"t": "text", "v": text[pos:m.start()]})
        if m.group(1) is not None:
            out.append({"t": "bold", "v": m.group(1)})
        else:
            out.append({"t": "term", "k": m.group(2), "v": values[m.group(2)]})
        pos = m.end()
    if pos < len(text):
        out.append({"t": "text", "v": text[pos:]})
    return out


# ------------------------------------------------------------ values

def number(value) -> str:
    """70 → "70", 72.5 → "72.5", "1500" → "1,500", 1500.5 → "1,500.50"."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if d == d.to_integral_value():
        return f"{int(d):,}"
    return f"{d:,.2f}"


def percent(value) -> str:
    d = Decimal(str(value))
    return f"{d.normalize():f}" if d != d.to_integral_value() else str(int(d))


def one_line(address: dict | None) -> str:
    a = address or {}
    street = ", ".join(x for x in (a.get("street", "").strip(), a.get("unit", "").strip()) if x)
    tail = " ".join(x for x in (a.get("state", "").strip(), a.get("zip", "").strip()) if x)
    return ", ".join(x for x in (street, a.get("city", "").strip(), tail) if x)


def dated(day: date | None) -> str:
    if day is None:
        return UNDATED
    n = day.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"this {n}{suffix} day of {day:%B}, {day.year}"


def section_30(terms: dict) -> list[str]:
    """Section 30's paragraphs: the fee clause when any fee is above $0, then
    the additional items; "None." when both are empty (change A7, clause B)."""
    paras = []
    fees = terms.get("fees") or {}
    lines = []
    for key, period in changes.PERIODS:
        row = fees.get(key) or {}
        if Decimal(str(row.get("fee") or 0)) > 0:
            lines.append(changes.FEE_LINE.format(period=period,
                                                 threshold=number(row.get("threshold") or 0),
                                                 fee=number(row.get("fee"))))
    if lines:
        paras.append(changes.FEE_CLAUSE)
        paras.extend(lines)
    extra = (terms.get("additional_items") or "").strip()
    if extra:
        paras.extend(p.strip() for p in re.split(r"\n\s*\n", extra) if p.strip())
    return paras or ["None."]


def owner_values(details: dict, property_address: dict | None = None) -> dict:
    """The owner's section, as the PDF's lines show it. The property address
    is the opening's, never typed again (owner, 2026-11-24)."""
    d = details or {}
    mailing = d.get("mailing") or {}
    emergency = d.get("emergency") or {}
    person = " ".join(x for x in (d.get("first_name", ""), d.get("last_name", "")) if x).strip()
    entity = d.get("owner_type") == "entity"
    return {
        "property_address": one_line(property_address),
        "bedrooms": str(d.get("bedrooms") or ""), "bathrooms": str(d.get("bathrooms") or ""),
        "square_feet": number(d["square_feet"]) if d.get("square_feet") else "",
        "sleeps": str(d.get("sleeps") or ""),
        "owner_of_record": (d.get("entity_name", "") if entity else person),
        "signer": (f"{person}, {d.get('signer_title', '')}".strip(", ") if entity else ""),
        "phone": d.get("phone", ""), "email": d.get("email", ""),
        "mailing_street": ", ".join(x for x in (mailing.get("street", ""),
                                                mailing.get("street2", "")) if x),
        "mailing_city": mailing.get("city", ""), "mailing_state": mailing.get("state", ""),
        "mailing_zip": mailing.get("zip", ""), "business_phone": d.get("business_phone", ""),
        "emergency_name": emergency.get("name", ""),
        "emergency_address": emergency.get("address", ""),
        "emergency_phone": emergency.get("phone", ""),
    }


def owner_lines(values: dict) -> list:
    out = []
    for line in OWNER_LINES:
        if isinstance(line, str):
            out.append({"note": line})
        elif isinstance(line, dict):
            out.append(dict(line))
        else:
            out.append({"fields": [{"label": label, "key": key, "value": values.get(key, "")}
                                   for label, key in line]})
    return out


# ------------------------------------------------------------ the document

#: Before the owners are named (the staff's first preview).
UNNAMED = [{"name": "[owner name]", "title": ""}]


def owner_name_line(owner: dict) -> str:
    """"Pat Sample" or "Pat Sample, Trustee": under each owner's signature."""
    return ", ".join(x for x in ((owner.get("name") or "").strip(),
                                 (owner.get("title") or "").strip()) if x)


def document(template_key: str, terms: dict, details: dict | None, *,
             agreement_date: date | None = None, owners: list | None = None) -> list[dict]:
    """The agreement as blocks, every value filled in. `owners` are the people
    who sign, in order ({name, title}): one signature block each."""
    tpl = texts.get(template_key)
    details = details or {}
    property_address = details.get("property_address") or terms.get("property_address")
    values = {"agreement_date": dated(agreement_date),
              "property_address": one_line(property_address),
              "owner_percent": percent(terms.get("owner_percent", 70)),
              "manager_percent": percent(terms.get("manager_percent", 30)),
              **exhibit_a.values(details.get("sleeps"))}
    out = []
    for block in parse(tpl.source()):
        kind = block["type"]
        if kind == "para":
            out.append({"type": "para", "indent": block["indent"],
                        "spans": spans(block["text"], values)})
        elif kind == "list":
            out.append({"type": "list", "items": [{"level": i["level"],
                                                   "spans": spans(i["text"], values)}
                                                  for i in block["items"]]})
        elif kind == "section_30":
            out.append({"type": "section_30", "paras": section_30(terms)})
        elif kind == "owner_section":
            out.append({"type": "owner_section",
                        "lines": owner_lines(owner_values(details, property_address))})
        elif kind == "signatures":
            out.append({"type": "signatures", "signer_name": tpl.signer_name,
                        "signer_title": tpl.signer_title,
                        "owners": [{"name": owner_name_line(o)} for o in (owners or UNNAMED)]})
        else:
            out.append(dict(block))
    return out


def signature_words(block: dict) -> str:
    """The signature page's words (A9): SkyRun's block, then one per owner."""
    owners = " ".join(f"OWNER BY: [Owner signature] Signature DATE: [Owner date] "
                      f"NAME: {o['name']}" for o in block.get("owners") or [])
    return ("THE PARTIES HERETO HAVE EXECUTED THIS AGREEMENT. MANAGER SKYRUN PARK CITY "
            "BY: [Manager signature] DATE: [Manager date] "
            f"NAME: {block['signer_name']}, {block['signer_title']} "
            "By signing below, you are indicating that you own all or part of the unit. You "
            "are also indicating that ANY AND ALL additional owners have signed below. "
            f"{owners} (ALL owners of Unit must sign)")


def _words_of(block: dict, placeholders: bool) -> str:
    kind = block["type"]
    if kind in ("title", "heading"):
        return block["text"]
    if kind == "para":
        return "".join(s["v"] for s in block["spans"])
    if kind == "list":
        return " ".join("".join(s["v"] for s in i["spans"]) for i in block["items"])
    if kind == "section_30":
        return "[section 30]" if placeholders else " ".join(block["paras"])
    if kind == "owner_section":
        parts = []
        for line in block["lines"]:
            if "note" in line:
                parts.append(line["note"])
                continue
            if "heading" in line:
                parts.append(line["heading"])
                continue
            for f in line["fields"]:
                value = PLACEHOLDER[f["key"]] if placeholders else f["value"]
                parts.append(f"{f['label']} {value}".strip())
        return " ".join(parts)
    if kind == "signatures":
        return signature_words(block)
    return ""


def compare_text(template_key: str) -> str:
    """The template's words with every variable as its bracketed name, the
    split at its default 70 and 30: the words the change list describes."""
    blocks = document(template_key, {"owner_percent": 70, "manager_percent": 30}, None)
    names = {"agreement_date": "[agreement date]", "property_address": "[property address]",
             **exhibit_a.COMPARE}
    for b in blocks:
        rows = b["spans"] if b["type"] == "para" else \
            [s for i in b["items"] for s in i["spans"]] if b["type"] == "list" else []
        for s in rows:
            if s.get("k") in names:
                s["v"] = names[s["k"]]
    return "\n\n".join(w for w in (_words_of(b, True) for b in blocks) if w)


def signed_text(template_key: str, terms: dict, details: dict, owners: list | None = None) -> str:
    """The words the owners sign, as one text: the date line left as it reads
    before countersigning, so the date is not part of it (owner, 2026-11-23).
    The same words for every owner (owner, 2026-11-24)."""
    blocks = document(template_key, terms, details, agreement_date=None, owners=owners)
    return "\n\n".join(w for w in (_words_of(b, False) for b in blocks) if w)


def signed_sha256(template_key: str, terms: dict, details: dict,
                  owners: list | None = None) -> str:
    return hashlib.sha256(signed_text(template_key, terms, details, owners)
                          .encode("utf-8")).hexdigest()
