"""What the books say (`docs/p5_finance_accounting.md` §5): the P&L, the
balance view, the dashboard's three figures and the CPA export.

Everything here reads; nothing writes. Removed entries are never counted.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from django.db.models import Q, Sum

from apps.finance.models import FinanceAccount, FinanceCategory, FinanceEntry
from apps.finance.services import settings_for

K = FinanceEntry.Kind
D = FinanceEntry.Direction
T = FinanceCategory.Type

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def live(tenant):
    return FinanceEntry.all_objects.filter(tenant=tenant, removed_at__isnull=True)


# ----------------------------------------------------------------------- P&L

def pnl(tenant, *, year: int, by: str = "month") -> dict:
    """Income and expenses for a calendar year, by month or by quarter (F10).
    Cash basis: an entry counts in the period it is dated. Transfers, owner
    money and tax held are not earnings or costs and are not here. Entries
    with no category are counted beside it, never silently dropped."""
    if by not in ("month", "quarter"):
        by = "month"
    periods = 12 if by == "month" else 4
    labels = list(MONTHS) if by == "month" else ["Q1", "Q2", "Q3", "Q4"]
    index = (lambda month: month - 1) if by == "month" else (lambda month: (month - 1) // 3)
    settings_for(tenant)            # makes the chart, for a practice's first look

    earned = live(tenant).filter(kind__in=FinanceEntry.EARNED, on_date__year=year)
    cells: dict = {}
    for row in (earned.filter(category__isnull=False)
                .values("category_id", "on_date__month").annotate(total=Sum("amount_cents"))):
        amounts = cells.setdefault(row["category_id"], [0] * periods)
        amounts[index(row["on_date__month"])] += row["total"]

    sections = {}
    for kind in (T.INCOME, T.EXPENSE):
        rows = []
        for category in FinanceCategory.all_objects.filter(tenant=tenant, type=kind).order_by(
                "position", "name"):
            amounts = cells.get(category.pk)
            # An archived category shows only where it has figures.
            if amounts is None and category.archived_at is not None:
                continue
            amounts = amounts or [0] * periods
            rows.append({"id": str(category.pk), "name": category.name,
                         "cpa_code": category.cpa_code, "amounts": amounts,
                         "total": sum(amounts)})
        totals = [sum(row["amounts"][i] for row in rows) for i in range(periods)]
        sections[kind] = {"rows": rows, "totals": totals, "total": sum(totals)}

    income, expense = sections[T.INCOME], sections[T.EXPENSE]
    net = [income["totals"][i] - expense["totals"][i] for i in range(periods)]
    loose_rows = earned.filter(category__isnull=True)
    return {
        "year": year, "by": by, "periods": labels,
        "income": income, "expenses": expense,
        "net": net, "net_total": sum(net),
        "uncategorized": {
            "count": loose_rows.count(),
            "amount_cents": loose_rows.aggregate(total=Sum("amount_cents"))["total"] or 0},
        "years": years(tenant, year),
    }


def years(tenant, also: int) -> list[int]:
    found = {day.year for day in live(tenant).dates("on_date", "year")}
    return sorted(found | {also}, reverse=True)


def pnl_csv(report: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    plain = lambda cents: f"{cents / 100:.2f}"  # noqa: E731
    writer.writerow([f"Profit and loss, {report['year']}, cash basis"])
    writer.writerow(["Category", "CPA code", *report["periods"], "Total"])
    for title, section in (("Income", report["income"]), ("Expenses", report["expenses"])):
        writer.writerow([title])
        for row in section["rows"]:
            writer.writerow([row["name"], row["cpa_code"],
                             *[plain(a) for a in row["amounts"]], plain(row["total"])])
        writer.writerow([f"Total {title.lower()}", "",
                         *[plain(a) for a in section["totals"]], plain(section["total"])])
    writer.writerow(["Net", "", *[plain(a) for a in report["net"]],
                     plain(report["net_total"])])
    loose = report["uncategorized"]
    if loose["count"]:
        writer.writerow([])
        writer.writerow([f"{loose['count']} entries with no category are not in these "
                         f"figures: {plain(loose['amount_cents'])}"])
    return out.getvalue()


# ------------------------------------------------------------ the balance view

def _flow(entries, account) -> int:
    """Money into an account less money out of it."""
    def total(filtered):
        return filtered.aggregate(total=Sum("amount_cents"))["total"] or 0

    through = entries.filter(account=account)
    return (total(through.exclude(kind=K.TRANSFER).filter(direction=D.IN))
            - total(through.exclude(kind=K.TRANSFER).filter(direction=D.OUT))
            - total(through.filter(kind=K.TRANSFER))
            + total(entries.filter(kind=K.TRANSFER, to_account=account)))


def balance(tenant, *, as_of: date) -> dict:
    """Cash, cards and tax held, as of a day. Not a balance sheet: it has no
    fixed assets, no loans and no retained earnings, and says so."""
    from apps.billing import services as billing
    from apps.billing.models import ClientInvoice

    entries = live(tenant).filter(on_date__lte=as_of)
    cash, cards = [], []
    for account in FinanceAccount.all_objects.filter(tenant=tenant).order_by("kind", "name"):
        if account.opening_on > as_of:
            continue
        # Entries before the opening balance are already inside it.
        flow = _flow(entries.filter(on_date__gte=account.opening_on), account)
        is_card = account.kind == FinanceAccount.Kind.CARD
        amount = account.opening_balance_cents - flow if is_card \
            else account.opening_balance_cents + flow
        if account.closed_at is not None and amount == 0:
            continue
        (cards if is_card else cash).append({
            "id": str(account.pk), "name": account.name, "kind": account.kind,
            "last4": account.last4, "amount_cents": amount,
            "closed": account.closed_at is not None})

    # Invoice payments not yet placed in an account: shown once, never lost.
    loose = entries.filter(account__isnull=True, direction=D.IN)
    unplaced = loose.aggregate(total=Sum("amount_cents"))["total"] or 0
    held = entries.filter(kind=K.HELD)
    tax_held = ((held.filter(direction=D.IN).aggregate(t=Sum("amount_cents"))["t"] or 0)
                - (held.filter(direction=D.OUT).aggregate(t=Sum("amount_cents"))["t"] or 0))
    cash_total = sum(row["amount_cents"] for row in cash) + unplaced
    owed_total = sum(row["amount_cents"] for row in cards) + tax_held
    owed_to_you = billing.totals(
        ClientInvoice.all_objects.filter(tenant=tenant), today=as_of)
    return {
        "as_of": as_of.isoformat(), "cash": cash,
        "unplaced_cents": unplaced, "unplaced_count": loose.count(),
        "cash_total_cents": cash_total, "cards": cards, "tax_held_cents": tax_held,
        "owed_total_cents": owed_total, "net_cents": cash_total - owed_total,
        # Beside it, not in it: cash basis counts an invoice when it is paid.
        "owed_to_you_cents": owed_to_you["outstanding_cents"],
    }


# ---------------------------------------------------------------- the dashboard

def this_month(tenant, today: date) -> dict:
    """Revenue, expenses and margin for the month so far (§5.3)."""
    month = live(tenant).filter(on_date__year=today.year, on_date__month=today.month,
                                on_date__lte=today)
    sums = month.aggregate(
        revenue=Sum("amount_cents", filter=Q(kind=K.INCOME)),
        expenses=Sum("amount_cents", filter=Q(kind=K.EXPENSE)))
    revenue, expenses = sums["revenue"] or 0, sums["expenses"] or 0
    return {
        "revenue_cents": revenue, "expenses_cents": expenses,
        "net_cents": revenue - expenses,
        # A share of revenue, to one decimal; nothing to divide by is no figure.
        "margin_percent": round((revenue - expenses) * 1000 / revenue) / 10 if revenue
        else None,
        "month": MONTHS[today.month - 1], "year": today.year,
    }


# -------------------------------------------------------------- the CPA export

def _in_range(tenant, start: date, end: date):
    return (live(tenant).filter(on_date__gte=start, on_date__lte=end)
            .select_related("category", "account", "to_account", "client_company",
                            "client_payment__invoice")
            .order_by("on_date", "created_at"))


def export_entries(tenant, *, start: date, end: date) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Kind", "Category", "CPA code", "Description", "Payee or payer",
                     "Account", "To account", "Money in", "Money out", "Client company",
                     "Invoice", "Reference", "Source"])
    plain = lambda cents: f"{cents / 100:.2f}"  # noqa: E731
    for entry in _in_range(tenant, start, end):
        category = entry.category
        invoice = entry.client_payment.invoice.number if entry.client_payment_id else ""
        writer.writerow([
            entry.on_date.isoformat(), entry.get_kind_display(),
            category.name if category else ("" if entry.kind == K.TRANSFER
                                            else "(no category yet)"),
            category.cpa_code if category else "", entry.description, entry.counterparty,
            entry.account.name if entry.account_id else "",
            entry.to_account.name if entry.to_account_id else "",
            plain(entry.amount_cents) if entry.direction == D.IN else "",
            plain(entry.amount_cents) if entry.direction == D.OUT else "",
            entry.client_company.name if entry.client_company_id else "",
            invoice, entry.reference, entry.get_source_display()])
    return out.getvalue()


def export_summary(tenant, *, start: date, end: date) -> str:
    """Each category with its total for the range, and net. It adds up to the
    entries file: the same rows, grouped."""
    out = io.StringIO()
    writer = csv.writer(out)
    plain = lambda cents: f"{cents / 100:.2f}"  # noqa: E731
    writer.writerow([f"Summary by category, {start.isoformat()} to {end.isoformat()}, "
                     "cash basis"])
    writer.writerow(["Type", "Category", "CPA code", "Total"])
    earned = _in_range(tenant, start, end).filter(kind__in=FinanceEntry.EARNED)
    by_category = {row["category_id"]: row["total"] for row in
                   earned.order_by().values("category_id").annotate(
                       total=Sum("amount_cents"))}
    totals = {}
    for kind, title in ((T.INCOME, "Income"), (T.EXPENSE, "Expense")):
        totals[kind] = 0
        for category in FinanceCategory.all_objects.filter(tenant=tenant, type=kind).order_by(
                "position", "name"):
            amount = by_category.get(category.pk)
            if amount:
                writer.writerow([title, category.name, category.cpa_code, plain(amount)])
                totals[kind] += amount
        loose = earned.filter(category__isnull=True, kind=kind).aggregate(
            total=Sum("amount_cents"))["total"] or 0
        if loose:
            writer.writerow([title, "(no category yet)", "", plain(loose)])
            totals[kind] += loose
    writer.writerow(["", "Total income", "", plain(totals[T.INCOME])])
    writer.writerow(["", "Total expenses", "", plain(totals[T.EXPENSE])])
    writer.writerow(["", "Net", "", plain(totals[T.INCOME] - totals[T.EXPENSE])])
    return out.getvalue()
