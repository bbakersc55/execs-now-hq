"""The plan's periods: a horizon's period containing a day, the next and the
last, and how each is said.

- **Year and quarter** follow the company's fiscal-year start month (default
  January): a July company's year runs July to June, its quarters July to
  September, and so on.
- **Month** is the calendar month.
- **Week** starts on the company's week start, the scorecard's own (Monday
  unless the scorecard says Sunday), so the sprint and the scorecard agree.
- **The picture** is three years from the fiscal year it was set in.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from .models import Horizon

MONTHS = list(calendar.month_name)[1:]


def fiscal_start(company) -> int:
    month = getattr(company, "fiscal_year_start", None) or 1
    return month if 1 <= month <= 12 else 1


def week_start(company) -> str:
    from apps.scorecard.models import Scorecard

    found = Scorecard.all_objects.filter(company_id=company.pk).values_list(
        "week_start", flat=True).first()
    return found or "monday"


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _year_start(day: date, first_month: int) -> date:
    year = day.year if day.month >= first_month else day.year - 1
    return date(year, first_month, 1)


def start_of(horizon: str, day: date, company) -> date:
    first = fiscal_start(company)
    if horizon in (Horizon.PICTURE, Horizon.YEAR):
        return _year_start(day, first)
    if horizon == Horizon.QUARTER:
        year = _year_start(day, first)
        months = (day.year - year.year) * 12 + day.month - year.month
        return _add_months(year, months - months % 3)
    if horizon == Horizon.MONTH:
        return day.replace(day=1)
    if horizon == Horizon.WEEK:
        first_day = 6 if week_start(company) == "sunday" else 0
        return day - timedelta(days=(day.weekday() - first_day) % 7)
    raise ValueError(horizon)


def _length_months(horizon: str) -> int:
    return {Horizon.PICTURE: 36, Horizon.YEAR: 12, Horizon.QUARTER: 3,
            Horizon.MONTH: 1}[horizon]


def end_of(horizon: str, start: date, company=None) -> date:
    if horizon == Horizon.WEEK:
        return start + timedelta(days=6)
    return _add_months(start, _length_months(horizon)) - timedelta(days=1)


def next_start(horizon: str, start: date, company=None) -> date:
    if horizon == Horizon.WEEK:
        return start + timedelta(days=7)
    return _add_months(start, _length_months(horizon))


def previous_start(horizon: str, start: date, company=None) -> date:
    if horizon == Horizon.WEEK:
        return start - timedelta(days=7)
    return _add_months(start, -_length_months(horizon))


def _month(day: date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


def label(horizon: str, start: date, company=None) -> str:
    """"Through December 2028", "2026", "July 2026 to June 2027", "October to
    December 2026", "November 2026", "Week of November 9"."""
    end = end_of(horizon, start)
    if horizon == Horizon.PICTURE:
        return f"Through {_month(end)}"
    if horizon == Horizon.YEAR:
        return str(start.year) if start.month == 1 else f"{_month(start)} to {_month(end)}"
    if horizon == Horizon.QUARTER:
        if start.year == end.year:
            return f"{MONTHS[start.month - 1]} to {_month(end)}"
        return f"{_month(start)} to {_month(end)}"
    if horizon == Horizon.MONTH:
        return _month(start)
    return f"Week of {MONTHS[start.month - 1]} {start.day}"


def short(horizon: str, start: date) -> str:
    """For a sentence: "the week of November 9", "November", "the quarter
    from October to December 2026"."""
    if horizon == Horizon.WEEK:
        return f"the week of {MONTHS[start.month - 1]} {start.day}"
    if horizon == Horizon.MONTH:
        return MONTHS[start.month - 1]
    if horizon == Horizon.QUARTER:
        return f"the quarter from {label(horizon, start)}"
    return label(horizon, start)


def below(horizon: str) -> str | None:
    from .models import ORDER

    i = list(ORDER).index(horizon)
    return ORDER[i + 1] if i + 1 < len(ORDER) else None


def above(horizon: str) -> str | None:
    from .models import ORDER

    i = list(ORDER).index(horizon)
    return ORDER[i - 1] if i > 0 else None
