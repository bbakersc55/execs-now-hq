"""Claude drafting for Module 4 — candidate map rows and the mirror.

Two things govern this module, and they pull in the same direction:

1. **Claude proposes; the fractional disposes** (R6). Every row lands as
   `proposed` in a tray. Nothing here writes to the map, sends anything, or
   edits a row a person has already touched.
2. **Exactly two triggers** (FR-4.18a, AC-4.16): an explicit "Draft rows"
   button, and the moment every question in one diagnostic area is answered —
   once per area. Saving an answer never calls Claude. The mirror is its own
   button and is never automatic.

Failure is not fatal anywhere here. A refused or unreachable Claude leaves the
session exactly as it was, with an `ai_call` row recording what it cost to find
out, and the fractional writes the rows themselves.
"""

from __future__ import annotations

import json
import re

from apps.strategy import services
from apps.strategy.models import StrategyMapRow, StrategyPathNote

ROWS_PURPOSE = "strategy_rows"
MIRROR_PURPOSE = "strategy_mirror"
PATHS_PURPOSE = "strategy_path_notes"

DIAGNOSTIC_SECTION = "diagnostic"
DESTINATION_SECTION = "where_they_want_to_go"
PATHS_SECTION = "two_paths"
VALUES_SECTION = "what_they_value"

#: The marker that keeps §8's automatic draft to once a session, kept beside the
#: diagnostic areas in `drafted_areas` rather than in a column of its own.
PATHS_MARKER = "§8"

ROWS_SYSTEM = """\
You are drafting candidate rows for a fractional operations executive's Strategy \
Map, from what a prospect said in a diagnostic conversation.

A row has: bottleneck, root cause, the fix, an owner, a horizon of 30, 60 or 90 \
days, and a measurable.

You are given ONLY the questions asked and the answers captured — what they \
said, who or what causes it, and what they have already tried. You must not \
assert any fact, figure, name, date or cause that is not in that input. Do not \
invent a measurable the conversation does not support, do not estimate numbers, \
and do not name an owner nobody mentioned: leave the owner empty instead. If an \
area is thin, draft fewer rows. Three to five rows is the useful range; fewer is \
better than padded.

The fix is what would actually be done, in the plain words an operator would \
use. The measurable is how they would know it worked — a thing already being \
counted, or an obvious count of what the answer describes. The horizon is your \
read of how long the fix takes, and only 30, 60 or 90.

Reply with JSON only: a list of objects with the keys "bottleneck", \
"root_cause", "the_fix", "owner_text", "horizon", "measurable". No prose around \
it, no markdown fence."""

MIRROR_SYSTEM = """\
You are drafting "the mirror" for a fractional operations executive: two \
sentences read back to a prospect near the start of a strategy session.

- "goal": their stated destination, in THEIR words. Quote and compress what they \
said; do not improve it, do not add ambition they did not state.
- "unlocks": which single bottleneck, if fixed first, most unlocks that goal — \
and one clause saying why, drawn from what they said.

You are given only their answers. Assert nothing that is not in them. Name no \
cause the input does not name. If they never stated a destination, say so in the \
"goal" field rather than inventing one.

Reply with JSON only: an object with the keys "goal" and "unlocks". No prose \
around it, no markdown fence."""


PATHS_SYSTEM = """\
You are drafting the pros and cons of two paths, for the decision page of a \
document a prospect keeps after a strategy session with a fractional operations \
executive.

Path A is that they carry on themselves, using the strategy map they were just \
given. Path B is that they work with {practice} to do it.

Write 2 to 3 pros and 2 to 3 cons for EACH path. Address the reader directly as \
"you" and "your team". One line each, no more than about fifteen words, no \
headings, no bullet characters, no trailing full stops unless the line is a \
sentence.

You are given only this session's own material: what they said in the \
diagnostic, the mirror, what they told us they value, the map rows drafted from \
the conversation, and their reaction, stated risk and leaning on each path. \
**Assert nothing that is not in that input.** No figures they did not give, no \
timelines nobody agreed, no claim about {practice}'s results elsewhere, and no \
promise of an outcome. A con of Path B is a real cost or risk of bringing \
someone in — write it honestly; a document where one column has no downside \
persuades nobody.

Reply with JSON only: {{"a": {{"pros": [], "cons": []}}, "b": {{"pros": [], \
"cons": []}}}}. No prose around it, no markdown fence."""


def _answered(session, section_code):
    """[(rendered prompt, value)] for one section, in order, answered only."""
    answers = services.answers_of(session)
    context = services.merge_context(session)
    out = []
    for section, question in services.questions_in(session.template_snapshot):
        if section["code"] != section_code:
            continue
        answer = answers.get(question["key"])
        if answer is None or not answer.value:
            continue
        out.append((question, services.render_prompt(question["prompt"], context),
                    answer.value))
    return out


def drafting_input(session) -> str:
    """What Claude is given: the destination, and the diagnostic as captured.

    Never the fractional's private notes, never §9, never anything about money —
    a draft is about the work, and the private column is private from the model
    too, not only from the PDF.
    """
    lines = []
    for _question, prompt, value in _answered(session, DESTINATION_SECTION):
        text = (value.get("text") or "").strip()
        if text:
            lines.append(f"{prompt}\n  {text}")
    if lines:
        lines.insert(0, "Where they want to go:")
    diagnostic = _answered(session, DIAGNOSTIC_SECTION)
    if diagnostic:
        lines.append("\nDiagnostic — what is breaking:")
    for question, prompt, value in diagnostic:
        area = question.get("area") or ""
        lines.append(f"[{area}] {prompt}" if area else prompt)
        for field, label in (("said", "they said"), ("cause", "who or what causes it"),
                             ("tried", "what they tried, and why it did not stick")):
            said = (value.get(field) or "").strip()
            if said:
                lines.append(f"  {label}: {said}")
    return "\n".join(lines).strip()


def _json_payload(text: str):
    """Claude was asked for bare JSON. Accept a fence anyway rather than lose a
    good draft to punctuation."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _clean_row(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    bottleneck = (raw.get("bottleneck") or "").strip()
    if not bottleneck:
        return None                      # a row with no bottleneck is not a row
    horizon = raw.get("horizon")
    if isinstance(horizon, str) and horizon.strip().isdigit():
        horizon = int(horizon.strip())
    if horizon not in (30, 60, 90):
        horizon = None                   # never guessed into the column
    return {
        "bottleneck": bottleneck,
        "root_cause": (raw.get("root_cause") or "").strip(),
        "the_fix": (raw.get("the_fix") or "").strip(),
        "owner_text": (raw.get("owner_text") or "").strip()[:200],
        "horizon": horizon,
        "measurable": (raw.get("measurable") or "").strip()[:255],
    }


def draft_map_rows(session, *, trigger="button"):
    """Append candidate rows to the tray. Never touches a row already there.

    Returns the rows created — possibly none, which is a legitimate answer when
    the diagnostic is still thin.
    """
    from apps.tenancy import claude

    user_text = drafting_input(session)
    if not user_text:
        return []
    try:
        text, call = claude.complete_with_call(
            tenant=session.tenant, purpose=ROWS_PURPOSE, system=ROWS_SYSTEM,
            user_text=user_text, target_type="strategy_session", target_id=session.pk,
            trigger=trigger, max_tokens=4000,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return []                        # the ai_call row records what happened
    payload = _json_payload(text)
    if isinstance(payload, dict):
        payload = payload.get("rows")
    if not isinstance(payload, list):
        return []

    existing = {row.bottleneck.strip().lower() for row in
                StrategyMapRow.objects.filter(session=session)}
    position = (StrategyMapRow.objects.filter(session=session).count())
    made = []
    for raw in payload:
        row = _clean_row(raw)
        if row is None or row["bottleneck"].lower() in existing:
            continue                     # a second run does not duplicate the first
        existing.add(row["bottleneck"].lower())
        made.append(StrategyMapRow.objects.create(
            tenant=session.tenant, session=session, position=position,
            state=StrategyMapRow.State.PROPOSED, ai_call=call, **row))
        position += 1
    return made


def draft_mirror(session):
    """Write `proposed_mirror_*`. Never `mirror_*` — accepting is a person's act
    (FR-4.19), and this must not overwrite words a person wrote.
    """
    from apps.tenancy import claude

    user_text = drafting_input(session)
    if not user_text:
        return None
    try:
        text = claude.complete(
            tenant=session.tenant, purpose=MIRROR_PURPOSE, system=MIRROR_SYSTEM,
            user_text=user_text, target_type="strategy_session", target_id=session.pk,
            trigger="button", max_tokens=1000,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return None
    payload = _json_payload(text)
    if not isinstance(payload, dict):
        return None
    session.proposed_mirror_goal = (payload.get("goal") or "").strip()
    session.proposed_mirror_unlocks = (payload.get("unlocks") or "").strip()
    session.save(update_fields=["proposed_mirror_goal", "proposed_mirror_unlocks",
                                "updated_at"])
    return session


# ------------------------------------------------- the second trigger (FR-4.18a)

def completed_areas(session) -> set:
    """Diagnostic areas where every question now has an answer with content."""
    answers = services.answers_of(session)
    by_area: dict = {}
    for section, question in services.questions_in(session.template_snapshot):
        if section["code"] != DIAGNOSTIC_SECTION or not question.get("area"):
            continue
        answer = answers.get(question["key"])
        filled = bool(answer and any((answer.value or {}).get(f, "").strip()
                                     for f in ("said", "cause", "tried")))
        by_area.setdefault(question["area"], []).append(filled)
    return {area for area, flags in by_area.items() if flags and all(flags)}


def draft_for_newly_completed_areas(session):
    """The automatic trigger, fired at most once per area.

    Called after an answer is saved in the live view. It is the only automatic
    path to Claude in this module, and it cannot re-fire: the areas that have
    drafted are recorded on the session.
    """
    already = set(session.drafted_areas or [])
    newly = completed_areas(session) - already
    if not newly:
        return []
    rows = draft_map_rows(session, trigger="auto")
    session.drafted_areas = sorted(already | newly)
    session.save(update_fields=["drafted_areas", "updated_at"])
    return rows


# ------------------------------------------ §8's pros and cons (owner, 2026-09-21)

def path_input(session) -> str:
    """What the pros-and-cons draft is given: this session's own material.

    The reaction and the stated risk **are** input — they are the most useful
    thing said about either path — even though they never reach the prospect's
    PDF. A draft that had to ignore what they said about the paths could only
    write brochure copy.
    """
    lines = [drafting_input(session)]
    if session.mirror_goal or session.mirror_unlocks:
        lines.append("\nThe mirror, as read back to them:")
        if session.mirror_goal:
            lines.append(f"  their goal: {session.mirror_goal}")
        if session.mirror_unlocks:
            lines.append(f"  what unlocks it: {session.mirror_unlocks}")

    values = _answered(session, VALUES_SECTION)
    if values:
        lines.append("\nWhat they told us they value:")
    for _question, _prompt, value in values:
        said = (value.get("value") or "").strip()
        why = (value.get("why") or "").strip()
        if said:
            lines.append(f"  {said}" + (f" — because {why}" if why else ""))

    rows = list(StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.ACCEPTED).order_by("position"))
    if rows:
        lines.append("\nThe map they were just given, in priority order:")
        for index, row in enumerate(rows, start=1):
            horizon = f" ({row.horizon} days)" if row.horizon else ""
            lines.append(f"  {index}. {row.bottleneck}{horizon}")

    paths = _answered(session, PATHS_SECTION)
    if paths:
        lines.append("\nThe two paths, and what they said about each:")
    for _question, prompt, value in paths:
        lines.append(prompt)
        for field, label in (("reaction", "their reaction"),
                             ("risk", "the honest risk, in their words"),
                             ("leaning", "leaning")):
            said = (value.get(field) or "").strip()
            if said:
                lines.append(f"  {label}: {said}")
    return "\n".join(lines).strip()


def paths_captured(session) -> bool:
    """§8 is captured when both paths carry something a person typed."""
    answers = services.answers_of(session)
    keys = [question["key"]
            for section, question in services.questions_in(session.template_snapshot)
            if section["code"] == PATHS_SECTION]
    if not keys:
        return False
    return all(
        any((answers[key].value or {}).get(field, "").strip()
            for field in ("reaction", "risk", "leaning"))
        for key in keys if key in answers
    ) and len([key for key in keys if key in answers]) == len(keys)


def draft_path_notes(session, *, trigger="button"):
    """Append pros and cons to the tray. Never touches one already there.

    Two to three of each, per path. A note lands `proposed`; **only an accepted
    one reaches the prospect's PDF**, which is the same rule the map rows and
    the mirror carry.
    """
    from apps.crm.services import email_layout
    from apps.tenancy import claude

    user_text = path_input(session)
    if not user_text:
        return []
    practice = email_layout.branding(session.tenant).display_name or "the practice"
    try:
        text, call = claude.complete_with_call(
            tenant=session.tenant, purpose=PATHS_PURPOSE,
            system=PATHS_SYSTEM.format(practice=practice),
            user_text=user_text, target_type="strategy_session", target_id=session.pk,
            trigger=trigger, max_tokens=1500,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return []                        # the ai_call row records what happened
    payload = _json_payload(text)
    if not isinstance(payload, dict):
        return []

    existing = {(note.path, note.kind, note.text.strip().lower())
                for note in StrategyPathNote.objects.filter(session=session)}
    made = []
    for path in (StrategyPathNote.Path.A, StrategyPathNote.Path.B):
        side = payload.get(path) or {}
        if not isinstance(side, dict):
            continue
        for kind, key in ((StrategyPathNote.Kind.PRO, "pros"),
                          (StrategyPathNote.Kind.CON, "cons")):
            items = side.get(key)
            if not isinstance(items, list):
                continue
            position = StrategyPathNote.objects.filter(
                session=session, path=path, kind=kind).count()
            # Three is the brief's ceiling; a fourth is padding, and padding on
            # a decision page is what makes a prospect stop reading.
            for raw in items[:3]:
                line = str(raw or "").strip()
                if not line or (path, kind, line.lower()) in existing:
                    continue
                existing.add((path, kind, line.lower()))
                made.append(StrategyPathNote.objects.create(
                    tenant=session.tenant, session=session, path=path, kind=kind,
                    text=line, position=position, ai_call=call,
                    state=StrategyPathNote.State.PROPOSED))
                position += 1
    return made


def draft_paths_once_captured(session):
    """The second trigger, fired at most once a session (owner, 2026-09-21).

    Recorded beside the diagnostic areas in `drafted_areas`, so "has this
    already run?" has one answer in one place.
    """
    already = set(session.drafted_areas or [])
    if PATHS_MARKER in already or not paths_captured(session):
        return []
    notes = draft_path_notes(session, trigger="auto")
    session.drafted_areas = sorted(already | {PATHS_MARKER})
    session.save(update_fields=["drafted_areas", "updated_at"])
    return notes
