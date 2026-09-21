"""The same-day PDF (FR-4.23/4.24, AC-4.9).

**Redesigned 2026-09-21 as a sales document, on the owner's instruction**, for a
real prospect session. Two pages, visual over verbose: page one carries the Six
Key Components as a chart, the mirror as a callout, and the Strategy Map as
cards under a 30/60/90 strip that says which fix lands when; page two carries the
two paths side by side, what they value, and the agreed next steps as a checklist
with dates. The Snapshot survives as a strip of chips in the header rather than a
page of question-and-answer — FR-4.23 still gets what it asks for, in the space a
sales document can spare it.

**One exclusion rule narrowed, deliberately** (2026-09-21, and flagged to the
owner rather than done quietly). §9 used to be dropped *as a section* unless the
investment flag was on. The rule now keys on the question's own
`is_financial` flag, so the **two money items — the range and their reaction to
it — are excluded exactly as before**, and §9's logistics (start date, cadence,
who else weighs in, the follow-up call, the proposal due date) become the
checklist the owner asked for. Those are things the prospect agreed to out loud
on the call; sending them back the same day is the point of the document. If the
owner would rather §9 stayed shut entirely, one line here reverts it.

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

from apps.crm.services import email_layout
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
        # The money is out unless the investment flag is on. Keyed on the
        # question's own `is_financial` (ruling 3 puts it on both §9 money
        # items), not on the section, so §9's logistics can be the next-steps
        # checklist while the range and their reaction to it stay shut.
        if question.get("is_financial") and not flags["investment"]:
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
            "key": question["key"],
            "prompt": services.render_prompt(question["prompt"], merge),
            "schema": question["response_schema"],
            "value": answer.value or {},
            "text": _answer_text(answer.value, question["response_schema"]),
            "note": note,
            "is_financial": bool(question.get("is_financial")),
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
            "position": len(rows) + 1,
            "bottleneck": row.bottleneck, "root_cause": row.root_cause,
            "the_fix": row.the_fix, "owner_text": row.owner_text,
            "horizon": row.horizon, "measurable": row.measurable,
            # FR-4.24.2 — the column of hard-won experience, off by default.
            "mechanics_note": row.mechanics_note if flags["mechanics"] else "",
        })

    paths = sections.get(PATHS_SECTION, [])
    scope = sections.get(SCOPE_SECTION, [])
    return {
        "brand": email_layout.branding(session.tenant),
        "session": session,
        "company": session.company.name if session.company else "",
        "prospect": f"{session.contact.first_name} {session.contact.last_name}".strip(),
        "fractional": merge.get("Fractional name", ""),
        "session_date": merge.get("Session date", "") or timezone.localdate().strftime(
            "%-d %B %Y"),
        # FR-4.23 still asks for the Snapshot. It rides in the header as chips
        # rather than a page of Q&A: a prospect already knows their own numbers,
        # and the document's job is what to do about them.
        "snapshot": [{**item, "label": _short(item["prompt"])}
                     for item in sections.get(SNAPSHOT_SECTION, [])],
        "six_key": {"ratings": ratings, "average": six_key["average"],
                    "complete": six_key["complete"], "chart": _chart(ratings)},
        "destination": sections.get(DESTINATION_SECTION, []),
        "mirror_goal": session.mirror_goal,
        "mirror_unlocks": session.mirror_unlocks,
        "map_rows": rows,
        # Which fix lands when, across the top of the map (owner, 2026-09-21).
        "horizons": _horizons(rows),
        "paths": [_path(item) for item in paths],
        # Side by side is two columns, and two is what the seed gives.
        "path_pair": [_path(item) for item in paths[:2]],
        "values": [{"value": (item["value"] or {}).get("value", ""),
                    "why": (item["value"] or {}).get("why", "")}
                   for item in sections.get(VALUES_SECTION, [])],
        "scope": scope,
        # Page two's checklist: everything in §9 that is not money. The two
        # money items are already gone from `scope` unless the flag is on.
        "next_steps": [_step(item) for item in scope if not item["is_financial"]],
        "money": [item for item in scope if item["is_financial"]],
        "flags": flags,
        "show_mechanics": flags["mechanics"],
    }


def _short(prompt: str) -> str:
    """A chip's label: the part before the em dash, which is where the seed puts
    the question and after which it puts the instructions."""
    return prompt.split("—")[0].strip() or prompt


def _chart(ratings):
    """Geometry for the Six Key Components bar chart, computed here rather than
    in the template: a bar's width is arithmetic, and arithmetic in a template
    is where a chart quietly starts lying."""
    if not ratings:
        return None
    row_height = 20
    bar_height = 12
    label_width = 76
    track = 176
    value_gutter = 22        # the number sits after the bar, never inside it
    bars = []
    for index, rating in enumerate(ratings):
        bars.append({
            "label": rating["label"],
            "rating": rating["rating"],
            "is_lowest": rating["is_lowest"],
            "y": index * row_height,
            "width": round(track * rating["rating"] / 10, 1),
            # Where the number goes: past the end of this bar, in dark text.
            # Reversed out of the bar, a low score has no bar to sit in.
            "value_x": label_width + round(track * rating["rating"] / 10, 1) + 4,
            "text_y": index * row_height + bar_height - 2,
        })
    return {"bars": bars, "width": label_width + track + value_gutter,
            "label_width": label_width, "track": track, "bar_height": bar_height,
            "height": len(ratings) * row_height, "row_height": row_height}


def _horizons(rows):
    """The 30/60/90 strip. A row with no horizon is not invented into one — it
    sits in its own column, because a made-up date on a document a prospect
    keeps is worse than an honest blank."""
    buckets = [
        {"days": 30, "label": "30 days", "rows": []},
        {"days": 60, "label": "60 days", "rows": []},
        {"days": 90, "label": "90 days", "rows": []},
        {"days": None, "label": "Not dated", "rows": []},
    ]
    by_days = {bucket["days"]: bucket for bucket in buckets}
    for row in rows:
        by_days.get(row["horizon"], by_days[None])["rows"].append(row)
    return [bucket for bucket in buckets if bucket["rows"]]


def _path(item):
    """One of the two paths, in the shape the page lays out side by side."""
    value = item["value"] or {}
    prompt = item["prompt"]
    name, _, rest = prompt.partition(":")
    return {
        "name": name.strip(),
        "detail": rest.strip() or prompt,
        "reaction": (value.get("reaction") or "").strip(),
        "risk": (value.get("risk") or "").strip(),
        "leaning": (value.get("leaning") or "").strip(),
    }


def _step(item):
    """One line of the next-steps checklist. `notes` is where the date lives —
    "10/1", "Next Tuesday" — so it is the line, and the prompt is the label."""
    value = item["value"] or {}
    return {
        "label": item["prompt"],
        "agreed": bool(value.get("agreed")),
        "detail": (value.get("notes") or "").strip(),
    }


def render_html(session) -> str:
    """The document, with the practice's logo resolved the way the email layout
    resolves it — one brand system, not a second one for paper."""
    html = render_to_string("strategy/pdf.html", context_for(session))
    html, _ = email_layout.with_logo(html, session.tenant, as_data_uri=True)
    return html


def page_count(session) -> int:
    """How many pages it actually comes to. The brief is two; this is how a test
    holds the design to it rather than trusting the eye."""
    from weasyprint import HTML

    return len(HTML(string=render_html(session)).render().pages)


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
