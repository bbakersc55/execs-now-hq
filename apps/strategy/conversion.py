"""Converting a session into work (FR-4.28–4.31, AC-4.11).

Three things this has to get right:

1. **Nothing is created until the fractional confirms.** `preview` answers "what
   would this make?" and writes nothing; `convert` is the only writer.
2. **The map row's measurable survives the trip.** A row promises a measurable
   and a horizon; a goal that drops them is a goal nobody can answer later. The
   columns exist for this (Phase 4.5, carried back), and conversion **asks for
   the baseline** rather than silently leaving it null: a measurable with no
   starting reading cannot be reported against.
3. **Converting means they are a client.** The contact moves to the sales
   pipeline's `won` stage, which fires the client invariant (FR-1.6a) — the one
   source of truth for who is a client, rather than a second flag set here.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Contact, Pipeline, PipelineStage, StageSemantic
from apps.strategy.models import StrategyMapRow, StrategySession
from apps.strategy.services import SessionError
from apps.work.models import Goal, Project

GOAL = StrategyMapRow.ConvertedTo.GOAL
PROJECT = StrategyMapRow.ConvertedTo.PROJECT
# Not a `ConvertedTo` value, because nothing is converted: "leave it out" is a
# choice made at conversion, and it leaves the map row exactly as it was.
SKIP = "skip"


class ConversionRefused(SessionError):
    """Refused, and — where the refusal is about particular rows — which ones.

    `rows` exists so one press can tell the whole truth. A session with nine
    measurables that each need a baseline used to refuse on the first row it
    met, which is nine presses to learn nine things.
    """

    def __init__(self, message, status=400, rows=()):
        super().__init__(message, status=status)
        self.rows = [str(row) for row in rows]


def accepted_rows(session):
    return list(StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.ACCEPTED
    ).order_by("position", "created_at"))


def resolve_owner(session, owner_text: str):
    """`owner_text` → a Contact, where it resolves unambiguously.

    The owner on a map row is free text because it is usually the client's
    Integrator, who has no login. Matching is deliberately narrow: an exact full
    name, then a unique first name, within the session's own company. Anything
    ambiguous stays as text, because guessing an accountable person is worse
    than leaving the field for the fractional.
    """
    name = (owner_text or "").strip()
    if not name or session.company_id is None:
        return None
    people = list(Contact.objects.filter(company_id=session.company_id))
    full = [c for c in people
            if f"{c.first_name} {c.last_name}".strip().lower() == name.lower()]
    if len(full) == 1:
        return full[0]
    first = [c for c in people if (c.first_name or "").lower() == name.lower()]
    return first[0] if len(first) == 1 else None


def _target_date(row):
    return (timezone.localdate() + timedelta(days=row.horizon)) if row.horizon else None


def preview(session) -> list[dict]:
    """What conversion would make. Writes nothing (AC-4.11)."""
    out = []
    for row in accepted_rows(session):
        owner = resolve_owner(session, row.owner_text)
        out.append({
            "row": str(row.pk),
            "position": row.position,
            "title": row.bottleneck,
            "the_fix": row.the_fix,
            "root_cause": row.root_cause,
            "owner_text": row.owner_text,
            "client_owner_contact": {
                "id": str(owner.pk), "name": f"{owner.first_name} {owner.last_name}".strip()
            } if owner else None,
            "measurable": row.measurable,
            "horizon": row.horizon,
            "target_date": _target_date(row),
            # The default is a Goal: a map row is a destination with a
            # measurable, which is what a goal is. The fractional may say
            # Project per row (FR-4.28).
            "suggested": GOAL,
            "needs_baseline": bool(row.measurable),
        })
    return out


def _description(row):
    parts = []
    if row.root_cause:
        parts.append(f"Root cause: {row.root_cause}")
    if row.the_fix:
        parts.append(f"The fix: {row.the_fix}")
    return "\n\n".join(parts)


def _won_stage(tenant):
    return (PipelineStage.all_objects.filter(
        tenant=tenant, semantic=StageSemantic.WON, pipeline__kind=Pipeline.Kind.SALES,
    ).order_by("position").first())


@transaction.atomic
def convert(session, *, choices, actor=None, role=None):
    """Create the work, back-linked, and make the prospect a client.

    `choices` is `{row_id: {"as": "goal"|"project"|"skip", "baseline_value": ..,
    "baseline_at": .., "target_value": .., "measurable_unit": ..,
    "direction": .., "baseline_unknown": bool}}`.

    A goal carrying a measurable must come with either a baseline or an explicit
    "not measured yet" — the prompt is enforced here, not only drawn on a screen.

    Every row is checked **before** anything is written, so one press names every
    row that is not ready rather than the first one.
    """
    if session.state == StrategySession.State.CONVERTED:
        raise ConversionRefused("This session has already been converted.", status=409)
    rows = accepted_rows(session)
    if not rows:
        raise ConversionRefused(
            "There is nothing to convert: no map row has been accepted.", status=409)

    plan, refusals = [], []
    for row in rows:
        choice = dict(choices.get(str(row.pk)) or {})
        as_what = choice.get("as") or GOAL
        if as_what == SKIP:
            continue
        if as_what not in (GOAL, PROJECT):
            refusals.append((row, f"{as_what!r} is not 'goal', 'project' or 'skip'."))
            continue
        if as_what == GOAL:
            problem = _goal_problem(row, choice)
            if problem is not None:
                refusals.append((row, problem))
                continue
        plan.append((row, as_what, choice))

    if refusals:
        raise ConversionRefused(_refusal_sentence(refusals),
                                rows=[row.pk for row, _ in refusals])
    if not plan:
        raise ConversionRefused(
            "Every row is left out, so there is nothing to create. Choose a goal or "
            "a project for at least one of them.", status=400)

    made = []
    for row, as_what, choice in plan:
        owner_contact = resolve_owner(session, row.owner_text)
        common = {
            "tenant": session.tenant,
            "title": row.bottleneck,
            "description": _description(row),
            "client_company": session.company,
            "owner": session.owner or actor,
            "client_owner_contact": owner_contact,
            "target_date": _target_date(row),
            "source_map_row": row,
        }
        if as_what == PROJECT:
            made.append(("project", Project.objects.create(**common)))
        else:
            baseline = _number(choice.get("baseline_value"))
            made.append(("goal", Goal.objects.create(
                **common,
                measurable=row.measurable,
                measurable_unit=(choice.get("measurable_unit") or "").strip(),
                baseline_value=baseline,
                baseline_at=choice.get("baseline_at")
                or (timezone.localdate() if baseline is not None else None),
                target_value=_number(choice.get("target_value")),
                direction=(choice.get("direction") or ""),
                horizon_days=row.horizon,
            )))
        row.converted_to = as_what
        row.save(update_fields=["converted_to", "updated_at"])

    # R9 — converting is the moment they became a client, and that fact has one
    # source of truth (FR-1.6a).
    stage = _won_stage(session.tenant)
    if stage is not None:
        from apps.crm.services import pipeline as pipeline_service

        pipeline_service.change_stage(session.contact, stage, actor=actor,
                                      reason="strategy session converted")

    session.state = StrategySession.State.CONVERTED
    session.converted_at = timezone.now()
    session.save(update_fields=["state", "converted_at", "updated_at"])
    return made


def _number(value):
    """A figure, or None. Raises nothing — `_goal_problem` has already refused
    anything that is not a number, in a sentence a person can act on."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError, ValueError):
        return None


def _is_a_number(value) -> bool:
    if value in (None, ""):
        return True
    try:
        Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError, ValueError):
        return False
    return True


def _goal_problem(row, choice) -> str | None:
    """Why this row cannot become a goal yet, in the fractional's words."""
    baseline = choice.get("baseline_value")
    for value, field in ((baseline, "baseline"), (choice.get("target_value"), "target")):
        if not _is_a_number(value):
            # A DecimalField meeting "7 a week" used to be a 500 with no sentence
            # in it. The unit lives in the measurable; this column is the figure.
            return (f'has a {field} that reads "{value}", which is not a number — '
                    f"give the figure on its own, since the unit belongs in the "
                    f"measurable")
    if row.measurable and baseline in (None, "") and not choice.get("baseline_unknown"):
        return ("needs a baseline before the engagement starts, or an explicit "
                '"not measured yet": a measurable with no starting reading cannot be '
                "reported against")
    return None


def _refusal_sentence(refusals) -> str:
    """One sentence for however many rows are not ready.

    Nine rows refused for the same reason say the reason once and name the rows;
    nine refused for two different reasons must not report one reason nine
    times. Either way the card marks each row it names.
    """
    if len(refusals) == 1:
        row, problem = refusals[0]
        return f'"{row.bottleneck}" {problem}.'

    def named(rows):
        shown = ", ".join(f'"{row.bottleneck}"' for row in rows[:3])
        rest = len(rows) - 3
        return shown + (f", and {rest} more below" if rest > 0 else "")

    reasons = {problem for _, problem in refusals}
    if len(reasons) == 1:
        rows = [row for row, _ in refusals]
        return (f"{len(refusals)} rows are not ready to convert — {named(rows)}. "
                f"Each of them {reasons.pop()}.")
    listed = "; ".join(f'"{row.bottleneck}" {problem}'
                       for row, problem in refusals[:3])
    rest = len(refusals) - 3
    return (f"{len(refusals)} rows are not ready to convert: {listed}"
            + (f", and {rest} more below" if rest > 0 else "") + ".")
