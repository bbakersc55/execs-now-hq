"""Readings by hand (spec, "Readings and entering them by hand").

- **The entry screen**: one form for a period, every KPI the person may
  enter in page order, each with its unit and last period's value; on a
  per-person KPI one field per person they cover. Past periods may be
  entered; a future one is refused.
- **One value per period**: saving again replaces the value and keeps every
  value it has held, with who and when (`KpiReadingChange`).
- **Bulk entry**: periods across, KPIs down, for catching up; the same rules.
- **Reminders**: when a period closes without a value, the KPI's reading
  owner gets one, shown in the app until the reading is in.
- **Units**: a percent is typed as 82, money in dollars, a duration in the
  KPI's own unit, a rating out of its scale; anything else is refused and
  the refusal says why.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import periods as P
from .board import Targets, definition, name_of, num
from .models import Kpi, KpiMonthTarget, KpiPerson, KpiReading, KpiReadingChange, KpiReminder

LIMIT = Decimal("1e12")
#: How far back the period pickers reach: two years of each cadence (Bryan,
#: 2026-10-23), and never short of January 2025 (Bryan, 2026-10-24: any month
#: back to then can be chosen, next year too). Entering further back is
#: allowed; the pickers stop here.
REACH = {P.DAILY: 731, P.WEEKLY: 105, P.MONTHLY: 24, P.QUARTERLY: 8}
FLOOR = date(2025, 1, 1)


def reach(today, cadence, week_start="monday") -> list:
    """The periods the pickers offer, newest first: back to the earlier of
    two years ago and the period January 1, 2025 is in."""
    rolling = P.last_n(today, cadence, REACH[cadence], week_start)[0]
    first = min(rolling, P.start_of(FLOOR, cadence, week_start))
    return list(reversed(P.starts_between(first, today, cadence, week_start)))


class ReadingRefused(ValueError):
    pass


def parse(kpi, raw) -> Decimal:
    """The typed value as a decimal in the KPI's unit, or ReadingRefused
    saying what shape it wants."""
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if kpi.kind == Kpi.Kind.MONEY:
        text = text.replace("$", "").strip()
    if kpi.kind == Kpi.Kind.PERCENT:
        text = text.rstrip("%").strip()
    if not text:
        raise ReadingRefused("Type a number.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        want = {"percent": "a percent as a number, like 82",
                "money": "an amount in dollars, like 12400 or 12,400.50",
                "count": "a whole number", "rating": "a rating, like 4.5",
                "duration": f"a number of {kpi.duration_unit or 'hours'}"}.get(
            kpi.kind, "a number")
        raise ReadingRefused(f"That isn't a number. Type {want}.") from None
    if not value.is_finite() or abs(value) >= LIMIT:
        raise ReadingRefused("That number is too large.")
    if kpi.kind == Kpi.Kind.COUNT:
        if value != value.to_integral_value() or value < 0:
            raise ReadingRefused("A count is a whole number, zero or more.")
    if kpi.kind == Kpi.Kind.MONEY and value.as_tuple().exponent < -2:
        raise ReadingRefused("Money has at most two places after the point.")
    if kpi.kind == Kpi.Kind.PERCENT and Decimal(0) < abs(value) < 1 and "." in text \
            and kpi.target_value is not None and abs(kpi.target_value) >= 1:
        raise ReadingRefused(f"Type the percent as {(value * 100).normalize():f}, "
                             f"not {text}.")
    if kpi.kind == Kpi.Kind.RATING:
        scale = kpi.rating_scale or 5
        if value < 0 or value > scale:
            raise ReadingRefused(f"A rating is from 0 to {scale}.")
    if kpi.kind == Kpi.Kind.DURATION and value < 0:
        raise ReadingRefused("A duration can't be negative.")
    return value.quantize(Decimal("0.0001"))


def _visible_entries(reader, scorecard):
    """The KPIs this person may enter, in page order, each with the rows."""
    from .board import visible_pages

    out = []
    for page, kpis in visible_pages(reader, scorecard):
        for kpi in kpis:
            if not reader.may_enter(kpi):
                continue
            rows = None
            if kpi.per_person:
                rows = reader.enters_rows_of(kpi)
                if not rows:
                    continue
            out.append((page, kpi, rows))
    return out


def form(reader, scorecard, day: date, today: date) -> dict:
    """The entry form for the period `day` is in, for each KPI's cadence."""
    week_start = scorecard.week_start
    if P.start_of(day, P.WEEKLY, week_start) > today:
        raise ReadingRefused("Readings can't be entered for a future period.")
    entries = _visible_entries(reader, scorecard)
    kpi_ids = [k.pk for _, k, _ in entries]
    starts = {k.pk: P.start_of(day, k.cadence, week_start) for _, k, _ in entries}
    before = {k.pk: P.previous_start(starts[k.pk], k.cadence, week_start)
              for _, k, _ in entries}
    found = defaultdict(dict)
    for r in KpiReading.objects.filter(kpi_id__in=kpi_ids).filter(
            period_start__in=set(starts.values()) | set(before.values())):
        found[r.kpi_id][(r.period_start, r.membership_id)] = r
    months = defaultdict(dict)
    for t in KpiMonthTarget.objects.filter(kpi_id__in=kpi_ids):
        months[t.kpi_id][t.month] = t.value
    names = {p.membership_id: name_of(p.membership.user) for p in
             KpiPerson.objects.filter(kpi_id__in=kpi_ids).select_related("membership__user")}
    you = reader.membership.pk

    def field(kpi, membership):
        now = found[kpi.pk].get((starts[kpi.pk], membership))
        last = found[kpi.pk].get((before[kpi.pk], membership))
        return {"membership": str(membership) if membership else None,
                "name": names.get(membership, "") if membership else "",
                "you": membership == you,
                "value": num(now.value) if now else None,
                "reading": str(now.pk) if now else None,
                "edited": bool(now and now.times_changed),
                "last": num(last.value) if last else None}

    kpis = []
    for page, kpi, rows in entries:
        target = Targets(kpi, months[kpi.pk]).of(starts[kpi.pk])
        kpis.append({
            **definition(kpi, reader=reader),
            "page_name": page.name,
            "period_start": starts[kpi.pk].isoformat(),
            "period_label": P.long_label(starts[kpi.pk], kpi.cadence),
            "target": num(target),
            "fields": ([field(kpi, m) for m in sorted(rows, key=lambda m: (
                m != you, names.get(m, "").lower()))] if rows is not None
                else [field(kpi, None)]),
        })
    weekly = P.start_of(day, P.WEEKLY, week_start)
    return {
        "period": {"day": weekly.isoformat(), "week_start": week_start,
                   "label": P.long_label(weekly, P.WEEKLY),
                   "closes": P.end_of(weekly, P.WEEKLY).isoformat(),
                   "open": not P.closed(weekly, P.WEEKLY, today)},
        # Grouped by the month each week starts in, so a month is found as
        # easily here as in the catch-up table's From.
        "choices": [{"day": s.isoformat(), "label": P.long_label(s, P.WEEKLY),
                     "month": P.long_label(s.replace(day=1), P.MONTHLY)}
                    for s in reach(today, P.WEEKLY, week_start)],
        "kpis": kpis,
        "progress": progress(reader, scorecard, starts_for_week=weekly),
    }


def default_day(reader, scorecard, today: date) -> date:
    """Where the form opens: the week just closed while any field of it is
    still empty for this person, else this week (a Monday's numbers are
    last week's)."""
    last = P.previous_start(P.start_of(today, P.WEEKLY, scorecard.week_start), P.WEEKLY,
                            scorecard.week_start)
    if any(f["value"] is None for k in form(reader, scorecard, last, today)["kpis"]
           for f in k["fields"]):
        return last
    return today


def progress(reader, scorecard, *, starts_for_week):
    """"This week, across the company": which KPIs are in, and whose they
    are. Only KPIs the reader sees, and never a colleague's value."""
    from .board import visible_pages

    out = []
    for _, kpis in visible_pages(reader, scorecard):
        for kpi in kpis:
            start = P.start_of(starts_for_week, kpi.cadence, scorecard.week_start)
            has = KpiReading.objects.filter(kpi=kpi, period_start=start)
            if kpi.per_person:
                rows = reader.rows_of(kpi)
                has = has.filter(membership_id__in=rows)
                state = "yours" if reader.may_enter(kpi) else (
                    "in" if has.exists() else "waiting")
            else:
                state = "yours" if kpi.reading_owner_id == reader.user_id and not \
                    has.exists() else ("in" if has.exists() else "waiting")
            out.append({"id": str(kpi.pk), "name": kpi.name, "state": state,
                        "owner": name_of(kpi.reading_owner)})
    return out


@transaction.atomic
def save(reader, scorecard, rows, today: date) -> dict:
    """Save readings. Each row is {kpi, period_start, membership?, value};
    a blank value leaves a reading as it is. All or nothing: the errors say
    which field, and nothing is saved while any is wrong."""
    week_start = scorecard.week_start
    kpis = {str(k.pk): k for k in Kpi.objects.filter(scorecard=scorecard,
                                                     archived_at__isnull=True)
            .select_related("page", "page__team", "audience_team")}
    errors, plan = {}, []
    for i, row in enumerate(rows if isinstance(rows, list) else []):
        key = f"{row.get('kpi')}|{row.get('period_start')}|{row.get('membership') or ''}"
        kpi = kpis.get(str(row.get("kpi")))
        if kpi is None or not reader.sees_kpi(kpi):
            errors[key] = "That KPI isn't on a scorecard you can see."
            continue
        if not reader.may_enter(kpi):
            errors[key] = "You can't enter readings for this KPI."
            continue
        try:
            start = date.fromisoformat(str(row.get("period_start")))
        except ValueError:
            errors[key] = "That isn't a period."
            continue
        if not P.is_valid_start(start, kpi.cadence, week_start):
            errors[key] = f"That isn't the start of a {P.noun(kpi.cadence)}."
            continue
        if start > today:
            errors[key] = "Readings can't be entered for a future period."
            continue
        member = row.get("membership") or None
        if kpi.per_person:
            allowed = {str(m) for m in reader.enters_rows_of(kpi)}
            if member is None or str(member) not in allowed:
                errors[key] = "You can't enter this person's reading."
                continue
        elif member is not None:
            errors[key] = "This KPI has no readings per person."
            continue
        raw = row.get("value")
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = parse(kpi, raw)
        except ReadingRefused as exc:
            errors[key] = str(exc)
            continue
        plan.append((kpi, start, member, value))
    if errors:
        return {"saved": 0, "changed": 0, "errors": errors}
    saved = changed = 0
    now = timezone.now()
    user = reader.request.user
    for kpi, start, member, value in plan:
        reading = KpiReading.objects.select_for_update().filter(
            kpi=kpi, period_start=start, membership_id=member).first()
        if reading is None:
            reading = KpiReading.objects.create(
                tenant_id=kpi.tenant_id, kpi=kpi, period_start=start, membership_id=member,
                value=value, entered_by=user, entered_at=now)
            KpiReadingChange.objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                            value=value, changed_by=user)
            saved += 1
        elif reading.value != value:
            KpiReadingChange.objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                            value=value, previous_value=reading.value,
                                            changed_by=user)
            reading.value, reading.entered_by, reading.entered_at = value, user, now
            reading.times_changed += 1
            # Typed over a feed's number: the hand wins from now on (spec, "Feeds").
            reading.source = KpiReading.Source.HAND
            reading.save(update_fields=["value", "entered_by", "entered_at",
                                        "times_changed", "source", "updated_at"])
            changed += 1
    return {"saved": saved, "changed": changed, "errors": {}}


def history(reader, reading) -> dict:
    """Every value a reading has held, for someone who can enter it."""
    kpi = reading.kpi
    if not reader.sees_history_of(kpi):
        return None
    if reading.membership_id is not None and \
            reading.membership_id not in reader.covered_rows(kpi):
        return None
    return {
        "kpi": kpi.name, "period": P.long_label(reading.period_start, kpi.cadence),
        "changes": [{"value": num(c.value), "previous": num(c.previous_value),
                     "by": name_of(c.changed_by), "at": c.created_at.isoformat()}
                    for c in reading.changes.select_related("changed_by")],
    }


def bulk(reader, scorecard, cadence, count, today, first=None) -> dict:
    """Periods across, KPIs down: the KPIs of one cadence this person may
    enter, with their rows, over the last `count` periods, or `count`
    periods from the one `first` is in (never past the current one)."""
    week_start = scorecard.week_start
    if first is not None:
        start = P.start_of(min(first, today), cadence, week_start)
        starts = []
        while len(starts) < count and start <= today:
            starts.append(start)
            start = P.next_start(start, cadence)
    else:
        starts = P.last_n(today, cadence, count, week_start)
    entries = [(p, k, r) for p, k, r in _visible_entries(reader, scorecard)
               if k.cadence == cadence]
    found = {(r.kpi_id, r.period_start, r.membership_id): r for r in
             KpiReading.objects.filter(kpi_id__in=[k.pk for _, k, _ in entries],
                                       period_start__in=starts)}
    names = {p.membership_id: name_of(p.membership.user) for p in
             KpiPerson.objects.filter(kpi_id__in=[k.pk for _, k, _ in entries])
             .select_related("membership__user")}
    lines = []
    for _, kpi, rows in entries:
        for member in (sorted(rows, key=lambda m: names.get(m, "").lower())
                       if rows is not None else [None]):
            lines.append({
                **definition(kpi, reader=reader),
                "membership": str(member) if member else None,
                "person": names.get(member, "") if member else "",
                "cells": [{"period_start": s.isoformat(),
                           "value": num(found[(kpi.pk, s, member)].value)
                           if (kpi.pk, s, member) in found else None} for s in starts],
            })
    offered = reach(today, cadence, week_start)
    earliest = offered[-1]
    latest_first = P.last_n(today, cadence, count, week_start)[0]
    earlier = later = None
    if starts and starts[0] > earliest:
        earlier = starts[0]
        for _ in range(count):
            earlier = P.previous_start(earlier, cadence, week_start)
        earlier = max(earlier, earliest)
    if starts and starts[0] < latest_first:
        later = starts[0]
        for _ in range(count):
            later = P.next_start(later, cadence)
        later = min(later, latest_first)
    return {"cadence": cadence, "periods": [{"start": s.isoformat(),
                                              "label": P.short_label(s, cadence)}
                                             for s in starts], "lines": lines,
            "from": starts[0].isoformat() if starts else None,
            "earliest": earliest.isoformat(),
            # Earlier / Later step a table's width at a time; "" for later is
            # the latest periods.
            "earlier": earlier.isoformat() if earlier else None,
            "later": None if later is None else
            ("" if later == latest_first else later.isoformat()),
            # The "From" picker's periods, newest first; a daily one is a date field.
            "choices": [] if cadence == P.DAILY else
            [{"start": s.isoformat(), "label": P.long_label(s, cadence)} for s in offered]}


# ---------------------------------------------------------------- reminders

def remind(tenant, today: date) -> int:
    """One reminder per KPI per closed period without a value, to its
    reading owner. Safe to run as often as liked: a period is reminded
    once. Only the period that closed most recently is looked at, so a new
    KPI does not send its whole past."""
    from .models import Scorecard

    made = 0
    for scorecard in Scorecard.all_objects.filter(tenant=tenant,
                                                  company__deleted_at__isnull=True):
        for kpi in Kpi.all_objects.filter(scorecard=scorecard, archived_at__isnull=True,
                                          page__archived_at__isnull=True, formula="",
                                          reading_owner__isnull=False):
            start = P.previous_start(P.start_of(today, kpi.cadence, scorecard.week_start),
                                     kpi.cadence, scorecard.week_start)
            if kpi.created_at.date() > P.end_of(start, kpi.cadence):
                continue
            if not _missing(kpi, start):
                continue
            _, created = KpiReminder.all_objects.get_or_create(
                kpi=kpi, period_start=start,
                defaults={"tenant_id": kpi.tenant_id, "recipient_id": kpi.reading_owner_id})
            made += int(created)
    return made


def _missing(kpi, start) -> bool:
    have = KpiReading.all_objects.filter(kpi=kpi, period_start=start)
    if not kpi.per_person:
        return not have.exists()
    tracked = set(KpiPerson.all_objects.filter(
        kpi=kpi, membership__revoked_at__isnull=True).values_list("membership_id", flat=True))
    return bool(tracked - set(have.values_list("membership_id", flat=True)))


def notices(request, company=None) -> list:
    """The reminders waiting on the person asking: reading owners asked for
    a number that is still not in, and told when their KPI's feed failed."""
    rows = (KpiReminder.objects.filter(recipient_id=request.user.pk,
                                       kpi__archived_at__isnull=True)
            .select_related("kpi", "kpi__scorecard__company"))
    if company is not None:
        rows = rows.filter(kpi__scorecard__company=company)
    out = []
    for r in rows.order_by("-period_start"):
        if not _missing(r.kpi, r.period_start):
            continue
        out.append({"kind": "reminder", "kpi": r.kpi.name, "kpi_id": str(r.kpi_id),
                    "company": r.kpi.scorecard.company.name,
                    "company_id": str(r.kpi.scorecard.company_id),
                    "period_start": r.period_start.isoformat(),
                    "text": f"No reading yet for {P.long_label(r.period_start, r.kpi.cadence)}",
                    "reminded_at": r.created_at.isoformat()})
    from .feeds import notices_for

    return out + notices_for(request.user, company)
