"""The eight Command Centers (P8), as the migration seeds the platform's
catalog and as the code knows each one's content. Operations is available;
People and Technology are next; the rest are coming."""

from __future__ import annotations

from apps.centers.content import operations

PRICE_CENTS = 5000
#: All of a practice's Command Centers together, at most.
CAP_CENTS = 15000
ADDON_PREFIX = "center_"

#: (code, name, short name, discipline, status, description)
CENTERS = [
    ("operations", "Operations Command Center", "Operations", "Operations", "available",
     "A session template in plain words, an operations KPI list, six playbooks, an SOP, a "
     "weekly note and a quarterly review, the recommended feeds and three AI actions."),
    ("people", "People Command Center", "People", "People", "coming",
     "For a fractional CHRO. Next."),
    ("technology", "Technology Command Center", "Technology", "Technology", "coming",
     "For a fractional CTO or CIO. Next."),
    ("finance", "Finance Command Center", "Finance", "Finance", "coming",
     "For a fractional CFO."),
    ("sales", "Sales Command Center", "Sales", "Sales", "coming",
     "For a fractional sales leader."),
    ("marketing", "Marketing Command Center", "Marketing", "Marketing", "coming",
     "For a fractional CMO."),
    ("projects", "Projects Command Center", "Projects", "Projects", "coming",
     "For a fractional project or program lead."),
    ("training", "Training Command Center", "Training", "Training", "coming",
     "For a fractional training and development lead."),
]
CODES = [c[0] for c in CENTERS]
NEXT = ("people", "technology")
NAMES = {c[0]: c[1] for c in CENTERS}
SHORT = {c[0]: c[2] for c in CENTERS}

#: What each available module ships (`apps/centers/content/<code>.py`).
CONTENT = {"operations": operations}


def content(code):
    return CONTENT.get(code)


def addon_code(code: str) -> str:
    return f"{ADDON_PREFIX}{code}"


def shipped_documents() -> dict:
    """original key -> (center code, name, title, body), every module's."""
    return {key: (code, *value) for code, module in CONTENT.items()
            for key, value in module.DOCUMENTS.items()}


def shipped_emails() -> dict:
    return {key: (code, *value) for code, module in CONTENT.items()
            for key, value in module.EMAILS.items()}


def shipped_playbooks() -> dict:
    return {key: (code, *value) for code, module in CONTENT.items()
            for key, value in module.PLAYBOOKS.items()}


def shipped_kpis() -> list:
    return [{**entry, "center": code} for code, module in CONTENT.items()
            for entry in module.KPIS]
