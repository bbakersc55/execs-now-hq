"""A goal's figures the way a sentence says them (owner, 2026-10-26): "54",
not "54.0000"; "1,250.5"; and, by the goal's unit as a KPI's kind would, "54%"
and "$1,200". The API keeps the stored decimals for the forms that edit them;
everything a person reads goes through here (and `goalFigure` in the app)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

#: Units read as a kind: a percent sits on the number, money before it.
PERCENT = {"%", "percent", "pct"}
MONEY = {"$", "usd", "dollars"}


def number_text(value) -> str:
    if value is None or value == "":
        return ""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    d = d.quantize(Decimal("0.01")).normalize() if d != d.to_integral_value() \
        else d.to_integral_value()
    text = f"{d:,f}"
    return text


def figure(value, unit: str = "") -> str:
    """One figure with its unit where the unit is a kind (% or $)."""
    text = number_text(value)
    if not text:
        return ""
    kind = (unit or "").strip().lower()
    if kind in PERCENT:
        return f"{text}%"
    if kind in MONEY:
        return f"-${text[1:]}" if text.startswith("-") else f"${text}"
    return text


def unit_after(unit: str) -> str:
    """The unit written after the figures: none when it is already on them."""
    kind = (unit or "").strip().lower()
    return "" if kind in PERCENT | MONEY else (unit or "")
