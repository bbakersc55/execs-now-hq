"""An SOP's sections, in order (2026-11-14, docs/p10_sop_studio.md, "The layout").

Every SOP has the same eleven sections, in this order, in the app, the
portal, the PDF and Word:

 1. Overview: the SOP number, effective date, owner, review frequency
 2. Purpose
 3. Scope
 4. Definitions and acronyms
 5. Roles and responsibilities
 6. Procedure steps
 7. Flowchart
 8. Related documents and resources
 9. Training requirements
10. Performance metrics and monitoring
11. Revision history, built from the published versions

They come from the Operations Command Center's SOP template. A practice
edits its own copy of that template (Settings → Documents) to rename or
reorder them:

- A heading names a section by its own name or an older one ("Roles",
  "Steps", "Measures", "When it applies", "Review date" still count).
- **To rename one,** put its standard name in brackets after the new one:
  `# Why we do this (Purpose)` shows "Why we do this".
- **The order** is the copy's when it names all eleven. Until then the
  shipped order holds, with the shipped names.
- Any other heading is a section of its own (free text), kept where the copy
  puts it, or before Revision history while the shipped order holds.
"""

from __future__ import annotations

import re

#: (key, the shipped name, the other names a heading may use)
STANDARD = [
    ("overview", "Overview", ("overview", "review date", "review")),
    ("purpose", "Purpose", ("purpose",)),
    ("scope", "Scope", ("scope", "when it applies")),
    ("definitions", "Definitions and acronyms",
     ("definitions and acronyms", "definitions", "acronyms", "glossary")),
    ("roles", "Roles and responsibilities",
     ("roles and responsibilities", "roles", "responsibilities")),
    ("steps", "Procedure steps", ("procedure steps", "procedure", "steps")),
    ("flowchart", "Flowchart", ("flowchart", "flow chart", "process map")),
    ("related", "Related documents and resources",
     ("related documents and resources", "related documents", "resources")),
    ("training", "Training requirements", ("training requirements", "training")),
    ("metrics", "Performance metrics and monitoring",
     ("performance metrics and monitoring", "performance metrics", "metrics", "measures",
      "monitoring")),
    ("revisions", "Revision history", ("revision history", "revisions", "change history")),
]
KEYS = [k for k, _, _ in STANDARD]
NAME = {k: name for k, name, _ in STANDARD}
_ALIAS = {alias: k for k, _, names in STANDARD for alias in names}
MAX_CUSTOM = 12


def key_of(heading: str) -> tuple[str | None, str]:
    """(the standard section a heading names or None, the title to show)."""
    title = re.sub(r"^\s*\d+[.)]\s*", "", heading or "").strip()
    bracket = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", title)
    if bracket and bracket.group(2).strip().lower() in _ALIAS:
        return _ALIAS[bracket.group(2).strip().lower()], bracket.group(1).strip()[:120]
    return _ALIAS.get(title.lower()), title[:120]


def parse(body: str) -> list[dict]:
    """A template's sections, in its order: [{key, title, hint}], with
    `key` "custom" for a free-text section."""
    out, seen = [], set()
    for block in re.split(r"(?m)^#\s+", body or "")[1:]:
        heading, _, guidance = block.partition("\n")
        key, title = key_of(heading.strip())
        guidance = guidance.strip()
        if re.fullmatch(r"[\d.\s]*", guidance):
            guidance = ""
        if not title:
            continue
        if key is None:
            out.append({"key": "custom", "title": title, "hint": guidance[:500]})
        elif key not in seen:
            seen.add(key)
            out.append({"key": key, "title": title, "hint": guidance[:500]})
    return out


def resolve(body: str) -> list[dict]:
    """The eleven, in order, and the free-text sections: from a complete
    copy as it stands, else the shipped order and names."""
    found = parse(body)
    named = {s["key"]: s for s in found if s["key"] != "custom"}
    custom = [s for s in found if s["key"] == "custom"][:MAX_CUSTOM]
    if set(named) == set(KEYS):
        kept, extra = [], 0
        for s in found:
            if s["key"] != "custom":
                kept.append(s)
            elif extra < MAX_CUSTOM:
                kept.append(s)
                extra += 1
        return kept
    ordered = [{"key": k, "title": NAME[k], "hint": named.get(k, {}).get("hint", "")}
               for k in KEYS]
    return ordered[:-1] + custom + ordered[-1:]
