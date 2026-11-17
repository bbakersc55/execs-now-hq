"""When a recurring invoice bills (2026-11-17; cadences 2026-11-17, later).

A schedule's timing is a **cadence**, how often it counts (`every`), and the
cadence's own fields, from its first date (`first_billing_on`):

- **weekly**: every `every` weeks on `weekday` (0 is Monday), counted from the
  first date (which is on that weekday). Weekly is every 1, every two weeks 2.
- **monthly**: every `every` months on one or more `days_of_month`, 1 to 28 so
  that every month has each of them, counted from the first date's month.
  Monthly is every 1; twice a month is the 1st and 15th; quarterly is every 3
  on one day; custom is every N.
- **yearly**: once a year on the first date's month and day; any date but
  February 29.

The form's presets (Weekly, Every two weeks, Twice a month, Monthly,
Quarterly, Yearly, Custom) are only ways of filling these fields. Nothing else
in billing works out a billing date except through this module.

**Stopping** (`notice_end`): billing ends on the last day of the calendar
month after the month notice is given, every billing date up to and including
that day billed and none after; or on the contract's end date, when there is
one and it is later. The same for every cadence.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

#: The days a monthly schedule may bill on: in every month there is.
MONTH_DAYS = range(1, 29)
#: How far ahead `next_date` looks: more than a year of any cadence.
HORIZON = timedelta(days=800)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
#: The most a custom schedule counts: a year of weeks or of months.
EVERY_MOST = {"weekly": 52, "monthly": 12, "yearly": 1}
CADENCES_ALLOWED = ("weekly", "monthly", "yearly")
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


class TimingError(ValueError):
    """A timing that can't be billed, said in plain words."""


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _long(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + n
    return index // 12, index % 12 + 1


# ------------------------------------------------------------- checking

def clean_days(values) -> list[int]:
    """Days of the month as given ([15, "1"]), checked and sorted ([1, 15])."""
    if not isinstance(values, (list, tuple)) or not values:
        raise TimingError("Choose at least one day of the month.")
    days = set()
    for value in values:
        if isinstance(value, bool):
            raise TimingError("A day of the month is a number from 1 to 28.")
        try:
            day = int(value)
        except (TypeError, ValueError):
            raise TimingError("A day of the month is a number from 1 to 28.") from None
        if day not in MONTH_DAYS or str(value).strip() not in (str(day), f"{day}.0"):
            raise TimingError("A day of the month is a number from 1 to 28.")
        days.add(day)
    return sorted(days)


def clean_weekday(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
        raise TimingError("Choose the weekday.")
    return value


def clean_every(value, cadence: str) -> int:
    most = EVERY_MOST.get(cadence, 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
        unit = {"weekly": "weeks", "monthly": "months"}.get(cadence, "years")
        raise TimingError(f"Every 1 to {most} {unit}." if most > 1 else "Once a year.")
    return value


def check(schedule) -> None:
    """A schedule's timing, as saved: refused in plain words if it can't be
    billed. Fills in what follows from the first date."""
    cadence = schedule.cadence
    if cadence not in CADENCES_ALLOWED:
        raise TimingError("Choose how often it bills.")
    schedule.every = clean_every(schedule.every, cadence)
    first = schedule.first_billing_on
    if first is None:
        raise TimingError("Choose the first date.")
    if cadence == "weekly":
        schedule.weekday = clean_weekday(schedule.weekday)
        if first.weekday() != schedule.weekday:
            raise TimingError(f"The first date is a {WEEKDAYS[schedule.weekday]}, "
                              f"like the rest.")
        schedule.days_of_month = []
    elif cadence == "monthly":
        schedule.weekday = None
        schedule.days_of_month = clean_days(schedule.days_of_month)
        if schedule.every > 1 and len(schedule.days_of_month) > 1:
            raise TimingError("Every few months bills on one day of the month.")
        if first.day not in schedule.days_of_month:
            raise TimingError(f"The first date is on one of its days (the "
                              f"{_and([ordinal(d) for d in schedule.days_of_month])}).")
    else:
        schedule.weekday = None
        schedule.days_of_month = []
        if (first.month, first.day) == (2, 29):
            raise TimingError("A yearly date can't be February 29: choose February 28 or "
                              "March 1.")
    if schedule.term_ends_on is not None and schedule.term_ends_on < first:
        raise TimingError("The contract can't end before the first date.")


def shortest_gap(schedule) -> int:
    """The fewest days between two billing dates, over a year of them."""
    found = dates(schedule, schedule.first_billing_on,
                  schedule.first_billing_on + timedelta(days=800))
    gaps = [(b - a).days for a, b in zip(found, found[1:])]
    return min(gaps) if gaps else 365


def check_lead(schedule, lead_days: int) -> None:
    """The invoice is emailed at most the gap between billing dates ahead."""
    gap = shortest_gap(schedule)
    if lead_days > gap:
        raise TimingError(f"Billing dates can be {gap} day{'' if gap == 1 else 's'} apart, so "
                          f"each invoice is emailed at most {gap} day"
                          f"{'' if gap == 1 else 's'} before.")


# ---------------------------------------------------------------- dates

def _monthly(schedule, start: date, end: date):
    first = schedule.first_billing_on
    days = sorted(set(schedule.days_of_month))
    low = max(start, first)
    year, month = first.year, first.month
    # Jump to the first counted month on or before `low`'s month.
    behind = (low.year - year) * 12 + (low.month - month)
    if behind > 0:
        year, month = _add_months(year, month, behind - behind % schedule.every)
    while date(year, month, 1) <= end:
        for day in days:
            on = date(year, month, day)
            if low <= on <= end:
                yield on
        year, month = _add_months(year, month, schedule.every)


def _weekly(schedule, start: date, end: date):
    first = schedule.first_billing_on
    step = 7 * schedule.every
    low = max(start, first)
    on = first + timedelta(days=((low - first).days + step - 1) // step * step)
    while on <= end:
        yield on
        on += timedelta(days=step)


def _yearly(schedule, start: date, end: date):
    first = schedule.first_billing_on
    year = max(first.year, start.year)
    while True:
        on = date(year, first.month, first.day)
        if on > end:
            return
        if on >= max(start, first):
            yield on
        year += schedule.every


CADENCES = {"monthly": _monthly, "weekly": _weekly, "yearly": _yearly}


def dates(schedule, start: date, end: date) -> list[date]:
    """Every billing date from `start` through `end`, both included, never
    before the first date."""
    if end < start or schedule.first_billing_on is None:
        return []
    return list(CADENCES[schedule.cadence](schedule, start, end))


def next_date(schedule, on_or_after: date, *, through: date | None = None) -> date | None:
    """The first billing date on or after a day (and, given, not after
    `through`); None if there is none."""
    end = on_or_after + HORIZON
    if through is not None:
        end = min(end, through)
    found = dates(schedule, on_or_after, end)
    return found[0] if found else None


def last_date(schedule, start: date, end: date) -> date | None:
    found = dates(schedule, start, end)
    return found[-1] if found else None


def notice_end(notice_on: date, term_ends_on: date | None = None) -> date:
    """The last day billed after notice given on `notice_on`: the last day of
    the next calendar month, or the contract's end if that is later."""
    year, month = _add_months(notice_on.year, notice_on.month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    if term_ends_on is not None and term_ends_on > end:
        return term_ends_on
    return end


# ---------------------------------------------------------------- words

def _times(n: int, unit: str) -> str:
    return f"every {_NUMBER_WORDS.get(n, str(n))} {unit}s"


def describe(schedule) -> str:
    """The schedule in plain words: "every Friday", "every two weeks on
    Friday", "on the 1st and 15th of each month", "on the 1st of January,
    April, July and October", "every year on March 31"."""
    first = schedule.first_billing_on
    if schedule.cadence == "weekly":
        day = WEEKDAYS[schedule.weekday if schedule.weekday is not None else first.weekday()]
        return f"every {day}" if schedule.every == 1 else f"{_times(schedule.every, 'week')} on {day}"
    if schedule.cadence == "yearly":
        return f"every year on {first:%B} {first.day}"
    days = _and([ordinal(d) for d in sorted(set(schedule.days_of_month))])
    if schedule.every == 1:
        return f"on the {days} of each month"
    if first is not None and 12 % schedule.every == 0 and schedule.every < 12:
        months = sorted({_add_months(first.year, first.month, k * schedule.every)[1]
                         for k in range(12 // schedule.every)})
        return f"on the {days} of " + _and([calendar.month_name[m] for m in months])
    if schedule.every == 12 and first is not None:
        return f"on the {days} of {first:%B} each year"
    return f"{_times(schedule.every, 'month')} on the {days}"
