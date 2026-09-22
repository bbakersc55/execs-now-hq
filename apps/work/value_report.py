"""The client value report — Module 4B (FR-4B.1 to FR-4B.44).

It answers the one question a founder pays a fractional to have answered: *are
we getting where we said we were going, and is it working?* Anchored on
**goals**, never on a period, because the goal is where the engagement's promise
lives.

Three rules govern everything below, and all three are about not lying:

1. **Nothing is stored that can be read.** The current value is the latest
   measurement, the completion bar is counted from the task tree, the timeline
   is assembled from rows that already exist. A stored rollup drifts the moment
   something changes outside the path that wrote it, and a number on a client's
   screen that disagrees with its own history is worse than no number.
2. **Percent-of-tasks-done is never the headline** (FR-4B.21). A third of the
   tasks is not a third of an outcome, and a client who works that out once
   stops believing every number on the page after it. It is a **product rule**,
   which is why the headline is decided here, once, rather than in a template.
3. **A client is shown only what is theirs and only what is accepted.** The
   narrative draft, the tenant-side nudge, an internal goal, a milestone whose
   task is hidden — each is *absent from the response*, not hidden in the UI.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.crm.models import Task
from apps.work import milestones as milestone_service
from apps.work import permissions as work_perms
from apps.work import status as status_service
from apps.work.models import (
    Goal, GoalMeasurement, GoalNarrative, GoalResolution, Project,
)

#: Below this, a chart is decoration over two points (ruling 9, FR-4B.22).
CHART_MINIMUM_READINGS = 3


# ------------------------------------------------------------------ the measure

def measurements_of(goal):
    """Newest first. Ordering is `-measured_at, -created_at`, so on one date the
    **most recently recorded** reading is current — never the higher one
    (ruling C)."""
    return list(GoalMeasurement.objects.filter(goal=goal).select_related("recorded_by"))


def current_measurement(goal):
    rows = measurements_of(goal)
    return rows[0] if rows else None


def has_dated_baseline(goal) -> bool:
    return goal.baseline_value is not None and goal.baseline_at is not None


def reading_count(goal, rows=None) -> int:
    """Points on the axis. **A dated baseline is one of them** (ruling D) — it
    is a reading, taken at the engagement's start. An undated one is not: a
    point with no date cannot be placed on an axis."""
    rows = measurements_of(goal) if rows is None else rows
    return len(rows) + (1 if has_dated_baseline(goal) else 0)


def series_of(goal, rows=None):
    """Oldest first, baseline included where it is dated — what a chart draws."""
    rows = measurements_of(goal) if rows is None else rows
    points = []
    if has_dated_baseline(goal):
        points.append({"at": goal.baseline_at.isoformat(),
                       "value": str(goal.baseline_value), "is_baseline": True,
                       "note": ""})
    for row in reversed(rows):
        points.append({"at": row.measured_at.isoformat(), "value": str(row.value),
                       "is_baseline": False, "note": row.note})
    return points


def _movement(goal, current):
    """Which way it has gone, said only when the goal declares which way is good
    (FR-4B.7). Never inferred from baseline versus target."""
    if current is None or goal.baseline_value is None or not goal.direction:
        return ""
    delta = Decimal(current.value) - Decimal(goal.baseline_value)
    if delta == 0:
        return "level"
    rising = delta > 0
    good = (goal.direction == Goal.Direction.UP_IS_GOOD)
    return "better" if rising == good else "worse"


def measure_block(goal, *, for_client: bool = False) -> dict:
    rows = measurements_of(goal)
    current = rows[0] if rows else None
    count = reading_count(goal, rows)
    return {
        "kind": goal.measurable_kind or None,
        # FR-4B.6a — *not yet decided* is a different fact from *decided: not
        # measurable*, and only the first one nudges. **The nudge is the
        # practice's**: a client is not shown that nobody has decided yet.
        "kind_is_undecided": goal.kind_is_undecided and not for_client,
        "measurable": goal.measurable,
        "unit": goal.measurable_unit,
        "how_we_will_know": goal.how_we_will_know,
        "direction": goal.direction,
        "baseline": {"value": str(goal.baseline_value) if goal.baseline_value is not None
                     else None,
                     "at": goal.baseline_at.isoformat() if goal.baseline_at else None},
        "current": {"value": str(current.value), "at": current.measured_at.isoformat(),
                    "note": current.note} if current else None,
        "target": str(goal.target_value) if goal.target_value is not None else None,
        "movement": _movement(goal, current),
        "reading_count": count,
        # Ruling 9 — from three up, and below that baseline → current as text.
        "show_chart": count >= CHART_MINIMUM_READINGS,
        "series": series_of(goal, rows),
    }


# --------------------------------------------------------------- the completion

def completion_of(goal, *, task_queryset) -> dict:
    """The **secondary** bar (FR-4B.20). Counted from whichever tasks the viewer
    may see, so a client's bar counts client-visible work and a fractional's
    counts all of it — neither is ever promoted to the headline."""
    # One filter with a Q, not two querysets OR'd together: combining
    # querysets merges their joins as well as their conditions, and the join
    # through `project` then quietly drops tasks filed straight under the goal.
    tasks = task_queryset.filter(deleted_at__isnull=True).filter(
        Q(goal_id=goal.pk) | Q(project__goal_id=goal.pk))
    # `distinct()` must carry the id: `values_list("status").distinct()` is
    # DISTINCT over the status column, which collapses five tasks in two
    # statuses into a denominator of two.
    statuses = [status for _, status in tasks.values_list("id", "status").distinct()]
    live = [s for s in statuses if s != Task.Status.CANCELLED]
    done = [s for s in live if s == Task.Status.DONE]
    return {"done": len(done), "of": len(live),
            "percent": round(100 * len(done) / len(live)) if live else None}


# --------------------------------------------------------------- the resolution

def resolutions_of(goal):
    """Newest first. Append-only: a goal's state is its latest row."""
    return list(GoalResolution.objects.filter(goal=goal).select_related("resolved_by"))


def current_resolution(goal, rows=None):
    rows = resolutions_of(goal) if rows is None else rows
    return rows[0] if rows else None


def is_historical(goal, rows=None) -> bool:
    latest = current_resolution(goal, rows)
    return latest is not None and latest.resolution in GoalResolution.HISTORICAL


# ----------------------------------------------------------------- the headline

def headline_of(goal, measure) -> dict:
    """**The product rule, decided here rather than in a template** (FR-4B.21).

    A numeric goal leads with baseline → current → target. Everything else —
    qualitative, `none`, or a kind nobody has chosen — leads with the outcome
    statement. The completion bar is **never** the headline, and does not get
    promoted into the slot just because the numeric one is empty.

    **A headline that repeats the title is not a headline** (findings,
    2026-09-21). A goal converted from a map row has its bottleneck as its
    title and nothing written about it yet, so falling back to the title
    printed every card's name twice. When there is nothing distinct to say,
    this says nothing and the card shows what it is waiting on instead.
    """
    if goal.measurable_kind == Goal.MeasurableKind.NUMERIC:
        text = goal.measurable or goal.outcome_statement
        return {"kind": "measure", "text": "" if text.strip() == goal.title.strip()
                else text}
    outcome = (goal.outcome_statement or "").strip()
    if outcome and outcome != goal.title.strip():
        return {"kind": "outcome", "text": outcome}
    return {"kind": "none", "text": ""}


def _awaiting(goal, measure) -> list:
    """The card says what it is short of rather than sitting there empty."""
    missing = []
    if measure["kind"] is None:
        missing.append("no measure recorded yet")
    elif measure["kind"] == Goal.MeasurableKind.NUMERIC and measure["current"] is None:
        missing.append("no reading recorded yet")
    elif measure["kind"] == Goal.MeasurableKind.QUALITATIVE \
            and not goal.how_we_will_know.strip():
        missing.append("no \u201chow we will know\u201d written yet")
    if not (goal.outcome_statement or "").strip():
        missing.append("no outcome statement yet")
    return missing


# ------------------------------------------------------------------- the report

def narrative_for(goal, *, for_client: bool):
    """What the client reads is `body`, and only once accepted. The draft is
    **absent** from their response (AC-4B.15), never merely unrendered."""
    narrative = GoalNarrative.objects.filter(goal=goal).first()
    if narrative is None:
        return None
    accepted = narrative.state == GoalNarrative.State.ACCEPTED and bool(narrative.body)
    if for_client:
        return {"body": narrative.body} if accepted else None
    return {
        "id": str(narrative.pk),
        "state": narrative.state,
        "proposed_body": narrative.proposed_body,
        "body": narrative.body,
        "accepted_at": narrative.accepted_at.isoformat() if narrative.accepted_at else None,
        "accepted_by": narrative.accepted_by.full_name if narrative.accepted_by else "",
        "version_count": narrative.versions.count(),
    }


def goal_block(goal, *, request, for_client: bool, task_queryset) -> dict:
    """One goal, whole. The **structural half shows regardless** of whether a
    narrative has been accepted (FR-4B.34) — holding a goal back until someone
    writes prose would make the report's availability depend on the fractional's
    backlog, which is the failure mode of the artifact this replaces."""
    resolutions = resolutions_of(goal)
    latest = current_resolution(goal, resolutions)
    measure = measure_block(goal, for_client=for_client)
    today = timezone.localdate()
    visible_milestones = milestone_service.for_goal(goal, for_client=for_client)
    block = {
        "id": str(goal.pk),
        "title": goal.title,
        "outcome_statement": goal.outcome_statement,
        "headline": headline_of(goal, measure),
        # What this goal is still waiting for somebody to write or record.
        # **Staff only** — a client is shown the goal, not the practice's
        # unfinished admin (findings, 2026-09-21).
        "awaiting": [] if for_client else _awaiting(goal, measure),
        "measure": measure,
        "completion": completion_of(goal, task_queryset=task_queryset),
        "status": status_service.status_of(goal),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "horizon_days": goal.horizon_days,
        "client_owner_contact": (
            f"{goal.client_owner_contact.first_name} "
            f"{goal.client_owner_contact.last_name}".strip()
            if goal.client_owner_contact_id else ""),
        "is_historical": is_historical(goal, resolutions),
        "resolution": {
            "resolution": latest.resolution,
            # Ruling G — the client reads the reason. A reason they cannot read
            # cannot make "changed course" read as judgement.
            "reason": latest.reason,
            "at": latest.resolved_at.isoformat(),
            "by": latest.resolved_by.full_name if latest.resolved_by else "",
        } if latest else None,
        "resolutions": [
            {"id": str(r.pk), "resolution": r.resolution, "reason": r.reason,
             "at": r.resolved_at.isoformat(),
             "by": r.resolved_by.full_name if r.resolved_by else ""}
            for r in resolutions
        ],
        "milestones": [
            {"id": str(m.pk), "title": m.title,
             "due_date": m.due_date.isoformat() if m.due_date else None,
             "occurred_at": (milestone_service.occurred_on(m).isoformat()
                             if milestone_service.occurred_on(m) else None),
             "state": milestone_service.state_of(m, today=today),
             "is_derived": m.is_derived,
             "source_task": str(m.source_task_id) if m.source_task_id else None}
            for m in visible_milestones
        ],
        "narrative": narrative_for(goal, for_client=for_client),
        "source_map_row": str(goal.source_map_row_id) if goal.source_map_row_id else None,
    }
    if not for_client:
        block["measurements"] = [
            {"id": str(m.pk), "value": str(m.value), "measured_at": m.measured_at.isoformat(),
             "note": m.note,
             "recorded_by": m.recorded_by.full_name if m.recorded_by else ""}
            for m in measurements_of(goal)
        ]
    return block


# ------------------------------------------------------- the engagement timeline

def _goal_span(goal, measurements, resolutions, *, today):
    """FR-4B.36c — a goal starts at the earliest date it has (a `Goal` carries no
    `start_date`, so that is its baseline date, else the day it was created) and
    ends at its latest resolution. An unresolved goal runs to today."""
    start = goal.baseline_at or goal.created_at.date()
    for row in measurements:
        start = min(start, row.measured_at)
    latest = resolutions[0] if resolutions else None
    ends = latest.resolved_at.date() if latest and latest.resolution in \
        GoalResolution.HISTORICAL else today
    return start, max(start, ends)


def timeline_for(goals, *, for_client: bool, today=None) -> dict:
    """One axis across the whole engagement (FR-4B.36a–36e).

    Every mark on it is a row that already exists — **nothing here is stored**,
    and nothing appears that the viewer could not already see: a milestone
    hidden from the client is hidden here, an internal goal never reached this
    function, and a resolution shows its reason because the client reads it.
    """
    today = today or timezone.localdate()
    spans, marks = [], []
    for goal in goals:
        measurements = measurements_of(goal)
        resolutions = resolutions_of(goal)
        start, end = _goal_span(goal, measurements, resolutions, today=today)
        spans.append({"goal": str(goal.pk), "title": goal.title,
                      "start": start.isoformat(), "end": end.isoformat(),
                      "is_historical": is_historical(goal, resolutions)})
        marks.append({"goal": str(goal.pk), "goal_title": goal.title, "kind": "start",
                      "at": start.isoformat(), "label": goal.title, "detail": ""})
        for milestone in milestone_service.for_goal(goal, for_client=for_client):
            at = milestone_service.occurred_on(milestone) or milestone.due_date
            if at is None:
                continue
            marks.append({
                "goal": str(goal.pk), "goal_title": goal.title, "kind": "milestone",
                "at": at.isoformat(), "label": milestone.title,
                "detail": milestone_service.state_of(milestone, today=today)})
        for row in measurements:
            marks.append({
                "goal": str(goal.pk), "goal_title": goal.title, "kind": "reading",
                "at": row.measured_at.isoformat(),
                "label": f"{row.value}{(' ' + goal.measurable_unit) if goal.measurable_unit else ''}",
                "detail": row.note})
        for row in resolutions:
            marks.append({
                "goal": str(goal.pk), "goal_title": goal.title, "kind": "resolution",
                "at": row.resolved_at.date().isoformat(),
                "label": row.get_resolution_display(), "detail": row.reason})
    marks.sort(key=lambda m: (m["at"], m["goal_title"], m["kind"]))
    starts = [s["start"] for s in spans] or [today.isoformat()]
    ends = [s["end"] for s in spans] or [today.isoformat()]
    return {"from": min(starts), "to": max(ends), "spans": spans, "marks": marks,
            "today": today.isoformat()}


# ---------------------------------------------------------------- the whole page

def goals_for_company(request, company_id):
    """**Internal goals never appear** (FR-4B.4, ruling 10): the report is a
    client artifact and has nothing to say about the practice's own work. This
    is a filter on the report, not a permission rule."""
    qs = work_perms.goal_queryset_for(
        request, Goal.objects.filter(deleted_at__isnull=True,
                                     client_company_id=company_id))
    return list(qs.select_related("client_company", "client_owner_contact", "owner")
                .order_by("created_at"))


def report_for(request, *, company, for_client: bool) -> dict:
    """The all-goals report: the engagement timeline first, then every goal,
    **current first and historical below** (FR-4B.1)."""
    goals = goals_for_company(request, company.pk)
    task_queryset = work_perms.task_queryset_for(request, Task.objects.all())
    blocks = [goal_block(g, request=request, for_client=for_client,
                         task_queryset=task_queryset) for g in goals]
    current = [b for b in blocks if not b["is_historical"]]
    historical = [b for b in blocks if b["is_historical"]]
    return {
        "company": {"id": str(company.pk), "name": company.name},
        # FR-4B.36b — the timeline belongs to the all-goals report, and to the
        # all-goals PDF. A single goal's page is already a timeline of one goal.
        "timeline": timeline_for(goals, for_client=for_client),
        "current": current,
        "historical": historical,
        "generated_at": timezone.now().isoformat(),
    }
