"""Net worth (P6 M4 stop 3, decision 19): what the household has less what
it owes, as one line over time.

- **Assets:** the household's bank and cash accounts (from their lines),
  retirement and investments (their newest balance), and things owned with
  a value entered by hand (a home, a vehicle), each on its newest value on or
  before the day. No valuations fetched.
- **Less debts:** each debt's newest balance; a household card's balance is
  what its statements say is owed.
- **Equity:** a home (or a vehicle) against the loan named on it.
- **A Mixed card is the practice's account**, in its books, so it is not in
  the household's net worth; its personal lines are, as they are paid.

Month ends back to the first with any figure (at most twelve), then today.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from apps.personal import debts, reconcile, retirement
from apps.personal.models import (
    PersonalAccount, PersonalAsset, PersonalBalance, PersonalDebt, PersonalMember,
)
from apps.personal.services import PersonalError

MONTHS_SHOWN = 12


def _month(day: date, n: int) -> date:
    index = day.year * 12 + day.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def assets(ledger, *, whose="all"):
    rows = PersonalAsset.objects.filter(ledger=ledger, closed_at__isnull=True)\
        .select_related("whose", "debt")
    if whose != "all":
        rows = rows.filter(whose=whose)
    return rows


def value_of(asset, as_of: date | None = None) -> tuple[int, date | None]:
    rows = PersonalBalance.objects.filter(asset=asset)
    if as_of is not None:
        rows = rows.filter(on_date__lte=as_of)
    newest = rows.order_by("-on_date", "-created_at").first()
    return (newest.balance_cents, newest.on_date) if newest else (0, None)


def at(ledger, day: date, *, whose="all") -> dict:
    """Every figure on one day: `{"assets": [...], "debts": [...], "total"}`."""
    out_assets, out_debts = [], []
    accounts = PersonalAccount.objects.filter(ledger=ledger, closed_at__isnull=True)
    if whose != "all":
        accounts = accounts.filter(whose=whose)
    for account in accounts:
        if account.opening_on > day:
            continue
        cents = reconcile.balance(account, day)
        if account.kind == PersonalAccount.Kind.CARD:
            if not PersonalDebt.objects.filter(account=account, closed_at__isnull=True).exists():
                out_debts.append({"kind": "card", "name": account.name, "cents": cents})
            continue
        out_assets.append({"kind": "account", "name": account.name, "cents": cents})
    for holding in retirement.holdings(ledger, whose=whose):
        cents, on = retirement.balance_of(holding, day)
        if on is not None:
            out_assets.append({"kind": holding.kind, "name": holding.name, "cents": cents})
    for asset in assets(ledger, whose=whose):
        cents, on = value_of(asset, day)
        if on is not None:
            out_assets.append({"kind": asset.kind, "name": asset.name, "cents": cents})
    for debt in debts.open_debts(ledger, whose=whose):
        cents, on, _source = debts.balance_of(debt, day)
        if on is not None:
            out_debts.append({"kind": debt.kind, "name": debt.name, "cents": cents})
    have = sum(row["cents"] for row in out_assets)
    owe = sum(row["cents"] for row in out_debts)
    return {"assets": out_assets, "debts": out_debts, "assets_cents": have,
            "debts_cents": owe, "total_cents": have - owe}


def _first(ledger) -> date | None:
    dates = [PersonalAccount.objects.filter(ledger=ledger).aggregate(m=Min("opening_on"))["m"],
             PersonalBalance.objects.filter(ledger=ledger).aggregate(m=Min("on_date"))["m"]]
    dates = [d for d in dates if d is not None]
    return min(dates) if dates else None


def equity(ledger, today: date, *, whose="all") -> list[dict]:
    """A home (or anything owned) against the loan named on it."""
    out = []
    for asset in assets(ledger, whose=whose):
        value, on = value_of(asset, today)
        if asset.debt_id is None or on is None:
            continue
        owed, owed_on, _source = debts.balance_of(asset.debt, today)
        out.append({"id": str(asset.pk), "name": asset.name, "kind": asset.kind,
                    "value_cents": value, "value_on": on.isoformat(),
                    "debt": asset.debt.name, "owed_cents": owed,
                    "owed_on": owed_on.isoformat() if owed_on else None,
                    "equity_cents": value - owed})
    return out


def summary(ledger, today: date | None = None, *, whose="all") -> dict:
    today = today or timezone.localdate()
    first = _first(ledger)
    series = []
    if first is not None:
        this = today.replace(day=1)
        for n in range(-MONTHS_SHOWN, 0):
            end = _month(this, n + 1) - timedelta(days=1)
            if end < first:
                continue
            series.append({"on_date": end.isoformat(),
                           "cents": at(ledger, end, whose=whose)["total_cents"]})
    now = at(ledger, today, whose=whose)
    series.append({"on_date": today.isoformat(), "cents": now["total_cents"]})
    return {"as_of": today.isoformat(), **now, "series": series,
            "equity": equity(ledger, today, whose=whose),
            "change_cents": (now["total_cents"] - series[0]["cents"]) if len(series) > 1
            else None,
            "since": series[0]["on_date"] if len(series) > 1 else None,
            "things": [represent_asset(a) for a in assets(ledger, whose=whose)]}


def represent_asset(asset) -> dict:
    value, on = value_of(asset)
    return {"id": str(asset.pk), "name": asset.name, "kind": asset.kind,
            "kind_label": asset.get_kind_display(),
            "whose": str(asset.whose_id) if asset.whose_id else None,
            "debt": ({"id": str(asset.debt_id), "name": asset.debt.name}
                     if asset.debt_id else None),
            "value_cents": value, "value_on": on.isoformat() if on else None}


# --------------------------------------------------------------- changing

@transaction.atomic
def save_asset(ledger, *, asset=None, data: dict) -> PersonalAsset:
    made = asset is None
    asset = asset or PersonalAsset(ledger=ledger)
    if "name" in data or made:
        asset.name = " ".join(str(data.get("name") or "").split())[:120]
        if not asset.name:
            raise PersonalError("Say what it is.")
    if "kind" in data or made:
        asset.kind = data.get("kind") or "other"
        if asset.kind not in PersonalAsset.Kind.values:
            raise PersonalError("kind is home, vehicle or other.")
    if "whose" in data:
        asset.whose = None
        if data["whose"]:
            asset.whose = PersonalMember.objects.filter(
                ledger=ledger, pk=data["whose"], removed_at__isnull=True).first()
            if asset.whose is None:
                raise PersonalError("That person is not in your household.", status=404)
    if "debt" in data:
        asset.debt = None
        if data["debt"]:
            asset.debt = PersonalDebt.objects.filter(ledger=ledger, pk=data["debt"]).first()
            if asset.debt is None:
                raise PersonalError("There is no such debt.", status=404)
    asset.save()
    if "value_cents" in data and data["value_cents"] not in (None, ""):
        add_value(asset, on_date=_day(data.get("value_on")) or timezone.localdate(),
                  cents=data["value_cents"])
    elif made:
        raise PersonalError("Give it a value.")
    return asset


def _day(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PersonalError("A date is YYYY-MM-DD.") from None


def add_value(asset, *, on_date: date, cents) -> PersonalBalance:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        raise PersonalError("A value is a whole number of cents, zero or more.")
    if on_date > timezone.localdate():
        raise PersonalError("A value is for today or a day before.")
    return PersonalBalance.objects.create(ledger=asset.ledger, asset=asset, on_date=on_date,
                                          balance_cents=cents)


def close_asset(asset) -> None:
    asset.closed_at = timezone.now()
    asset.save(update_fields=["closed_at", "updated_at"])
