"""The practice's own scorecard ("My practice") and its feed "From this app".

**On the scorecard tables, unchanged.** A practice has one hidden company row
(`Company.is_practice`) that holds its scorecard, so pages, tiles, views,
entry and the Sheets and Track feeds all serve it as they serve a client's.
Its audiences are the practice's people: everyone at the practice; the
practice owner and associates; each person their own; the practice owner
only (`access.Reader` in practice mode).

**From this app** reads the practice's own data into a KPI, per closed
period, on the worker once a day, by the Sheets feed's rules (the hand wins,
nothing deleted, one notice on failure, the source on the tile's back). The
measures are a fixed menu (`MEASURES`). The money ones (invoices, cash) are
the practice owner's alone to see and to set, whatever the page's audience:
an assistant has no financials and an associate none of the practice's own.

Cash on hand and the 90-day low come from the cash forecast as it stands
when the period closes; they can't be worked out for a past period, so they
fill the closed period on the first read after it, as a cell feed does.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Max, Q

from . import periods as P

#: key -> (label, kind, money, param). `param` is "stage" for the one measure
#: that names a stage of the sales pipeline.
MEASURES = {
    "new_leads": ("New leads (entered Sales)", "count", False, ""),
    "prospects_in_stage": ("Prospects in a stage (at the period's end)", "count", False, "stage"),
    "proposals_given": ("Proposals given", "count", False, ""),
    "won": ("Won", "count", False, ""),
    "lost": ("Lost", "count", False, ""),
    "close_rate": ("Close rate (won of won and lost)", "percent", False, ""),
    "partners_added": ("Referral partners added", "count", False, ""),
    "introductions_made": ("Introductions made", "count", False, ""),
    "tasks_completed": ("Tasks completed", "count", False, ""),
    "tasks_overdue": ("Tasks overdue (at the period's end)", "count", False, ""),
    "invoices_sent": ("Invoices sent", "count", True, ""),
    "invoices_paid": ("Invoices paid in full", "count", True, ""),
    "invoices_overdue": ("Invoices overdue (at the period's end)", "count", True, ""),
    "days_to_pay": ("Average days to pay", "duration", True, ""),
    "cash_on_hand": ("Cash on hand (from the forecast)", "money", True, ""),
    "cash_low_90": ("Lowest cash in the next 90 days (forecast)", "money", True, ""),
}
FITS = {"count": {"count", "number"}, "percent": {"percent"}, "money": {"money"},
        "duration": {"duration", "number"}}
SNAPSHOT = {"cash_on_hand", "cash_low_90"}
PROPOSAL_CODE = "proposal_given"


class MeasureRefused(ValueError):
    pass


def practice_company(tenant):
    """The practice's own company row, made the first time it is asked for."""
    from apps.crm.models import Company

    found = Company.all_objects.filter(tenant=tenant, is_practice=True).first()
    if found is not None:
        return found
    return Company.all_objects.create(tenant=tenant, name=tenant.name, is_practice=True)


#: A new practice's starter "My practice" (owner, 2026-10-28): six KPIs on
#: "From this app", no targets; the money two are the owner's alone to see.
STARTER = (
    ("New leads", "new_leads", {"kind": "count", "cadence": "weekly", "rollup": "sum",
                                "tile": "bars"}),
    ("Proposals given", "proposals_given", {"kind": "count", "cadence": "weekly",
                                            "rollup": "sum", "tile": "bars"}),
    ("Won", "won", {"kind": "count", "cadence": "monthly", "rollup": "sum", "tile": "bars"}),
    ("Invoices overdue", "invoices_overdue", {"kind": "count", "cadence": "weekly",
                                              "rollup": "last", "direction": "lower"}),
    ("Cash on hand", "cash_on_hand", {"kind": "money", "cadence": "weekly", "rollup": "last",
                                      "tile": "line"}),
    ("Tasks overdue", "tasks_overdue", {"kind": "count", "cadence": "weekly",
                                        "rollup": "last", "direction": "lower"}),
)


def make_starter(tenant, actor) -> list:
    """The starter scorecard on a practice that has none: its first page and
    the six KPIs, each fed "From this app". The worker's daily run reads them."""
    from apps.tenancy.context import tenant_context

    from . import setup
    from .models import Kpi, KpiAppFeed, Scorecard

    with tenant_context(tenant.pk):
        company = practice_company(tenant)
        if Scorecard.objects.filter(company=company).exists():
            return []
        scorecard = setup.ensure(company, actor)
        page = scorecard.pages.get()
        made = []
        for name, measure, fields in STARTER:
            kpi = setup.create_kpi(scorecard, {"name": name, "page": str(page.pk), **fields},
                                   actor)
            KpiAppFeed.objects.create(tenant_id=tenant.pk, kpi=kpi, measure=measure,
                                      created_by=actor)
            Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.APP)
            made.append(kpi)
        return made


def is_money(measure) -> bool:
    return MEASURES.get(measure, ("", "", False))[2]


def menu(*, money: bool) -> list[dict]:
    return [{"key": k, "label": label, "kind": kind, "money": m, "param": param}
            for k, (label, kind, m, param) in MEASURES.items() if money or not m]


def check_fits(kpi, measure, *, role):
    from apps.tenancy.models import Role

    if measure not in MEASURES:
        raise MeasureRefused("Choose a measure from the list.")
    if not kpi.scorecard.company.is_practice:
        raise MeasureRefused("From this app is for the practice's own scorecard.")
    if kpi.per_person:
        raise MeasureRefused(f"{kpi.name} has a reading per person; these measures are one "
                             "number for the practice.")
    label, kind, money, _ = MEASURES[measure]
    if money and role != Role.FF:
        raise MeasureRefused("The money measures are the practice owner's to set.")
    if kpi.kind not in FITS[kind]:
        need = {"count": "Count or Number", "percent": "Percent", "money": "Money",
                "duration": "Duration or Number"}[kind]
        raise MeasureRefused(f"{label} fits a KPI of kind {need}; {kpi.name} is "
                             f"{kpi.get_kind_display()}.")


# ------------------------------------------------------------- the arithmetic

def _bounds(tenant, first, last):
    zone = ZoneInfo(getattr(tenant, "timezone", "") or "UTC")
    return (datetime.combine(first, time.min, tzinfo=zone),
            datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone))


def _sales(tenant):
    from apps.crm.services import pipeline

    return pipeline.sales_pipeline(tenant)


def _moves(tenant, start, end):
    from apps.crm.models import StageChange

    sales = _sales(tenant)
    return StageChange.all_objects.filter(tenant=tenant, pipeline=sales,
                                          created_at__gte=start, created_at__lt=end,
                                          contact__deleted_at__isnull=True)


def _won_lost(tenant, start, end):
    moves = _moves(tenant, start, end)
    won = moves.filter(to_stage__semantic="won").values("contact").distinct().count()
    lost = moves.filter(to_stage__semantic="lost").values("contact").distinct().count()
    return won, lost


def _in_stage_at(tenant, stage_id, end) -> int:
    """Contacts whose last Sales move before `end` put them in the stage."""
    from apps.crm.models import StageChange

    sales = _sales(tenant)
    latest = (StageChange.all_objects.filter(tenant=tenant, pipeline=sales, created_at__lt=end,
                                             contact__deleted_at__isnull=True)
              .values("contact").annotate(at=Max("created_at")))
    count = 0
    for row in latest:
        last = StageChange.all_objects.filter(tenant=tenant, pipeline=sales,
                                              contact_id=row["contact"],
                                              created_at=row["at"]).first()
        count += int(last is not None and str(last.to_stage_id) == str(stage_id))
    return count


def _done_at(tenant, end):
    """Task id -> when it was last marked done before `end`."""
    from apps.work.models import TaskUpdate

    rows = (TaskUpdate.all_objects.filter(tenant=tenant, kind=TaskUpdate.Kind.STATUS_CHANGED,
                                          to_value="done", created_at__lt=end)
            .values("task").annotate(at=Max("created_at")))
    return {r["task"]: r["at"] for r in rows}


def _invoice_money(tenant, end):
    """Invoice id -> (paid by `end` in cents, the day it was paid in full or None)."""
    from apps.billing.models import ClientInvoice, ClientPayment

    out = {}
    for invoice in ClientInvoice.all_objects.filter(tenant=tenant, sent_at__isnull=False,
                                                    sent_at__lt=end).exclude(status="void"):
        paid, full = 0, None
        for p in ClientPayment.all_objects.filter(invoice=invoice, removed_at__isnull=True,
                                                  paid_on__lt=end.date()).order_by("paid_on"):
            paid += p.amount_cents
            if full is None and paid >= invoice.total_cents > 0:
                full = p.paid_on
        out[invoice.pk] = (invoice, paid, full)
    return out


def value_for(measure, tenant, first, last, *, param="", today=None):
    """One period's number, or None when it has nothing to say."""
    from apps.crm.models import ContactTypeLink, Referral, Task

    start, end = _bounds(tenant, first, last)
    if measure == "new_leads":
        return Decimal(_moves(tenant, start, end).filter(from_stage__isnull=True)
                       .values("contact").distinct().count())
    if measure == "prospects_in_stage":
        if not param:
            raise MeasureRefused("Choose the stage.")
        return Decimal(_in_stage_at(tenant, param, end))
    if measure == "proposals_given":
        return Decimal(_moves(tenant, start, end).filter(to_stage__code=PROPOSAL_CODE)
                       .values("contact").distinct().count())
    if measure in ("won", "lost", "close_rate"):
        won, lost = _won_lost(tenant, start, end)
        if measure == "won":
            return Decimal(won)
        if measure == "lost":
            return Decimal(lost)
        return (Decimal(won * 100) / (won + lost)).quantize(Decimal("0.1")) \
            if won + lost else None
    if measure == "partners_added":
        return Decimal(ContactTypeLink.all_objects.filter(
            tenant=tenant, contact_type__code="referral_partner", created_at__gte=start,
            created_at__lt=end, contact__deleted_at__isnull=True).count())
    if measure == "introductions_made":
        return Decimal(Referral.all_objects.filter(
            tenant=tenant, direction=Referral.Direction.OUTBOUND, referred_on__gte=first,
            referred_on__lte=last).count())
    if measure == "tasks_completed":
        return Decimal(sum(1 for at in _done_at(tenant, end).values() if at >= start))
    if measure == "tasks_overdue":
        done_by_end = _done_at(tenant, end)
        done_ever = _done_at(tenant, end + timedelta(days=36500))
        tasks = Task.all_objects.filter(tenant=tenant, due_date__lt=last, created_at__lt=end)
        # Not done by the end: still open, or marked done only after it.
        return Decimal(sum(1 for t in tasks if t.pk not in done_by_end
                           and (t.status != Task.Status.DONE or t.pk in done_ever)))
    if measure in ("invoices_sent", "invoices_paid", "invoices_overdue", "days_to_pay"):
        money = _invoice_money(tenant, end)
        if measure == "invoices_sent":
            return Decimal(sum(1 for inv, _, _ in money.values() if inv.sent_at >= start))
        paid_in = [(inv, full) for inv, _, full in money.values()
                   if full is not None and first <= full <= last]
        if measure == "invoices_paid":
            return Decimal(len(paid_in))
        if measure == "days_to_pay":
            if not paid_in:
                return None
            days = [(full - inv.sent_at.date()).days for inv, full in paid_in]
            return (Decimal(sum(days)) / len(days)).quantize(Decimal("0.1"))
        return Decimal(sum(1 for inv, paid, _ in money.values()
                           if inv.due_date and inv.due_date < last and paid < inv.total_cents))
    if measure in SNAPSHOT:
        from apps.finance import forecast
        from apps.tenancy import modules

        if not modules.has(tenant, modules.FORECAST):
            raise MeasureRefused("This practice doesn't have the cash forecast, which these "
                                 "measures come from.")
        built = forecast.build(tenant, today, snapshot=False)
        if not built["ready"]:
            raise MeasureRefused("The cash forecast isn't ready yet: it needs two closed "
                                 "months in the books.")
        cents = built["cash_today_cents"] if measure == "cash_on_hand" \
            else built["views"]["90"]["low_cents"]
        return (Decimal(cents) / 100).quantize(Decimal("0.01"))
    raise MeasureRefused("Choose a measure from the list.")


def plan_for(feed, today, *, periods=2, back=13, read_open=False):
    """{(start, None): value} for the closed periods this read covers, as the
    Track feed reads: the last two each day, 13 back the first time. A
    snapshot measure fills only the period that closed most recently. With
    `read_open`, the open period too, up to today."""
    kpi = feed.kpi
    tenant = kpi.scorecard.company.tenant
    week_start = kpi.scorecard.week_start
    last_closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                                   week_start)
    count = 1 if feed.measure in SNAPSHOT else (back if feed.last_success_at is None else periods)
    values = {}
    starts = P.last_n(last_closed, kpi.cadence, count, week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    for start in starts:
        value = value_for(feed.measure, tenant, start,
                          min(P.end_of(start, kpi.cadence), today),
                          param=feed.param, today=today)
        if value is not None and MEASURES[feed.measure][1] == "duration" \
                and kpi.kind == "duration":
            value = (value * (24 if kpi.duration_unit == "hours" else 1440)).quantize(
                Decimal("0.1"))
        if value is not None:
            values[(start, None)] = value
    return values
