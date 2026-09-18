"""The same-day PDF (FR-4.23/4.24, AC-4.9).

**Everything private is excluded by default.** The five toggles all start false
on every session, and each one turned on is a deliberate act that puts something
the fractional wrote in front of the prospect:

| flag | what it lets through |
|---|---|
| `fractional_notes` | the private note beside a Snapshot or other answer |
| `diagnostic_observations` | the private note beside a diagnostic answer |
| `alignment_observation` | §3 item 4 — the question never asked aloud |
| `mechanics` | "notes / mechanics from experience" on a map row |
| `investment` | §9 in its entirety, money and all |

The exclusion is done **when the document's content is built**, not with CSS or
a print rule: content that is not in the context cannot leak into the file, and
a text search of the bytes is what AC-4.9 checks.
"""

from __future__ import annotations

from django.template.loader import render_to_string
from django.utils import timezone

from apps.strategy import services
from apps.strategy.models import PDF_FLAG_KEYS, StrategyMapRow

PDF_PURPOSE = "strategy_pdf"
PDF_PREFIX = "strategy"

SNAPSHOT_SECTION = "snapshot"
SIX_KEY_SECTION = "six_key_components"
DESTINATION_SECTION = "where_they_want_to_go"
DIAGNOSTIC_SECTION = "diagnostic"
VALUES_SECTION = "what_they_value"
PATHS_SECTION = "two_paths"
SCOPE_SECTION = "scope_agreement"


def flags_of(session) -> dict:
    stored = session.pdf_include_flags or {}
    return {key: bool(stored.get(key, False)) for key in PDF_FLAG_KEYS}


def _answer_text(value, schema) -> str:
    value = value or {}
    if schema == "free_text":
        return (value.get("text") or "").strip()
    if schema == "value_pair":
        return (value.get("value") or "").strip()
    if schema == "agreed_note":
        return (value.get("notes") or "").strip()
    return ""


def context_for(session) -> dict:
    """Everything the document may show, already filtered.

    Built section by section from the session's own snapshot, so a session run
    on an older template renders as it was run.
    """
    flags = flags_of(session)
    answers = services.answers_of(session)
    merge = services.merge_context(session)
    sections: dict = {}
    for section, question in services.questions_in(session.template_snapshot):
        code = section["code"]
        answer = answers.get(question["key"])
        if answer is None:
            continue
        # §9 is out entirely unless the investment flag is on (FR-4.24.5).
        if code == SCOPE_SECTION and not flags["investment"]:
            continue
        # The question never asked aloud (FR-4.17).
        if question.get("is_fractional_observation") and not flags["alignment_observation"]:
            continue
        note = (answer.fractional_note or "").strip()
        if note and code == DIAGNOSTIC_SECTION and not flags["diagnostic_observations"]:
            note = ""
        elif note and code != DIAGNOSTIC_SECTION and not flags["fractional_notes"]:
            note = ""
        sections.setdefault(code, []).append({
            "prompt": services.render_prompt(question["prompt"], merge),
            "schema": question["response_schema"],
            "value": answer.value or {},
            "text": _answer_text(answer.value, question["response_schema"]),
            "note": note,
        })

    six_key = services.six_key_components(session)
    ratings = []
    for item in sections.get(SIX_KEY_SECTION, []):
        rating = (item["value"] or {}).get("rating")
        if isinstance(rating, int):
            ratings.append({"label": item["prompt"], "rating": rating,
                            "comment": (item["value"].get("comment") or "").strip(),
                            "percent": rating * 10,
                            "is_lowest": False})
    if six_key["complete"] and ratings:
        floor = min(r["rating"] for r in ratings)
        for rating in ratings:
            rating["is_lowest"] = rating["rating"] == floor

    rows = []
    for row in (StrategyMapRow.objects.filter(session=session,
                                              state=StrategyMapRow.State.ACCEPTED)
                .order_by("position", "created_at")):
        rows.append({
            "position": row.position + 1,
            "bottleneck": row.bottleneck, "root_cause": row.root_cause,
            "the_fix": row.the_fix, "owner_text": row.owner_text,
            "horizon": row.horizon, "measurable": row.measurable,
            # FR-4.24.2 — the column of hard-won experience, off by default.
            "mechanics_note": row.mechanics_note if flags["mechanics"] else "",
        })

    return {
        "session": session,
        "company": session.company.name if session.company else "",
        "prospect": f"{session.contact.first_name} {session.contact.last_name}".strip(),
        "fractional": merge.get("Fractional name", ""),
        "session_date": merge.get("Session date", "") or timezone.localdate().strftime(
            "%-d %B %Y"),
        "snapshot": sections.get(SNAPSHOT_SECTION, []),
        "six_key": {"ratings": ratings, "average": six_key["average"],
                    "complete": six_key["complete"]},
        "destination": sections.get(DESTINATION_SECTION, []),
        "mirror_goal": session.mirror_goal,
        "mirror_unlocks": session.mirror_unlocks,
        "map_rows": rows,
        "paths": sections.get(PATHS_SECTION, []),
        "values": [{"value": (item["value"] or {}).get("value", ""),
                    "why": (item["value"] or {}).get("why", "")}
                   for item in sections.get(VALUES_SECTION, [])],
        "scope": sections.get(SCOPE_SECTION, []),
        "flags": flags,
        "show_mechanics": flags["mechanics"],
    }


def render_html(session) -> str:
    return render_to_string("strategy/pdf.html", context_for(session))


def render_pdf(session) -> bytes:
    """The bytes. Nothing is stored here — generating is not sending."""
    from weasyprint import HTML

    return HTML(string=render_html(session)).write_pdf()


def store_pdf(session):
    """Generate and keep it, so what was emailed is what can be re-read later."""
    from apps.tenancy import storage

    content = render_pdf(session)
    name = f"strategy-session-{timezone.localdate().isoformat()}.pdf"
    stored = storage.save(
        tenant=session.tenant, content=content,
        object_key=storage.object_key(PDF_PREFIX, name),
        purpose=PDF_PURPOSE, content_type="application/pdf",
    )
    session.pdf_file = stored
    session.save(update_fields=["pdf_file", "updated_at"])
    return stored
