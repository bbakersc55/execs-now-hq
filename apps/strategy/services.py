"""Module 4 services — the session, its frozen snapshot, and its answers.

Two rules shape everything here:

1. **A session renders from its own snapshot** (FR-4.5, AC-4.12). `start` takes
   a copy of the whole template at that moment, and every read afterwards —
   prompts, order, `ask_when`, response schemas, the `is_financial` flag —
   comes from that copy. Nothing consults the live template again.
2. **A prompt is shown as written, with merge fields filled or gracefully
   named** (FR-4.9a). A question about `{Integrator}` when there is no
   Integrator reads "no Integrator identified" — never a blank, because a blank
   looks like a mistake and gets skipped in the call.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.utils import timezone

from apps.strategy.models import (
    AskWhen, ResponseSchema, StrategyAnswer, StrategyQuestion, StrategySection,
    StrategySession, StrategyTemplate,
)

PRECALL_TTL = timedelta(days=30)          # FR-4.6
SNAPSHOT_VERSION = 1
MERGE_FIELD = re.compile(r"\{([A-Za-z ]+)\}")


class SessionError(Exception):
    """Refused at the service boundary, with a sentence for the caller."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------- the snapshot

def snapshot_of(template: StrategyTemplate) -> dict:
    """The whole template as it stands, frozen (FR-4.5).

    Deleted questions are left out: they were not asked. Everything a session
    needs to render itself is in here, which is what makes AC-4.12 structural
    rather than a promise.
    """
    sections = (StrategySection.objects.filter(template=template)
                .order_by("position", "created_at"))
    questions = (StrategyQuestion.objects.filter(template=template, deleted_at__isnull=True)
                 .order_by("position", "created_at"))
    by_section: dict = {}
    for question in questions:
        by_section.setdefault(question.section_id, []).append({
            "key": question.key,
            "prompt": question.prompt,
            "ask_when": question.ask_when,
            "must_ask": question.must_ask,
            "area": question.area,
            "response_schema": question.response_schema,
            "is_fractional_observation": question.is_fractional_observation,
            "has_fractional_note": question.has_fractional_note,
            "is_financial": question.is_financial,
            "position": question.position,
        })
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "taken_at": timezone.now().isoformat(),
        "template": {"id": str(template.pk), "name": template.name,
                     "discipline": template.discipline, "version": template.version},
        "sections": [{
            "code": section.code,
            "title": section.title,
            "position": section.position,
            "time_budget_minutes": section.time_budget_minutes,
            "questions": by_section.get(section.pk, []),
        } for section in sections],
    }


def questions_in(snapshot: dict, *, ask_when=None, include_financial=True):
    """Every question in the snapshot, in order, optionally narrowed.

    `include_financial=False` is matrix 10.8 — a VA must not receive the §9
    investment fields **in the API response**, not merely be unable to see them
    on a screen.
    """
    for section in snapshot.get("sections", []):
        for question in section.get("questions", []):
            if ask_when is not None and question["ask_when"] != ask_when:
                continue
            if not include_financial and question.get("is_financial"):
                continue
            yield section, question


def question_in(snapshot: dict, key: str):
    for _section, question in questions_in(snapshot):
        if question["key"] == key:
            return question
    return None


# ----------------------------------------------------------- the merge fields

# FR-4.9a — what a merge field says when the thing it names is not there. Never
# a blank: a blank reads as a bug and gets skipped mid-call.
#
# Two parts, because one is not enough. A merge field usually lands **inside a
# sentence**, often inside a possessive — "{Integrator}'s role" — and a whole
# explanatory clause dropped in there reads as broken English: "no Integrator
# identified's role" (found in the 2026-09-19 dry run). So the substitution is a
# plain noun phrase that survives a possessive, and the explanation is added once
# at the end of the prompt, in brackets, where it reads as a note rather than as
# part of the question.
MISSING_NAME = {
    "Visionary": "the Visionary",
    "Integrator": "the Integrator",
    "Location A": "their first location",
    "Location B": "their second location",
    "Company": "their company",
    "Session date": "the session date",
    "Fractional name": "your name",
}
MISSING_NOTE = {
    "Visionary": "no Visionary identified yet",
    "Integrator": "no Integrator identified yet",
    "Location A": "no locations on file",
    "Location B": "no second location on file",
}


def _contact_name(contact) -> str:
    if contact is None:
        return ""
    return f"{contact.first_name} {contact.last_name}".strip()


def merge_context(session: StrategySession) -> dict:
    """The values behind `{Visionary}`, `{Integrator}` and the rest."""
    company = session.company
    locations = list(company.locations.order_by("position", "created_at")[:2]) \
        if company is not None else []
    owner = session.owner
    return {
        "Visionary": _contact_name(session.visionary_contact),
        "Integrator": _contact_name(session.integrator_contact),
        "Company": company.name if company is not None else "",
        "Location A": locations[0].name if len(locations) > 0 else "",
        "Location B": locations[1].name if len(locations) > 1 else "",
        "Session date": (timezone.localtime(session.scheduled_at).strftime("%-d %B %Y")
                         if session.scheduled_at else ""),
        "Fractional name": ((owner.full_name or "").strip() or owner.email)
        if owner else "",
    }


def render_prompt(prompt: str, context: dict) -> str:
    """Fill the merge fields, naming what is missing rather than leaving a hole.

    A missing field becomes a noun phrase that reads correctly wherever it
    lands — including inside a possessive — and the reason is appended once, in
    brackets: *"…, the Integrator's role (no Integrator identified yet)"*.
    """
    missing: list[str] = []

    def replace(match):
        field = match.group(1)
        value = (context.get(field) or "").strip()
        if value:
            return value
        if field not in missing:
            missing.append(field)
        return MISSING_NAME.get(field, match.group(0))

    text = MERGE_FIELD.sub(replace, prompt)
    notes = [MISSING_NOTE[field] for field in missing if field in MISSING_NOTE]
    return f"{text} ({'; '.join(notes)})" if notes else text


# -------------------------------------------------------------- the session

def start(*, tenant, contact, template=None, owner=None, company=None,
          visionary_contact=None, integrator_contact=None, scheduled_at=None):
    """Create a session and freeze the template into it.

    The snapshot is taken here, once. From this moment the live template can be
    edited, reordered or emptied and this session is untouched.
    """
    if template is None:
        template = (StrategyTemplate.objects.filter(is_default=True).order_by("-version")
                    .first() or StrategyTemplate.objects.order_by("-version").first())
    if template is None:
        raise SessionError("This tenant has no strategy template to run.", status=409)
    company = company if company is not None else contact.company
    # FR-4.9b — the Visionary defaults to the company's primary contact, and to
    # the prospect themselves when there is none. Both are editable.
    if visionary_contact is None:
        visionary_contact = (company.primary_contact if company is not None
                             and company.primary_contact_id else contact)
    return StrategySession.objects.create(
        tenant=tenant, contact=contact, company=company, template=template,
        template_snapshot=snapshot_of(template), owner=owner,
        visionary_contact=visionary_contact, integrator_contact=integrator_contact,
        scheduled_at=scheduled_at,
    )


def _hash_token(raw: str) -> str:
    """Store only the hash; a database read never yields a working credential."""
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_precall_token(session: StrategySession) -> str:
    """A new token invalidates the old one — there is one live link per session."""
    raw = secrets.token_urlsafe(32)
    session.precall_token_hash = _hash_token(raw)
    session.precall_expires_at = timezone.now() + PRECALL_TTL
    session.save(update_fields=["precall_token_hash", "precall_expires_at", "updated_at"])
    return raw


def session_for_precall_token(raw: str):
    """Resolve a public token. Unscoped by necessity — the prospect has no
    tenant bound and no role at all (matrix 10.13) — and narrow by design: it
    yields one session and grants nothing else.
    """
    if not raw:
        return None
    return (StrategySession.all_objects
            .filter(precall_token_hash=_hash_token(raw),
                    precall_expires_at__gt=timezone.now())
            .exclude(precall_token_hash="")
            .select_related("tenant", "contact", "company", "visionary_contact",
                            "integrator_contact", "owner")
            .first())


# --------------------------------------------------------------- the answers

class AnswerInvalid(SessionError):
    pass


def _text(value, field, *, required=True):
    got = value.get(field)
    if got is None or (isinstance(got, str) and not got.strip()):
        if required:
            raise AnswerInvalid(f"{field} is required.")
        return ""
    if not isinstance(got, str):
        raise AnswerInvalid(f"{field} must be text.")
    return got.strip()


def clean_value(response_schema: str, value) -> dict:
    """Validate an answer against the schema **recorded in the snapshot** (FR-4.3).

    Unknown keys are dropped rather than stored: an answer is the shape its
    question declared, and anything else is a client bug or a probe.
    """
    if not isinstance(value, dict):
        raise AnswerInvalid("An answer must be an object.")
    if response_schema == ResponseSchema.FREE_TEXT:
        return {"text": _text(value, "text")}
    if response_schema == ResponseSchema.RATING_1_10:
        rating = value.get("rating")
        # **A rating may arrive without its number** (incident, 2026-09-22).
        # A prospect who answered the six in prose by email has said something
        # worth keeping, and the number is then taken on the call; refusing the
        # sentence until a number exists loses the sentence. An unrated
        # component stays unanswered for the average and the lowest score,
        # which `six_key_components` already decides by looking for an int.
        if rating in (None, ""):
            return {"rating": None, "comment": _text(value, "comment", required=False)}
        if isinstance(rating, bool) or not isinstance(rating, int):
            raise AnswerInvalid("rating must be a whole number from 1 to 10.")
        if not 1 <= rating <= 10:
            raise AnswerInvalid("rating must be from 1 to 10.")
        return {"rating": rating, "comment": _text(value, "comment", required=False)}
    if response_schema == ResponseSchema.DIAGNOSTIC_TRIPLE:
        return {"said": _text(value, "said", required=False),
                "cause": _text(value, "cause", required=False),
                "tried": _text(value, "tried", required=False)}
    if response_schema == ResponseSchema.VALUE_PAIR:
        return {"value": _text(value, "value"),
                "why": _text(value, "why", required=False)}
    if response_schema == ResponseSchema.AGREED_NOTE:
        agreed = value.get("agreed", False)
        if not isinstance(agreed, bool):
            raise AnswerInvalid("agreed must be true or false.")
        return {"agreed": agreed, "notes": _text(value, "notes", required=False)}
    if response_schema == ResponseSchema.PATH_REACTION:
        return {"path": _text(value, "path", required=False),
                "reaction": _text(value, "reaction", required=False),
                "risk": _text(value, "risk", required=False),
                "leaning": _text(value, "leaning", required=False)}
    raise AnswerInvalid(f"Unknown response schema: {response_schema}.")


def save_answer(session, *, question_key, value, answered_by, fractional_note=None):
    """Upsert one answer, validated against the session's own snapshot.

    A key that is not in the snapshot is refused: it was not asked in this
    session, whatever the live template says today.
    """
    question = question_in(session.template_snapshot, question_key)
    if question is None:
        raise AnswerInvalid(f"{question_key} is not a question in this session.", status=404)
    if (answered_by == StrategyAnswer.AnsweredBy.PROSPECT
            and question["ask_when"] != AskWhen.PRECALL):
        # The public form may only write what it was sent to ask.
        raise AnswerInvalid("That question is not on the pre-call form.", status=403)
    if answered_by == StrategyAnswer.AnsweredBy.PROSPECT and fractional_note:
        raise AnswerInvalid("A prospect cannot write a fractional note.", status=403)
    cleaned = clean_value(question["response_schema"], value)
    answer, _created = StrategyAnswer.objects.update_or_create(
        tenant=session.tenant, session=session, question_key=question_key,
        defaults={"value": cleaned, "answered_by": answered_by},
    )
    # A rating always takes the fractional's own note, whatever the template
    # says: the number is a number, and this product's whole argument is that a
    # number without the sentence beside it is worth little. It is also how a
    # prose answer typed in from an email is kept without inventing a score.
    takes_note = question["has_fractional_note"] \
        or question["response_schema"] == ResponseSchema.RATING_1_10
    if fractional_note is not None and takes_note:
        answer.fractional_note = fractional_note
        answer.save(update_fields=["fractional_note", "updated_at"])
    return answer


def answers_of(session) -> dict:
    return {a.question_key: a for a in StrategyAnswer.objects.filter(session=session)}


def must_ask_outstanding(session) -> dict:
    """FR-4.15 — the ★ counter the live view runs on.

    "Answered" means the answer has content in it, not that a row exists: a
    saved-but-empty diagnostic triple has not been asked.
    """
    answers = answers_of(session)
    outstanding, total = [], 0
    for _section, question in questions_in(session.template_snapshot):
        if not question.get("must_ask"):
            continue
        total += 1
        answer = answers.get(question["key"])
        filled = bool(answer and any(
            (v or "").strip() for v in (answer.value or {}).values()
            if isinstance(v, str)))
        if not filled:
            outstanding.append(question["key"])
    return {"outstanding": outstanding, "answered": total - len(outstanding),
            "of": total}


# ------------------------------------------------ the Six Key Components (FR-4.10)

SIX_KEY_SECTION = "six_key_components"


def six_key_components(session) -> dict:
    """The average, and the lowest score — "where to look first".

    Unanswered components are left out of the average rather than counted as
    zero, and the lowest is reported only when every one of them is answered:
    "your lowest is Data" is a lie if three are blank.
    """
    keys = [q["key"] for section, q in questions_in(session.template_snapshot)
            if section["code"] == SIX_KEY_SECTION]
    answers = answers_of(session)
    scored = []
    for key in keys:
        answer = answers.get(key)
        value = (answer.value or {}) if answer else {}
        rating = value.get("rating")
        if isinstance(rating, int):
            scored.append({
                "key": key,
                "rating": rating,
                # The comment beside the number, which is usually where the
                # signal is: "6" says little, "6, because we rewrote it in
                # March and nobody has read it since" says everything.
                "comment": (value.get("comment") or "").strip(),
                "answered_by": answer.answered_by if answer else "",
            })
    complete = len(scored) == len(keys) and bool(keys)
    average = round(sum(row["rating"] for row in scored) / len(scored), 1) \
        if scored else None
    lowest = min(scored, key=lambda row: row["rating"])["key"] if complete else None
    return {
        "scores": scored,
        # Kept for anything reading the old shape; `scores` carries the comment.
        "ratings": {row["key"]: row["rating"] for row in scored},
        "answered": len(scored),
        "of": len(keys),
        "average": average,
        "complete": complete,
        "lowest": lowest,
    }
