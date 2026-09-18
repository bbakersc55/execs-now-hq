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

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Contact, Pipeline, PipelineStage, StageSemantic
from apps.strategy.models import StrategyMapRow, StrategySession
from apps.strategy.services import SessionError
from apps.work.models import Goal, Project

GOAL = StrategyMapRow.ConvertedTo.GOAL
PROJECT = StrategyMapRow.ConvertedTo.PROJECT


class ConversionRefused(SessionError):
    pass


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

    `choices` is `{row_id: {"as": "goal"|"project", "baseline_value": ..,
    "baseline_at": .., "target_value": .., "measurable_unit": ..,
    "direction": .., "baseline_unknown": bool}}`.

    A goal carrying a measurable must come with either a baseline or an explicit
    "not measured yet" — the prompt is enforced here, not only drawn on a screen.
    """
    if session.state == StrategySession.State.CONVERTED:
        raise ConversionRefused("This session has already been converted.", status=409)
    rows = accepted_rows(session)
    if not rows:
        raise ConversionRefused(
            "There is nothing to convert: no map row has been accepted.", status=409)

    made = []
    for row in rows:
        choice = dict(choices.get(str(row.pk)) or {})
        as_what = choice.get("as") or GOAL
        if as_what not in (GOAL, PROJECT):
            raise ConversionRefused(f"{as_what!r} is not 'goal' or 'project'.")
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
            baseline = choice.get("baseline_value")
            if row.measurable and baseline in (None, "") \
                    and not choice.get("baseline_unknown"):
                raise ConversionRefused(
                    f'"{row.measurable}" needs a baseline before the engagement starts, '
                    f"or say it is not measured yet. A measurable with no starting "
                    f"reading cannot be reported against.", status=400)
            made.append(("goal", Goal.objects.create(
                **common,
                measurable=row.measurable,
                measurable_unit=(choice.get("measurable_unit") or "").strip(),
                baseline_value=baseline if baseline not in (None, "") else None,
                baseline_at=choice.get("baseline_at")
                or (timezone.localdate() if baseline not in (None, "") else None),
                target_value=choice.get("target_value") or None,
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
