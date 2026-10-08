"""The landing page's numbers (design brief, Tier 2).

**One call, one set of scoping rules.** Every figure here is read through the
same `*_queryset_for` helpers the individual screens use, so the dashboard
cannot show a CF a total that includes work they are not allowed to open. The
alternative — five separate endpoints the screen adds up — is five places for
that rule to drift.

Nothing here is stored. A dashboard that caches its own totals is a dashboard
that is wrong for as long as the cache lives, and these are cheap counts.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.crm import permissions as crm_perms
from apps.crm.models import Company, StageChange, Task
from apps.work import permissions as work_perms
from apps.work.models import Digest, Goal, GoalResolution

#: "This week" means the next seven days, not the calendar week. On a Thursday,
#: "due this week" meaning "in the next two days" is a number that shrinks as
#: the week goes on and tells you less the longer you look at it.
WINDOW_DAYS = 7

#: The pipeline panel groups names into "This week" and "Last week", so it
#: reads two windows back. The tile still counts one: it says "in the last week".
PIPELINE_DAYS = 14
#: Per pipeline, so a busy referral month cannot push every prospect off.
PIPELINE_ROWS = 12

OPEN_STATUSES = [Task.Status.NOT_STARTED, Task.Status.IN_PROGRESS,
                 Task.Status.BLOCKED, Task.Status.WAITING_ON_CLIENT]


def for_request(request) -> dict:
    today = timezone.localdate()
    until = today + timedelta(days=WINDOW_DAYS)
    since = timezone.now() - timedelta(days=WINDOW_DAYS)

    tasks = work_perms.task_queryset_for(
        request, Task.objects.filter(status__in=OPEN_STATUSES))
    due = tasks.filter(due_date__isnull=False, due_date__lte=until)
    goals = _open_goals(request)
    digests = _digests_for(request).filter(state=Digest.State.PENDING)
    changes = _stage_changes_for(request)
    moves = changes.filter(created_at__gte=since)

    return {
        "window_days": WINDOW_DAYS,
        "tiles": {
            # Overdue is counted separately and named separately: a number that
            # silently folds "late" into "soon" is a number you stop reading.
            "tasks_due": due.count(),
            "tasks_overdue": due.filter(due_date__lt=today).count(),
            "digests_pending": digests.count(),
            "pipeline_moves": moves.count(),
            "goals_open": goals.count(),
        },
        "due_by_day": _by_day(due, today, until),
        "digests": [_digest_row(d) for d in
                    digests.select_related("contact").order_by("period_end")[:8]],
        "pipeline": _pipeline_rows(changes.filter(
            created_at__gte=timezone.now() - timedelta(days=PIPELINE_DAYS))),
        "clients": _clients(request, tasks, goals),
        # AI spend is the FF's (FR-0.9): the finances slot shows it to them only.
        "ai": _ai_state(request),
        # P5: revenue, expenses and margin this month. The practice owner's
        # only (matrix 13.10); absent from everyone else's payload.
        "finance": _finance(request, today),
        # Every staff role sees that automatic AI work is paused; only the FF
        # sees the amounts (owner, 2026-09-29; FR-0.9).
        "ai_paused": _ai_paused(request),
        "waiting": _waiting(request),
    }


def _ai_paused(request):
    from apps.tenancy import ai_guard

    role = getattr(getattr(request, "membership", None), "role", None)
    state = ai_guard.status(request.tenant, financial=role == "FF")
    return state if state["paused"] or state["stopped_after_two_failures"] else None


def _waiting(request):
    """Commitments by people outside the practice (owner, 2026-09-28): how many
    are open, and how many are past their follow-up date."""
    from apps.meetings import commitments
    from apps.meetings.models import Commitment

    qs = commitments.scoped(request, Commitment.objects.filter(
        state=Commitment.State.OPEN))
    return {"open": qs.count(), "overdue": qs.filter(commitments.overdue_filter()).count()}


def _finance(request, today):
    if getattr(getattr(request, "membership", None), "role", None) != "FF":
        return None
    from apps.finance import reports

    return reports.this_month(request.tenant, today)


def _ai_state(request):
    from apps.tenancy import ai_budget

    if getattr(getattr(request, "membership", None), "role", None) != "FF":
        return None
    return ai_budget.state(request.tenant)


def _open_goals(request):
    """A goal's state is its **latest** resolution row (4B ruling 7), so
    "open" is not a column to filter on — a paused goal that was resumed is
    current again, and a subquery on "has any historical row" would hide it.
    """
    goals = work_perms.goal_queryset_for(request, Goal.objects.all())
    latest = {}
    for row in GoalResolution.objects.filter(goal__in=goals).order_by(
            "goal_id", "-resolved_at", "-created_at"):
        latest.setdefault(row.goal_id, row.resolution)
    closed = [goal_id for goal_id, resolution in latest.items()
              if resolution in GoalResolution.HISTORICAL]
    return goals.exclude(pk__in=closed)


def _digests_for(request):
    from apps.crm.permissions import Role, role_of

    digests = Digest.objects.all()
    role = role_of(request)
    if role in (Role.FF, Role.VA):
        return digests
    if role == Role.CF:
        return digests.filter(
            contact__company_id__in=crm_perms.assigned_company_ids(request))
    return digests.none()


def _stage_changes_for(request):
    """Scoped by the contact, which is where the rule already lives."""
    from apps.crm.models import Contact

    visible = crm_perms.contact_queryset_for(
        request, Contact.objects.filter(deleted_at__isnull=True))
    return StageChange.objects.filter(contact__in=visible).order_by("-created_at")


def _by_day(due, today, until) -> list[dict]:
    """Seven days, each named, **including the empty ones**.

    A list that skips quiet days makes a light week look like a missing one,
    and hides that Thursday is the day with everything in it.
    """
    counts = dict(due.filter(due_date__gte=today)
                  .values_list("due_date")
                  .annotate(n=Count("id"))
                  .values_list("due_date", "n"))
    days = []
    overdue = due.filter(due_date__lt=today).count()
    if overdue:
        days.append({"date": None, "label": "Overdue", "count": overdue,
                     "overdue": True})
    for offset in range((until - today).days + 1):
        day = today + timedelta(days=offset)
        days.append({
            "date": day.isoformat(),
            "label": "Today" if offset == 0 else
                     "Tomorrow" if offset == 1 else day.strftime("%a %-d %b"),
            "count": counts.get(day, 0),
            "overdue": False,
        })
    return days


def _digest_row(digest) -> dict:
    return {
        "id": str(digest.pk),
        "contact": f"{digest.contact.first_name} {digest.contact.last_name}".strip(),
        "cadence": digest.cadence,
        "period_end": digest.period_end.isoformat(),
        "ai_prose": digest.is_ai_generated,
        "stale": digest.is_stale,
    }


def _pipeline_rows(recent) -> list[dict]:
    """The newest `PIPELINE_ROWS` changes **in each pipeline**, newest first.

    One cap across all pipelines let whichever was busiest crowd the other
    column out of the panel entirely.
    """
    rows = []
    for pipeline_id in recent.order_by().values_list("pipeline_id", flat=True).distinct():
        rows.extend(recent.filter(pipeline_id=pipeline_id).select_related(
            "contact", "from_stage", "to_stage", "pipeline")[:PIPELINE_ROWS])
    rows.sort(key=lambda change: change.created_at, reverse=True)
    return [_move_row(change) for change in rows]


def _move_row(change) -> dict:
    return {
        "id": str(change.pk),
        "contact": str(change.contact_id),
        "name": f"{change.contact.first_name} {change.contact.last_name}".strip(),
        "pipeline": change.pipeline.name,
        "from": change.from_stage.label if change.from_stage_id else "",
        "to": change.to_stage.label,
        "at": change.created_at.isoformat(),
    }


def _clients(request, tasks, goals) -> list[dict]:
    """One card per client company, with the two numbers that decide whether
    you open it. Ordered by what is overdue, because that is the question the
    card is being scanned for."""
    today = timezone.localdate()
    companies = crm_perms.company_queryset_for(
        request, Company.objects.filter(is_client_company=True,
                                        deleted_at__isnull=True))
    rows = []
    for company in companies.order_by("name")[:24]:
        theirs = tasks.filter(client_company_id=company.pk)
        rows.append({
            "id": str(company.pk),
            "name": company.name,
            "open_tasks": theirs.count(),
            "overdue": theirs.filter(due_date__lt=today).count(),
            "open_goals": goals.filter(client_company_id=company.pk).count(),
        })
    rows.sort(key=lambda row: (-row["overdue"], -row["open_tasks"], row["name"]))
    return rows
