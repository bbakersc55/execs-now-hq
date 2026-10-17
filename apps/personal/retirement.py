"""Retirement and investments (P6 M4 stop 3, decision 17): simple.

- **Balances** entered monthly or from a statement; no live feeds.
- **Contributions recognized from transfers:** a line out of one of the
  household's accounts whose description has the account's own text in it
  ("VANGUARD ROTH"), averaged over the last six complete months. Where no
  line shows them (a Solo 401(k) paid from the practice), the owner types a
  monthly amount.
- **On track or behind:** today's balance and the monthly contribution
  grown at the owner's assumed yearly return (6% unless they set another),
  compounded monthly, to the end of the target year, against the target.
  An estimate, with the disclaimer, and never advice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.personal.models import PersonalBalance, PersonalHolding, PersonalLine, PersonalMember
from apps.personal.services import PersonalError

#: Complete months contributions are averaged over.
CONTRIBUTION_MONTHS = 6
ESTIMATE = ("An estimate at the yearly return you assume, not a prediction and not "
            "financial advice. Confirm with your CPA or adviser.")


def _month(day: date, n: int) -> date:
    index = day.year * 12 + day.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def holdings(ledger, *, whose="all"):
    rows = PersonalHolding.objects.filter(ledger=ledger, closed_at__isnull=True)\
        .select_related("whose")
    if whose != "all":
        rows = rows.filter(whose=whose)
    return rows


def balance_of(holding, as_of: date | None = None) -> tuple[int, date | None]:
    rows = PersonalBalance.objects.filter(holding=holding)
    if as_of is not None:
        rows = rows.filter(on_date__lte=as_of)
    newest = rows.order_by("-on_date", "-created_at").first()
    return (newest.balance_cents, newest.on_date) if newest else (0, None)


def contributions(holding, today: date) -> dict:
    """`{"monthly_cents", "months": [{month, cents}], "recognized": bool}`:
    the lines that are its contributions, by month, over the last six
    complete months."""
    this = today.replace(day=1)
    months = [_month(this, -n) for n in range(CONTRIBUTION_MONTHS, 0, -1)]
    by = {m: 0 for m in months}
    text = holding.contribution_text.strip()
    if text:
        for on, cents in PersonalLine.objects.filter(
                ledger=holding.ledger, removed_at__isnull=True, account__isnull=False,
                direction="out", description__icontains=text, on_date__gte=months[0],
                on_date__lt=this).values_list("on_date", "amount_cents"):
            by[on.replace(day=1)] += cents
    found = sum(by.values())
    recognized = found > 0
    monthly = round(found / len(months)) if recognized else (holding.monthly_cents or 0)
    return {"monthly_cents": monthly, "recognized": recognized,
            "months": [{"month": m.isoformat()[:7], "cents": by[m]} for m in months]}


def project(start_cents: int, monthly_cents: int, rate_percent: Decimal, months: int) -> int:
    """Grown monthly at a twelfth of the yearly rate, with the contribution
    added at each month's end."""
    r = float(rate_percent) / 1200
    value = float(start_cents)
    for _ in range(max(0, months)):
        value = value * (1 + r) + monthly_cents
    return round(value)


def needed_monthly(start_cents: int, target_cents: int, rate_percent: Decimal,
                   months: int) -> int:
    """What a month would reach the target by then, at that return."""
    if months <= 0:
        return 0
    r = float(rate_percent) / 1200
    grown = start_cents * (1 + r) ** months
    gap = target_cents - grown
    if gap <= 0:
        return 0
    factor = months if r == 0 else ((1 + r) ** months - 1) / r
    return max(0, round(gap / factor))


def represent(holding, ledger, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    rate = ledger.assumed_return_percent
    cents, on = balance_of(holding)
    paid_in = contributions(holding, today)
    status = None
    if holding.target_cents and holding.target_year:
        months = (holding.target_year - today.year) * 12 + 12 - today.month
        reach = project(cents, paid_in["monthly_cents"], rate, months)
        need = needed_monthly(cents, holding.target_cents, rate, months)
        projection = []
        for n in range(0, months + 1, 12):
            projection.append({"on_date": _month(today, n).isoformat(),
                               "cents": project(cents, paid_in["monthly_cents"], rate, n)})
        if months % 12:
            projection.append({"on_date": date(holding.target_year, 12, 1).isoformat(),
                               "cents": reach})
        status = {
            "on_track": reach >= holding.target_cents, "projected_cents": reach,
            "months": months, "short_cents": max(0, holding.target_cents - reach),
            "needed_monthly_cents": need, "projection": projection}
    return {
        "id": str(holding.pk), "name": holding.name, "kind": holding.kind,
        "kind_label": holding.get_kind_display(),
        "whose": str(holding.whose_id) if holding.whose_id else None,
        "whose_name": holding.whose.name if holding.whose_id else "Joint",
        "balance_cents": cents, "balance_on": on.isoformat() if on else None,
        "target_cents": holding.target_cents, "target_year": holding.target_year,
        "contribution_text": holding.contribution_text,
        "typed_monthly_cents": holding.monthly_cents,
        "contributions": paid_in, "status": status,
        "history": [{"on_date": row.on_date.isoformat(), "cents": row.balance_cents}
                    for row in PersonalBalance.objects.filter(holding=holding)
                    .order_by("on_date")],
    }


def summary(ledger, today: date | None = None, *, whose="all") -> dict:
    rows = [represent(h, ledger, today) for h in holdings(ledger, whose=whose)]
    return {"assumed_return_percent": str(ledger.assumed_return_percent),
            "estimate": ESTIMATE, "holdings": rows,
            "total_cents": sum(r["balance_cents"] for r in rows)}


# --------------------------------------------------------------- changing

def _whose(ledger, pk):
    if not pk:
        return None
    found = PersonalMember.objects.filter(ledger=ledger, pk=pk, removed_at__isnull=True).first()
    if found is None:
        raise PersonalError("That person is not in your household.", status=404)
    return found


def _cents_or_none(value, what):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PersonalError(f"{what} is a whole number of cents, zero or more.")
    return value


@transaction.atomic
def save(ledger, *, holding=None, data: dict) -> PersonalHolding:
    made = holding is None
    holding = holding or PersonalHolding(ledger=ledger)
    if "name" in data or made:
        holding.name = " ".join(str(data.get("name") or "").split())[:120]
        if not holding.name:
            raise PersonalError("Give the account a name.")
    if "kind" in data or made:
        holding.kind = data.get("kind") or "retirement"
        if holding.kind not in PersonalHolding.Kind.values:
            raise PersonalError("kind is retirement or investment.")
    if "whose" in data:
        holding.whose = _whose(ledger, data["whose"])
    if "target_cents" in data:
        holding.target_cents = _cents_or_none(data["target_cents"], "The target")
    if "target_year" in data:
        year = data["target_year"]
        if year in (None, ""):
            holding.target_year = None
        elif isinstance(year, bool) or not isinstance(year, int) \
                or not timezone.localdate().year <= year <= 2100:
            raise PersonalError("The target year is this year or later.")
        else:
            holding.target_year = year
    if bool(holding.target_cents) != bool(holding.target_year):
        raise PersonalError("A target is an amount by a year: give both, or neither.")
    if "contribution_text" in data:
        holding.contribution_text = " ".join(str(data["contribution_text"] or "").split())[:120]
    if "monthly_cents" in data:
        holding.monthly_cents = _cents_or_none(data["monthly_cents"], "The monthly amount")
    holding.save()
    if made and data.get("balance_cents") not in (None, ""):
        add_balance(holding, on_date=timezone.localdate(), cents=data["balance_cents"])
    return holding


def add_balance(holding, *, on_date: date, cents) -> PersonalBalance:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        raise PersonalError("A balance is a whole number of cents, zero or more.")
    if on_date > timezone.localdate():
        raise PersonalError("A balance is for today or a day before.")
    return PersonalBalance.objects.create(ledger=holding.ledger, holding=holding,
                                          on_date=on_date, balance_cents=cents)


def set_return(ledger, value) -> None:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise PersonalError("The return is a percent, like 6.") from None
    if not Decimal("0") <= rate <= Decimal("20"):
        raise PersonalError("The return assumed is from 0% to 20% a year.")
    ledger.assumed_return_percent = rate.quantize(Decimal("0.01"))
    ledger.save(update_fields=["assumed_return_percent", "updated_at"])


def close(holding) -> None:
    holding.closed_at = timezone.now()
    holding.save(update_fields=["closed_at", "updated_at"])
