"""When a recurring invoice that bills automatically bills (2026-11-17).

A schedule's timing is a **cadence**, how often it counts (`every`), and the
cadence's own fields, from its first billing date. Only **monthly** is built:
one or more days of the month, 1 to 28, so every month has each of them and
nothing is ever moved for a short month. Weekly, every two weeks, quarterly,
yearly and every-N are meant to be added as further cadences here: a function
that lists a schedule's billing dates between two days, and its words. Nothing
else in billing reads a schedule's timing except through this module.

**Stopping** (`notice_end`): billing ends on the last day of the calendar
month after the month notice is given, every billing date up to and
including that day billed and none after; or on the contract's end date,
when there is one and it is later.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

#: The days a monthly schedule may bill on: in every month there is.
MONTH_DAYS = range(1, 29)
#: How far ahead `next_date` looks: more than a year of any cadence.
HORIZON = timedelta(days=800)


class TimingError(ValueError):
    """A timing that can't be billed, said in plain words."""


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


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


def check(schedule) -> None:
    """The timing of a schedule that bills automatically, as saved."""
    if schedule.cadence != "monthly":
        raise TimingError("Only monthly billing can be chosen so far.")
    if schedule.every != 1:
        raise TimingError("Only every month can be chosen so far.")
    schedule.days_of_month = clean_days(schedule.days_of_month)
    if schedule.first_billing_on is None:
        raise TimingError("Choose the first billing date.")
    if schedule.first_billing_on.day not in schedule.days_of_month:
        raise TimingError(f"The first billing date is on one of its billing days (the "
                          f"{_and([ordinal(d) for d in schedule.days_of_month])}).")
    if schedule.term_ends_on is not None and schedule.term_ends_on < schedule.first_billing_on:
        raise TimingError("The contract can't end before the first billing date.")


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


CADENCES = {"monthly": _monthly}


def dates(schedule, start: date, end: date) -> list[date]:
    """Every billing date from `start` through `end`, both included, never
    before the first billing date."""
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

def describe(schedule) -> str:
    """"on the 1st and 15th of each month"."""
    days = _and([ordinal(d) for d in sorted(set(schedule.days_of_month))])
    if schedule.cadence == "monthly":
        every = "each month" if schedule.every == 1 else f"every {schedule.every} months"
        return f"on the {days} of {every}"
    return ""
