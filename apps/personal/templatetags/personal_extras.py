"""Filters for the personal side's PDF (P6 M4 decision 22)."""

from django import template

register = template.Library()


@register.filter
def money(cents):
    """Cents as dollars, "$1,234.56"; nothing for nothing."""
    if cents is None or cents == "":
        return ""
    cents = int(cents)
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


@register.filter
def long_date(value):
    """"2026-04-15" as "April 15, 2026"."""
    from datetime import date

    if not value:
        return ""
    day = value if isinstance(value, date) else date.fromisoformat(str(value))
    return f"{day:%B} {day.day}, {day.year}"
