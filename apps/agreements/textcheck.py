"""The agreement's words against the PDF they come from.

The owner (2026-11-23): the agreement's words are the PDF's exactly, apart
from an approved change list. This module reads the PDF's text, applies the
change list to it, and compares the result with the template, word by word.
Any difference that isn't on the list is a failure
(tests/test_agreement_text.py).

Matching an entry ignores quote style (straight or curly), spacing and line
breaks (owner, 2026-11-23). An entry that can't be found in the PDF is not
applied, and is listed. Three layout rules are not on the list (Q3, owner's
default): each page's DocuSign line and footer, the list bullets (▪, o) and
the dashed rules are dropped from the PDF's text, and whitespace is ignored.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# Each page's furniture: the DocuSign stamp and the 2014 footer.
FURNITURE = (
    re.compile(r"^\s*DocuSign Envelope ID:"),
    re.compile(r"^\s*V\.1 – May 2014\s+\d+\s+©\s*Park City Ski Chalets,\s*LLC\s*$"),
)
BULLET = re.compile(r"^\s*(▪|o)\s+")
RULE = re.compile(r"(?m)^\s*-{10,}\s*$")
QUOTES = {"'": "['’‘]", "’": "['’‘]", "‘": "['’‘]", '"': '["“”]', "“": '["“”]', "”": '["“”]'}
SAME_QUOTE = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
TOKEN = re.compile(r"\w+|[^\w\s]")


def pdf_text(path) -> str:
    """The PDF's text, page furniture, bullets and rules dropped."""
    import pypdf

    lines = []
    for page in pypdf.PdfReader(str(path)).pages:
        for line in (page.extract_text() or "").splitlines():
            if any(f.search(line) for f in FURNITURE):
                continue
            lines.append(BULLET.sub("", line))
    return RULE.sub("", "\n".join(lines))


def pattern(text: str) -> re.Pattern:
    """`text` as a pattern that ignores quote style and spacing."""
    parts = ["".join(QUOTES.get(c, re.escape(c)) for c in tok) for tok in TOKEN.findall(text)]
    return re.compile(r"\s*".join(parts))


def words(text: str) -> list[str]:
    """Words and punctuation, quotes made one style, spacing dropped."""
    return TOKEN.findall(text.translate(SAME_QUOTE))


@dataclass
class Change:
    """One approved change. `find` is replaced by `to`; with `until`, the run
    from `find` through `until` is. `after` inserts `to` right after it."""
    id: str
    where: str
    to: str
    find: str = ""
    until: str = ""
    after: str = ""
    note: str = ""


@dataclass
class Applied:
    change: Change
    found: int
    before: list[str] = field(default_factory=list)


def apply(text: str, changes) -> tuple[str, list[Applied]]:
    """The PDF's text with every change that can be found applied, and what
    each one matched (0 = not found, so not applied)."""
    report = []
    for ch in changes:
        if ch.after:
            m = pattern(ch.after).search(text)
            if not m:
                report.append(Applied(ch, 0))
                continue
            text = text[:m.end()] + " " + ch.to + " " + text[m.end():]
            report.append(Applied(ch, 1, [m.group(0)]))
            continue
        if not ch.find:                       # a note only (a variable kept at the PDF's value)
            report.append(Applied(ch, -1))
            continue
        if ch.until:
            start = pattern(ch.find).search(text)
            end = pattern(ch.until).search(text, start.end()) if start else None
            if not (start and end):
                report.append(Applied(ch, 0))
                continue
            before = text[start.start():end.end()]
            text = text[:start.start()] + ch.to + text[end.end():]
            report.append(Applied(ch, 1, [before]))
            continue
        found = list(pattern(ch.find).finditer(text))
        if found:
            text = pattern(ch.find).sub(lambda m: ch.to, text)
        report.append(Applied(ch, len(found), [m.group(0) for m in found]))
    return text, report


def compare(expected: str, template: str) -> list[str]:
    """The differences between the PDF-with-changes and the template, as
    lines; empty when they are the same words."""
    a, b = words(expected), words(template)
    out = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        ctx = " ".join(a[max(0, a1 - 6):a1])
        out.append(f"{op} after «…{ctx}»: PDF «{' '.join(a[a1:a2])}» / template «{' '.join(b[b1:b2])}»")
    return out


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def table(report: list[Applied]) -> str:
    """The comparison as a plain table for the report."""
    rows = ["| Entry | Where | Found | Before (PDF) | After (template) |", "|---|---|---|---|---|"]
    for r in report:
        found = {-1: "variable", 0: "NOT FOUND, not applied"}.get(r.found, str(r.found))
        before = _flat(r.before[0]) if r.before else (r.change.find or r.change.after or "")
        if r.change.after:
            before = f"(after) {_flat(r.change.after)}"
        rows.append(f"| {r.change.id} | {r.change.where} | {found} | {before[:160]} | "
                    f"{_flat(r.change.to or r.change.note)[:160]} |")
    return "\n".join(rows)
