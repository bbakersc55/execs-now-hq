"""Periods, windows, roll-ups and status: the scorecard's arithmetic, with no
database in it.

- **Periods** (decision 3): a KPI's readings are daily, weekly, monthly or
  quarterly. Months and quarters are calendar ones; a week starts on the
  company's week start (Monday by default, Sunday available).
- **Windows**: what the reader asks to see: This week, This month, This
  quarter, Year to date, Last year, or dates of their own. A KPI's periods in
  a window are those that overlap it and have begun.
- **Roll-up**: a KPI's readings over a window combine by its rule: Sum,
  Average or Last. Its target combines the same way over the periods that
  have a reading, so a part-way window is judged against the part it covers.
- **Status** (decision 5): at or past target is On track; short by no more
  than the KPI's band (10% by default) is Behind; worse is Off track;
  flipped for lower-is-better; for a range, the distance outside the nearer
  end. No target, no status; a missing reading has none of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

DAILY, WEEKLY, MONTHLY, QUARTERLY = "daily", "weekly", "monthly", "quarterly"
SUM, AVERAGE, LAST = "sum", "average", "last"
ON_TRACK, BEHIND, OFF_TRACK = "on_track", "behind", "off_track"
STATUS_LABEL = {ON_TRACK: "On track", BEHIND: "Behind", OFF_TRACK: "Off track"}

WINDOWS = ("this_week", "this_month", "this_quarter", "year_to_date", "last_year", "custom")
WINDOW_LABEL = {"this_week": "This week", "this_month": "This month",
                "this_quarter": "This quarter", "year_to_date": "Year to date",
                "last_year": "Last year", "custom": "Custom dates"}

#: How many periods a tile's trend, the back of a tile and the grid show.
HISTORY = 13
#: The most a window's trend draws: a year of weeks.
MOST_DRAWN = 53

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def week_offset(week_start: str) -> int:
    """Python's weekday of the first day of the week: Monday 0, Sunday 6."""
    return 6 if week_start == "sunday" else 0


def start_of(day: date, cadence: str, week_start: str = "monday") -> date:
    """The first day of the period `day` is in."""
    if cadence == DAILY:
        return day
    if cadence == WEEKLY:
        return day - timedelta(days=(day.weekday() - week_offset(week_start)) % 7)
    if cadence == MONTHLY:
        return day.replace(day=1)
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def next_start(start: date, cadence: str) -> date:
    if cadence == DAILY:
        return start + timedelta(days=1)
    if cadence == WEEKLY:
        return start + timedelta(days=7)
    months = 1 if cadence == MONTHLY else 3
    month = start.month - 1 + months
    return date(start.year + month // 12, month % 12 + 1, 1)


def previous_start(start: date, cadence: str, week_start: str = "monday") -> date:
    return start_of(start - timedelta(days=1), cadence, week_start)


def end_of(start: date, cadence: str) -> date:
    return next_start(start, cadence) - timedelta(days=1)


def is_valid_start(day: date, cadence: str, week_start: str = "monday") -> bool:
    return start_of(day, cadence, week_start) == day


def closed(start: date, cadence: str, today: date) -> bool:
    """The period has ended: its last day is before today."""
    return end_of(start, cadence) < today


def starts_between(first: date, last: date, cadence: str, week_start: str = "monday"):
    """The starts of the periods overlapping first..last, oldest first."""
    out = []
    start = start_of(first, cadence, week_start)
    while start <= last:
        out.append(start)
        start = next_start(start, cadence)
    return out


def last_n(end_day: date, cadence: str, n: int, week_start: str = "monday"):
    """The starts of the `n` periods ending with the one `end_day` is in."""
    starts = [start_of(end_day, cadence, week_start)]
    while len(starts) < n:
        starts.append(previous_start(starts[-1], cadence, week_start))
    return list(reversed(starts))


def short_label(start: date, cadence: str) -> str:
    """For a column or a bar: "Oct 12", "Oct 2026", "Q4 2026"."""
    if cadence in (DAILY, WEEKLY):
        return f"{MONTHS[start.month - 1][:3]} {start.day}"
    if cadence == MONTHLY:
        return f"{MONTHS[start.month - 1][:3]} {start.year}"
    return f"Q{(start.month - 1) // 3 + 1} {start.year}"


def long_label(start: date, cadence: str) -> str:
    """In a sentence: "the week of October 12 to 18, 2026", "October 2026"."""
    if cadence == DAILY:
        return f"{MONTHS[start.month - 1]} {start.day}, {start.year}"
    if cadence == WEEKLY:
        end = end_of(start, cadence)
        to = f"{end.day}" if end.month == start.month else f"{MONTHS[end.month - 1]} {end.day}"
        return f"the week of {MONTHS[start.month - 1]} {start.day} to {to}, {end.year}"
    if cadence == MONTHLY:
        return f"{MONTHS[start.month - 1]} {start.year}"
    return f"Q{(start.month - 1) // 3 + 1} {start.year}"


def noun(cadence: str) -> str:
    return {DAILY: "day", WEEKLY: "week", MONTHLY: "month", QUARTERLY: "quarter"}[cadence]


@dataclass(frozen=True)
class Window:
    key: str
    first: date
    last: date

    @property
    def label(self) -> str:
        if self.key != "custom":
            return WINDOW_LABEL[self.key]
        return f"{self.first:%b} {self.first.day}, {self.first.year} to " \
               f"{self.last:%b} {self.last.day}, {self.last.year}"


class WindowInvalid(ValueError):
    pass


def window(key: str, today: date, week_start: str = "monday", *, first=None,
           last=None) -> Window:
    """The dates a window covers. A custom window's dates are given."""
    if key == "this_week":
        start = start_of(today, WEEKLY, week_start)
        return Window(key, start, end_of(start, WEEKLY))
    if key == "this_month":
        start = start_of(today, MONTHLY)
        return Window(key, start, end_of(start, MONTHLY))
    if key == "this_quarter":
        start = start_of(today, QUARTERLY)
        return Window(key, start, end_of(start, QUARTERLY))
    if key == "year_to_date":
        return Window(key, date(today.year, 1, 1), today)
    if key == "last_year":
        return Window(key, date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    if key == "custom":
        if first is None or last is None:
            raise WindowInvalid("Custom dates need a first and a last day.")
        if first > last:
            raise WindowInvalid("The first day comes before the last.")
        if (last - first).days > 3 * 366:
            raise WindowInvalid("A window is at most three years.")
        return Window(key, first, last)
    raise WindowInvalid(f"Not a window: {key}.")


def periods_in(win: Window, cadence: str, today: date, week_start: str = "monday"):
    """A KPI's periods in a window: those overlapping it that have begun."""
    return [s for s in starts_between(win.first, min(win.last, today), cadence, week_start)]


# ------------------------------------------------------------------ roll-up

def combine(values, rule: str):
    """Sum, Average or Last of the values in period order; None for none."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    if rule == SUM:
        return sum(values, Decimal(0))
    if rule == AVERAGE:
        return sum(values, Decimal(0)) / len(values)
    return values[-1]


def status(value, target, direction: str, band_pct, *, low=None, high=None):
    """On track, Behind, Off track or None (no target, or no value)."""
    if value is None:
        return None
    band = Decimal(band_pct) / 100
    if direction == "range":
        if low is None or high is None:
            return None
        if low <= value <= high:
            return ON_TRACK
        edge = low if value < low else high
        slack = abs(edge) * band
        return BEHIND if abs(value - edge) <= slack else OFF_TRACK
    if target is None:
        return None
    if direction == "lower":
        if value <= target:
            return ON_TRACK
        return BEHIND if value <= target + abs(target) * band else OFF_TRACK
    if value >= target:
        return ON_TRACK
    return BEHIND if value >= target - abs(target) * band else OFF_TRACK
