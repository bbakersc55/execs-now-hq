"""The goal narrative — FR-4B.31 to FR-4B.36, review queue R9a.

**One living narrative per goal** (ruling B). The report has no period and
neither does its prose: a client reads the current account of the goal,
redrafted as the goal moves. **Every acceptance appends a dated snapshot**, so
what the client reads is replaced and what the client was *told* is not.

The faithfulness constraint is the digest's, tested the same way (AC-3.5): the
draft may assert nothing that is not in its input. What *is* in its input got
wider on 2026-09-21, on the owner's ruling — the goal's outcome statement, its
resolution history with the reasons written on it, and the source map row's
bottleneck, root cause and fix. **What the goal set out to change is part of
what the goal is**, and a narrative forbidden to refer to it can only describe
motion.

Nothing here is ever auto-published. A draft lands in `proposed_body`; a person
accepts it, and until they do it is absent from the client's response entirely.
"""

from __future__ import annotations

from django.utils import timezone

from apps.crm.models import Task
from apps.notes.models import Note
from apps.work import milestones as milestone_service
from apps.work import value_report
from apps.work.models import (
    GoalNarrative, GoalNarrativeVersion, TaskUpdate,
)

NARRATIVE_PURPOSE = "goal_narrative"

SYSTEM = """\
You are writing the connective narrative for one goal in a fractional \
executive's client value report. The reader is the founder paying for the \
engagement.

Answer one question: is this goal moving, and what does that add up to? Two to \
four sentences, plain English, no headings, no bullet points, no salutation.

You are given ONLY this goal's own material: what it set out to change, the \
outcome the fractional wrote, the measurable with its baseline and every dated \
reading, the milestones, any resolution and the reason written on it, the \
client-facing lines on its task updates, and notes linked to its tasks.

You must not assert any fact, figure, name, date or cause that is not in that \
input. Do not estimate, do not project, and do not describe a trend you were \
given fewer than two readings for. If there are no readings, do not say the \
goal has advanced, is on track, or is nearly met — describe what was done, not \
how far it has got. If there are readings, you may state the distance travelled, \
because it is in front of you.

You may refer to what the goal set out to change — the bottleneck, its root \
cause and the fix — because that is what the goal is. Do not re-litigate it and \
do not add to it.

Never lead with a count of tasks completed. A third of the tasks is not a third \
of an outcome, and the reader will know it.

Reply with the narrative text only."""


def _line(label, value):
    value = (value or "").strip()
    return f"{label}: {value}" if value else ""


def drafting_input(goal) -> str:
    """Everything the draft may draw on, and nothing else. The prompt IS the
    permission boundary here — a fact absent from this string is a fact the
    model cannot faithfully assert."""
    parts = [f"GOAL: {goal.title}"]
    parts.append(_line("Outcome the fractional wrote", goal.outcome_statement))

    # What it set out to change (owner, 2026-09-21).
    row = goal.source_map_row
    if row is not None:
        parts.append("\nWHAT THIS GOAL SET OUT TO CHANGE (from the strategy session)")
        parts.append(_line("Bottleneck", row.bottleneck))
        parts.append(_line("Root cause", row.root_cause))
        parts.append(_line("The fix", row.the_fix))

    measure = value_report.measure_block(goal)
    if measure["kind"]:
        parts.append("\nTHE MEASURE")
        parts.append(_line("Kind", measure["kind"]))
        parts.append(_line("What is measured", goal.measurable))
        parts.append(_line("How we will know", goal.how_we_will_know))
        parts.append(_line("Unit", goal.measurable_unit))
        parts.append(_line("Which way is good", goal.direction))
        if measure["baseline"]["value"] is not None:
            parts.append(f"Baseline: {measure['baseline']['value']} on "
                         f"{measure['baseline']['at'] or 'an unrecorded date'}")
        if measure["target"] is not None:
            parts.append(f"Target: {measure['target']}")
        for point in measure["series"]:
            if point["is_baseline"]:
                continue
            note = f" — {point['note']}" if point["note"] else ""
            parts.append(f"Reading on {point['at']}: {point['value']}{note}")

    stones = milestone_service.for_goal(goal, for_client=False)
    if stones:
        parts.append("\nMILESTONES")
        today = timezone.localdate()
        for stone in stones:
            occurred = milestone_service.occurred_on(stone)
            when = occurred.isoformat() if occurred else (
                f"due {stone.due_date.isoformat()}" if stone.due_date else "no date")
            parts.append(f"- {stone.title} ({when}, "
                         f"{milestone_service.state_of(stone, today=today)})")

    resolutions = value_report.resolutions_of(goal)
    if resolutions:
        parts.append("\nRESOLUTIONS, newest first — the reason is the fractional's "
                     "own words and the client has read it")
        for row in resolutions:
            parts.append(f"- {row.get_resolution_display()} on "
                         f"{row.resolved_at.date().isoformat()}: {row.reason}")

    task_ids = list(Task.all_objects.filter(
        tenant_id=goal.tenant_id, deleted_at__isnull=True,
    ).filter(goal_id=goal.pk).values_list("pk", flat=True))
    task_ids += list(Task.all_objects.filter(
        tenant_id=goal.tenant_id, deleted_at__isnull=True, project__goal_id=goal.pk,
    ).values_list("pk", flat=True))

    lines = list(TaskUpdate.all_objects.filter(
        tenant_id=goal.tenant_id, task_id__in=task_ids,
    ).exclude(client_facing_line="").order_by("created_at")
        .values_list("created_at", "client_facing_line"))
    if lines:
        parts.append("\nWHAT THE FRACTIONAL SAID THIS MEANT FOR THE CLIENT")
        for at, line in lines:
            parts.append(f"- {at.date().isoformat()}: {line}")

    notes = list(Note.all_objects.filter(
        tenant_id=goal.tenant_id, task_id__in=task_ids, deleted_at__isnull=True,
        # A PIN-locked note is not narrative material: the PIN screens it from
        # other users of the app, and a draft built on it would walk straight
        # past that (FR-2.11).
        pin_hash__isnull=True,
    ).order_by("created_at").values_list("created_at", "title", "body"))
    if notes:
        parts.append("\nNOTES ON THIS GOAL'S WORK")
        for at, title, body in notes:
            parts.append(f"- {at.date().isoformat()} {title}: {body}".strip())

    return "\n".join(p for p in parts if p)


def draft(goal, *, trigger="button"):
    """Write `proposed_body`. **Never `body`** — accepting is a person's act, and
    this must not overwrite words a person wrote."""
    from apps.tenancy import claude

    narrative, _ = GoalNarrative.objects.get_or_create(
        goal=goal, defaults={"tenant": goal.tenant,
                             "state": GoalNarrative.State.DRAFTING})
    try:
        text, call = claude.complete_with_call(
            tenant=goal.tenant, purpose=NARRATIVE_PURPOSE, system=SYSTEM,
            user_text=drafting_input(goal), target_type="goal", target_id=goal.pk,
            trigger=trigger, max_tokens=1500,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        # The `ai_call` row records what it cost to find out; the goal is
        # untouched and the fractional writes the prose themselves.
        narrative.state = GoalNarrative.State.FAILED
        narrative.save(update_fields=["state", "updated_at"])
        return None
    narrative.proposed_body = (text or "").strip()
    narrative.state = GoalNarrative.State.PROPOSED
    narrative.ai_call = call
    narrative.save(update_fields=["proposed_body", "state", "ai_call", "updated_at"])
    return narrative


def accept(goal, *, body, actor):
    """Publish, and **append a dated snapshot** (ruling B).

    `body` is what the fractional accepted — their edit of the draft, or the
    draft verbatim. The living narrative holds it; the version log keeps it.
    """
    body = (body or "").strip()
    if not body:
        raise ValueError("A narrative cannot be accepted empty.")
    narrative, _ = GoalNarrative.objects.get_or_create(
        goal=goal, defaults={"tenant": goal.tenant})
    now = timezone.now()
    narrative.body = body
    narrative.state = GoalNarrative.State.ACCEPTED
    narrative.accepted_by = actor
    narrative.accepted_at = now
    narrative.save(update_fields=["body", "state", "accepted_by", "accepted_at",
                                  "updated_at"])
    GoalNarrativeVersion.objects.create(
        tenant=goal.tenant, narrative=narrative, goal=goal, body=body,
        accepted_by=actor, accepted_at=now)
    return narrative


def discard(goal):
    """Bin the draft. The accepted text, and every version, are untouched."""
    narrative = GoalNarrative.objects.filter(goal=goal).first()
    if narrative is None:
        return None
    narrative.proposed_body = ""
    narrative.state = (GoalNarrative.State.ACCEPTED if narrative.body
                       else GoalNarrative.State.DISCARDED)
    narrative.save(update_fields=["proposed_body", "state", "updated_at"])
    return narrative


def current_version(goal):
    """The snapshot a PDF exported now would carry (FR-4B.33b)."""
    return GoalNarrativeVersion.objects.filter(goal=goal).first()
