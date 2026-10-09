"""The demo's history is made by the app's own code, run at the time it would
have run. `at` moves the app's clock for the length of a block, so an invoice
sent in March 2025 has its number, its PDF, its payment and its line in the
books dated then, by the same functions that date them on a real day."""

from __future__ import annotations

import random
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Denver")


def moment(day: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE)


@contextmanager
def at(when):
    """The app's "now" is `when` inside this block. A date means 9:00 that
    morning in the practice's own time zone."""
    if not isinstance(when, datetime):
        when = moment(when)
    with mock.patch("django.utils.timezone.now", return_value=when):
        yield when


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def months(first: date, last: date):
    """The first of each month from `first` through the month `last` is in."""
    day = date(first.year, first.month, 1)
    while day <= last:
        yield day
        day = next_month(day)


def month_end(day: date) -> date:
    return next_month(day) - timedelta(days=1)


def workday(day: date) -> date:
    """The same day, or the Monday after a weekend."""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def dice(*key) -> random.Random:
    """The same numbers on every run for the same thing: a re-seed makes the
    same practice, apart from where "today" has moved to."""
    return random.Random("|".join(str(part) for part in key))
