"""The cash forecast (`docs/p6_m2_cash_forecast.md`), stop 1: known and
regular lines, the card, the floor.

"How much cash is the practice likely to have, week by week, if clients pay
as they have been paying and its costs go on as they have been going."

What this module keeps true:

- **It is arithmetic on the books.** Every figure is a sum of lines, and
  every line says where it came from. Nothing here asks Claude for anything.
- **Nothing is stored but the floor.** The forecast is worked out from the
  books and the invoices each time it is asked for, so it cannot disagree
  with them (M2-16).
- **Only closed months are read for what is regular** (M1's closes; a month
  "locked before month close began" is not one). With fewer than two, the
  forecast is the practice's invoices and says so.
- **It reads and never writes** the books or the invoices.
- **Each week's end is its start plus money in less money out, and is the
  next week's start.**
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from statistics import median

from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.finance import reconcile, reports
from apps.finance.models import (
    FinanceAccount, FinanceEntry, FinanceForecastSettings, FinanceReconciliation,
)
from apps.finance.services import FinanceError, _cents, audit

K = FinanceEntry.Kind
D = FinanceEntry.Direction
CARD = FinanceAccount.Kind.CARD

#: The weekly view goes this far: the longest of the brief's three (30, 90
#: and 180 days), in weeks. 90 days is M2-1's 13 weeks, and is what opens.
VIEWS = {"30": 5, "90": 13, "180": 26}
WEEKS = max(VIEWS.values())
MONTHS = 12
#: An account with no entry for this long starts the forecast from a stale
#: balance, and the screen says so (M2-2).
STALE_DAYS = 14
#: An invoice this long past due is hoped for, not forecast (M2-5).
LEFT_OUT_AFTER_DAYS = 60
#: A client's own payment record is used with this many paid invoices (M2-4).
PAID_INVOICES_TO_GO_ON = 3
#: The days an estimated tax payment is due.
TAX_DATES = ((1, 15), (4, 15), (6, 15), (9, 15))
#: Closed months needed before anything is forecast from history.
CLOSED_MONTHS_NEEDED = 2

NOT_READY = ("Close two months and your regular costs will be forecast from them. Until "
             "then this is only your invoices.")


# -------------------------------------------------------------------- dates

def _add_months(day: date, months: int, day_of_month=None) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    wanted = day_of_month or day.day
    return date(year, month + 1, min(wanted, calendar.monthrange(year, month + 1)[1]))


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _ordinal(day: int) -> str:
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _long(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


# ----------------------------------------------------------- where it starts

def _accounts(tenant, today: date) -> tuple[list[dict], int]:
    """Cash today: every open bank and cash account, as the balance view has
    it. A card is not cash. Each says how fresh it is."""
    rows, total = [], 0
    for account in FinanceAccount.all_objects.filter(
            tenant=tenant, closed_at__isnull=True).exclude(kind=CARD).order_by("kind", "name"):
        if account.opening_on > today:
            continue
        cents = reports.account_balance(tenant, account, today)
        last = FinanceEntry.all_objects.filter(
            Q(account=account) | Q(to_account=account), tenant=tenant,
            removed_at__isnull=True, on_date__lte=today).aggregate(m=Max("on_date"))["m"]
        through = FinanceReconciliation.all_objects.filter(
            tenant=tenant, account=account,
            state=FinanceReconciliation.State.FINISHED).aggregate(m=Max("statement_on"))["m"]
        rows.append({
            "id": str(account.pk), "name": account.name, "kind": account.kind,
            "amount_cents": cents,
            "last_entry_on": last.isoformat() if last else None,
            "reconciled_through": through.isoformat() if through else None,
            "stale": last is None or (today - last).days > STALE_DAYS})
        total += cents
    return rows, total


def _unplaced(tenant, today: date) -> int:
    """Invoice payments received and not yet placed in an account: cash the
    practice has, as the balance view counts it."""
    return FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, account__isnull=True, direction=D.IN,
        on_date__lte=today).aggregate(t=Sum("amount_cents"))["t"] or 0


# -------------------------------------------------------------- known lines

def _lateness(tenant, today: date) -> dict:
    """`{company id: days}`: how long after the due date each client has paid,
    the median over their paid invoices of the last 12 months. Only with
    enough paid invoices to go on, and never earlier than the due date."""
    from apps.billing.models import ClientInvoice, ClientPayment

    since = _add_months(today, -12)
    paid = (ClientPayment.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, invoice__status=ClientInvoice.Status.PAID,
        invoice__client_company__isnull=False)
        .values("invoice_id", "invoice__client_company_id", "invoice__due_date")
        .annotate(last=Max("paid_on")).filter(last__gte=since))
    days: dict = {}
    for row in paid:
        days.setdefault(row["invoice__client_company_id"], []).append(
            (row["last"] - row["invoice__due_date"]).days)
    return {company: max(0, round(median(found))) for company, found in days.items()
            if len(found) >= PAID_INVOICES_TO_GO_ON}


def _habit(late) -> str:
    if late is None:
        return "on its due date (fewer than 3 paid invoices to go on)"
    if late == 0:
        return "on its due date, as this client usually pays"
    return f"{late} day{'s' if late != 1 else ''} after its due date, as this client usually pays"


def _known(tenant, today: date, end: date) -> tuple[list[dict], list[dict]]:
    """Invoices sent and unpaid, invoices not yet sent, and the invoices each
    recurring schedule will write. Returns `(lines, left out)`."""
    from apps.billing import money
    from apps.billing import services as billing
    from apps.billing.models import ClientInvoice, ClientInvoiceSchedule

    S = ClientInvoice.Status
    late = _lateness(tenant, today)
    lines, left_out = [], []
    invoices = (ClientInvoice.all_objects.filter(
        tenant=tenant, status__in=(S.SENT, S.PARTIALLY_PAID, S.READY, S.DRAFT))
        .select_related("client_company", "contact").order_by("due_date", "created_at"))
    for invoice in invoices:
        sent = invoice.status in ClientInvoice.OPEN
        amount = invoice.balance_cents if sent else invoice.total_cents
        if amount <= 0:
            continue
        who = invoice.client_company.name if invoice.client_company_id \
            else str(invoice.contact)
        habit = late.get(invoice.client_company_id)
        name = f"Invoice {invoice.number}" if invoice.number else "A draft invoice"
        if sent and (today - invoice.due_date).days > LEFT_OUT_AFTER_DAYS:
            left_out.append({
                "id": str(invoice.pk), "label": f"{who}: {name}", "amount_cents": amount,
                "due_date": invoice.due_date.isoformat(),
                "days_overdue": (today - invoice.due_date).days,
                "link": f"/invoices/{invoice.pk}"})
            continue
        # One not yet sent is counted as if sent today (M2-3).
        due = invoice.due_date if sent else max(invoice.due_date, today)
        expected = max(due + timedelta(days=habit or 0), today)
        if expected > end:
            continue
        lines.append({
            "id": f"invoice:{invoice.pk}", "kind": "known", "direction": D.IN,
            "amount_cents": amount, "on_date": expected, "label": f"{who}: {name}",
            "detail": (("Due " if sent else "Not sent yet. As if sent today, due ")
                       + f"{_long(due)}; forecast {_habit(habit)}."
                       + (" Part paid: this is what is left." if invoice.paid_cents and sent
                          else "")),
            "cadence": "", "category": "", "link": f"/invoices/{invoice.pk}",
            "counted": True, "on_card": ""})
    terms = billing.settings_for(tenant).terms_days
    for schedule in (ClientInvoiceSchedule.all_objects.filter(tenant=tenant, is_active=True)
                     .select_related("client_company")):
        amount = sum(money.line_amount(billing.Decimal(str(line["quantity"])),
                                       line["unit_price_cents"])
                     for line in schedule.lines)
        if amount <= 0:
            continue
        habit = late.get(schedule.client_company_id)
        written = schedule.next_on
        while written <= end and (schedule.ends_on is None or written <= schedule.ends_on):
            due = written + timedelta(days=terms)
            expected = max(due + timedelta(days=habit or 0), today)
            if expected <= end:
                lines.append({
                    "id": f"schedule:{schedule.pk}:{written.isoformat()}", "kind": "known",
                    "direction": D.IN, "amount_cents": amount, "on_date": expected,
                    "label": f"{schedule.client_company.name}: recurring invoice",
                    "detail": (f"Its schedule writes it on {_long(written)}, due "
                               f"{_long(due)}; forecast {_habit(habit)}."),
                    "cadence": "monthly", "category": "", "link": "/invoices",
                    "counted": True, "on_card": ""})
            written = billing._next_month(written, schedule.day_of_month)
    return lines, left_out


# ------------------------------------------------------------ regular lines

def _who(entry) -> tuple:
    """Who a regular line is to or from: the person named, else the payee as
    typed, else what it was called, with the numbers a bank adds taken out."""
    if entry.payee_contact_id:
        return ("contact", str(entry.payee_contact_id))
    text = entry.counterparty or entry.description
    return ("text", " ".join(re.sub(r"\d+", " ", text.lower()).split()))


def _name(entry) -> str:
    return (entry.counterparty or entry.description or entry.get_kind_display()).strip()


class _Pattern:
    """One category and payee, as the closed months show it."""

    def __init__(self, entry):
        self.entry = entry                       # the newest, for its names
        self.by_month: dict = {}                 # month -> cents
        self.days: dict = {}                     # month -> day of the month
        self.last_on = entry.on_date
        self.last_amount = entry.amount_cents

    def add(self, entry) -> None:
        month = entry.on_date.replace(day=1)
        self.by_month[month] = self.by_month.get(month, 0) + entry.amount_cents
        self.days.setdefault(month, entry.on_date.day)
        if entry.on_date >= self.last_on:
            self.entry, self.last_on, self.last_amount = entry, entry.on_date, \
                entry.amount_cents


def _patterns(tenant, months: list[date]) -> dict:
    """Every category-and-payee in these closed months, with what it came to
    in each. Invoices are known lines, transfers are not earnings or costs,
    tax held is someone else's money, and estimated tax has its own dates."""
    if not months:
        return {}
    entries = (FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, on_date__gte=months[0],
        on_date__lte=reconcile.month_end(months[-1]), account__isnull=False,
        kind__in=(K.EXPENSE, K.INCOME, K.OWNER), estimated_tax="")
        .exclude(source=FinanceEntry.Source.INVOICE)
        .exclude(kind=K.OWNER, direction=D.IN)
        .select_related("category", "category__parent", "account")
        .order_by("on_date", "created_at"))
    closed = set(months)
    found: dict = {}
    for entry in entries:
        if entry.on_date.replace(day=1) not in closed:
            continue                              # an open month between two closed ones
        key = (entry.kind, entry.direction, entry.category_id, entry.account_id,
               *_who(entry))
        found.setdefault(key, _Pattern(entry)).add(entry)
    return found


def _entered_since(tenant, after: date) -> dict:
    """`{(pattern key, month)}` for what has been entered since the last
    closed month: a regular cost already in the books for a month is not
    forecast again for it."""
    seen = set()
    for entry in FinanceEntry.all_objects.filter(
            tenant=tenant, removed_at__isnull=True, on_date__gt=after,
            account__isnull=False, kind__in=(K.EXPENSE, K.INCOME, K.OWNER)):
        key = (entry.kind, entry.direction, entry.category_id, entry.account_id,
               *_who(entry))
        seen.add((key, entry.on_date.replace(day=1)))
    return seen


def _category_name(category) -> str:
    if category is None:
        return ""
    return f"{category.parent.name}: {category.name}" if category.parent_id else category.name


def _regular(tenant, today: date, end: date, closed: list[date]) -> tuple[list, list]:
    """Regular lines at each cadence (M2-15), and the "likely annual" items
    that are listed and not forecast. Returns `(lines, likely annual)`."""
    last3, last12 = closed[-3:], closed[-12:]
    # Far enough back to see what was last seen 11 to 13 months ago.
    window = [m for m in closed if _months_between(m, today.replace(day=1)) <= 14]
    patterns = _patterns(tenant, window)
    entered = _entered_since(tenant, reconcile.month_end(closed[-1]))
    this_month = today.replace(day=1)
    lines, annual = [], []

    def line(key, pattern, on: date, cents: int, cadence: str, detail: str) -> dict:
        entry = pattern.entry
        card = entry.account.kind == CARD
        return {
            "id": "regular:" + "|".join(str(part or "") for part in key) + f":{on}",
            "kind": "regular", "direction": entry.direction, "amount_cents": cents,
            "on_date": on, "label": _name(entry), "detail": detail, "cadence": cadence,
            "category": _category_name(entry.category),
            "link": (f"/finance?category={entry.category_id}&subs=0"
                     if entry.category_id else "/finance"),
            # A charge on a card is not cash until the card is paid.
            "counted": not card, "on_card": str(entry.account_id) if card else ""}

    for key, pattern in patterns.items():
        in3 = [m for m in last3 if m in pattern.by_month]
        in12 = sorted(m for m in last12 if m in pattern.by_month)
        if len(in3) >= 2:
            amounts = [pattern.by_month[m] for m in in3]
            fixed = len(set(amounts)) == 1
            cents = amounts[0] if fixed else int(median(amounts))
            day = int(median(pattern.days[m] for m in in3))
            detail = (f"{_money(cents)} on the {_ordinal(day)}, monthly: "
                      + ("the same amount" if fixed else "the median")
                      + f" of {len(in3)} of the last {len(last3)} closed months.")
            month = reconcile.next_month(closed[-1])
            while month <= end:
                on = _add_months(month, 0, day)
                if month < this_month or (key, month) in entered:
                    pass      # an earlier open month, or already in the books for it
                elif max(on, today) <= end:
                    lines.append(line(key, pattern, max(on, today), cents, "monthly",
                                      detail))
                month = reconcile.next_month(month)
            continue
        gaps = [_months_between(a, b) for a, b in zip(in12, in12[1:])]
        if len(in12) >= 2 and all(2 <= gap <= 4 for gap in gaps):
            cents, day = pattern.last_amount, pattern.last_on.day
            detail = (f"{_money(cents)}, quarterly: seen {len(in12)} times in the last "
                      f"{len(last12)} closed months, about three months apart, last on "
                      f"{_long(pattern.last_on)}.")
            on = _add_months(pattern.last_on, 3, day)
            while on <= end:
                if on >= today and (key, on.replace(day=1)) not in entered:
                    lines.append(line(key, pattern, on, cents, "quarterly", detail))
                on = _add_months(on, 3, day)
            continue
        months_ago = _months_between(pattern.last_on.replace(day=1), this_month)
        seen = [m for m in window if m in pattern.by_month]
        if len(seen) == 1 and 11 <= months_ago <= 13 \
                and not any(found == key for found, _month in entered):
            entry = pattern.entry
            annual.append({
                "id": "annual:" + "|".join(str(part or "") for part in key),
                "label": _name(entry), "category": _category_name(entry.category),
                "direction": entry.direction, "amount_cents": pattern.last_amount,
                "last_on": pattern.last_on.isoformat(),
                "likely_on": _add_months(pattern.last_on, 12).isoformat(),
                "detail": (f"{_money(pattern.last_amount)} on {_long(pattern.last_on)}, "
                           "and not since. Likely annual: it is not in the forecast "
                           "until you confirm it.")})
    return lines, sorted(annual, key=lambda row: row["likely_on"])


def _estimated_tax(tenant, today: date, end: date, closed: list[date]) -> list[dict]:
    """Marked estimated tax payments are quarterly by definition: the last
    amount of each mark, on the dates they are due."""
    last12 = closed[-12:]
    marked = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
        account__isnull=False, on_date__gte=last12[0],
        on_date__lte=reconcile.month_end(last12[-1])).exclude(estimated_tax="") \
        .select_related("account").order_by("on_date", "created_at")
    latest = {}
    for entry in marked:
        if entry.on_date.replace(day=1) in set(last12):
            latest[entry.estimated_tax] = entry
    # One already paid for a due date (within a fortnight of it) is not forecast.
    paid = list(FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
        on_date__gt=reconcile.month_end(closed[-1])).exclude(estimated_tax="")
        .values_list("estimated_tax", "on_date"))
    lines = []
    for mark, entry in sorted(latest.items()):
        for year in range(today.year, end.year + 1):
            for month, day in TAX_DATES:
                due = date(year, month, day)
                if not today <= due <= end:
                    continue
                if any(m == mark and abs((on - due).days) <= 14 for m, on in paid):
                    continue
                lines.append({
                    "id": f"tax:{mark}:{due.isoformat()}", "kind": "regular",
                    "direction": D.OUT, "amount_cents": entry.amount_cents, "on_date": due,
                    "label": f"Estimated tax, {mark}",
                    "detail": (f"{_money(entry.amount_cents)}, the last {mark} estimated "
                               f"tax payment marked in the books ({_long(entry.on_date)}), "
                               "on the date the next is due."),
                    "cadence": "quarterly", "category": "Owner draw",
                    "link": f"/finance?kind=owner&estimated_tax={mark}",
                    "counted": entry.account.kind != CARD,
                    "on_card": str(entry.account_id) if entry.account.kind == CARD else ""})
    return lines


# ----------------------------------------------------------------- the card

def _card_payments(tenant, today: date, end: date, closed: list[date],
                   regular: list[dict]) -> list[dict]:
    """What is owed on a card today leaves the bank on the day the card is
    usually paid. After that, what is forecast to be charged is paid the
    month after it is charged (M2-8)."""
    lines = []
    for card in FinanceAccount.all_objects.filter(tenant=tenant, kind=CARD,
                                                  closed_at__isnull=True).order_by("name"):
        owed = reports.account_balance(tenant, card, today) if card.opening_on <= today else 0
        days = []
        if closed:
            last12 = closed[-12:]
            days = [on.day for on in FinanceEntry.all_objects.filter(
                tenant=tenant, removed_at__isnull=True, kind=K.TRANSFER, to_account=card,
                on_date__gte=last12[0], on_date__lte=reconcile.month_end(last12[-1]))
                .values_list("on_date", flat=True)]
        if days:
            day = int(median(days))
            first = _add_months(today, 0, day)
            if first < today:
                first = _add_months(today, 1, day)
            usual = f"on the {_ordinal(day)}, the day it is usually paid"
        else:
            first, day = today + timedelta(days=30), (today + timedelta(days=30)).day
            usual = "in 30 days: no payment to it was found in the closed months"
        charges = [row for row in regular if row["on_card"] == str(card.pk)]
        paid_on, start, number = first, None, 0
        while paid_on <= end:
            if number == 0:
                cents = owed
                detail = (f"What is owed on {card.name} today, {_money(owed)}, leaves the "
                          f"bank {usual}.")
            else:
                # What was forecast to be charged up to the payment before this one.
                until = _add_months(paid_on, -1, day) if days else paid_on - timedelta(days=30)
                mine = [row for row in charges
                        if (start is None or row["on_date"] > start)
                        and row["on_date"] <= until]
                cents = sum(row["amount_cents"] if row["direction"] == D.OUT
                            else -row["amount_cents"] for row in mine)
                detail = (f"{len(mine)} regular charge{'s' if len(mine) != 1 else ''} on "
                          f"{card.name} forecast through {_long(until)}, paid the month "
                          "after they are charged.")
                start = until
            if cents > 0:
                lines.append({
                    "id": f"card:{card.pk}:{paid_on.isoformat()}", "kind": "card",
                    "direction": D.OUT, "amount_cents": cents, "on_date": paid_on,
                    "label": f"{card.name} payment", "detail": detail,
                    "cadence": "monthly", "category": "", "link": "/finance/balance",
                    "counted": True, "on_card": ""})
            number += 1
            paid_on = _add_months(paid_on, 1, day) if days else paid_on + timedelta(days=30)
    return lines


# ---------------------------------------------------------------- the table

def _rows(spans: list[tuple], opening: int, lines: list[dict], floor) -> list[dict]:
    rows, cash = [], opening
    for start, stop, label in spans:
        mine = [row for row in lines if row["counted"] and start <= row["on_date"] <= stop]
        money_in = sum(row["amount_cents"] for row in mine if row["direction"] == D.IN)
        money_out = sum(row["amount_cents"] for row in mine if row["direction"] == D.OUT)
        end = cash + money_in - money_out
        rows.append({
            "start": start.isoformat(), "end": stop.isoformat(), "label": label,
            "start_cents": cash, "in_cents": money_in, "out_cents": money_out,
            "end_cents": end, "lines": [row["id"] for row in mine],
            "below_floor": floor is not None and end < floor, "below_zero": end < 0})
        cash = end
    return rows


def _summary(rows: list[dict]) -> dict:
    """The low point of these rows, and the first that ends under the floor
    and under nothing."""
    low = min(rows, key=lambda row: row["end_cents"])
    first = lambda flag: next((row["start"] for row in rows if row[flag]), None)  # noqa: E731
    return {"low_cents": low["end_cents"], "low_start": low["start"],
            "low_label": low["label"], "end_cents": rows[-1]["end_cents"],
            "first_below_floor": first("below_floor"),
            "first_below_zero": first("below_zero")}


# ------------------------------------------------------------- the forecast

def settings_for(tenant) -> FinanceForecastSettings:
    row, _ = FinanceForecastSettings.all_objects.get_or_create(tenant=tenant)
    return row


def set_floor(tenant, *, actor, floor_cents) -> FinanceForecastSettings:
    """"I want at least this much in the bank." None is no floor."""
    row = settings_for(tenant)
    before = row.floor_cents
    row.floor_cents = None if floor_cents is None else _cents(floor_cents, "The floor")
    row.updated_by = actor
    row.save()
    audit(tenant, "forecast_floor_changed", actor, row, before=before,
          after=row.floor_cents)
    return row


def closed_months(tenant) -> list[date]:
    """The months the forecast may read: closed, not "locked before month
    close began" (M1-9)."""
    return sorted(reconcile.standing(tenant))


def build(tenant, today: date | None = None) -> dict:
    """The whole forecast, from the books as they are now."""
    from apps.finance.disclaimer import DISCLAIMER

    today = today or timezone.localdate()
    floor = settings_for(tenant).floor_cents
    closed = closed_months(tenant)
    ready = len(closed) >= CLOSED_MONTHS_NEEDED
    last_week = today + timedelta(days=7 * WEEKS - 1)
    end = max(last_week, reconcile.month_end(_add_months(today.replace(day=1), MONTHS - 1)))

    accounts, cash = _accounts(tenant, today)
    unplaced = _unplaced(tenant, today)
    known, left_out = _known(tenant, today, end)
    regular, annual = [], []
    if ready:
        regular, annual = _regular(tenant, today, end, closed)
        regular += _estimated_tax(tenant, today, end, closed)
    cards = _card_payments(tenant, today, end, closed if ready else [], regular)
    lines = sorted(known + regular + cards, key=lambda row: (row["on_date"], row["id"]))

    opening = cash + unplaced
    weeks = _rows([(today + timedelta(days=7 * i), today + timedelta(days=7 * i + 6),
                    f"Week of {(today + timedelta(days=7 * i)):%b} "
                    f"{(today + timedelta(days=7 * i)).day}") for i in range(WEEKS)],
                  opening, lines, floor)
    spans, month = [], today.replace(day=1)
    for i in range(MONTHS):
        spans.append((today if i == 0 else month, reconcile.month_end(month),
                      reconcile.month_name(month)))
        month = reconcile.next_month(month)
    months = _rows(spans, opening, lines, floor)

    return {
        "as_of": today.isoformat(), "ready": ready, "closed_months": len(closed),
        "closed_through": reconcile.month_end(closed[-1]).isoformat() if closed else None,
        "note": "" if ready else NOT_READY,
        "cash_today_cents": opening, "accounts": accounts, "unplaced_cents": unplaced,
        "floor_cents": floor,
        "weeks": weeks, "months": months,
        "views": {**{days: _summary(weeks[:count]) for days, count in VIEWS.items()},
                  "months": _summary(months)},
        "lines": [{**row, "on_date": row["on_date"].isoformat()} for row in lines],
        "left_out": left_out, "likely_annual": annual,
        "disclaimer": DISCLAIMER,
    }


def dashboard_line(tenant, today: date) -> dict | None:
    """The practice owner's dashboard: the lowest cash in the next 13 weeks,
    and when (M2-11). Only with the module and two closed months."""
    from apps.tenancy import modules

    if not modules.has(tenant, modules.FORECAST):
        return None
    forecast = build(tenant, today)
    if not forecast["ready"]:
        return None
    view = forecast["views"]["90"]
    return {"low_cents": view["low_cents"], "week_of": view["low_start"],
            "below_zero": view["first_below_zero"] is not None,
            "below_floor": view["first_below_floor"] is not None}


def export(tenant, today: date | None = None) -> str:
    """The weekly table and the lines behind it, for a CPA or a bank."""
    import csv
    import io

    forecast = build(tenant, today)
    out = io.StringIO()
    writer = csv.writer(out)
    plain = lambda cents: f"{cents / 100:.2f}"  # noqa: E731
    writer.writerow([f"Cash forecast as of {forecast['as_of']}, 180 days by week"])
    writer.writerow(["Cash today", plain(forecast["cash_today_cents"])])
    writer.writerow(["Floor", plain(forecast["floor_cents"])
                     if forecast["floor_cents"] is not None else "not set"])
    if forecast["note"]:
        writer.writerow([forecast["note"]])
    writer.writerow([])
    writer.writerow(["Week starting", "Cash at the start", "Money in", "Money out",
                     "Cash at the end", "Under the floor", "Under zero"])
    for row in forecast["weeks"]:
        writer.writerow([row["start"], plain(row["start_cents"]), plain(row["in_cents"]),
                         plain(row["out_cents"]), plain(row["end_cents"]),
                         "yes" if row["below_floor"] else "",
                         "yes" if row["below_zero"] else ""])
    writer.writerow([])
    writer.writerow(["Date", "Kind", "What", "Category", "Cadence", "Money in",
                     "Money out", "In the cash line", "Where it comes from"])
    last = forecast["weeks"][-1]["end"]
    for row in forecast["lines"]:
        if row["on_date"] > last:
            continue
        writer.writerow([
            row["on_date"], {"known": "Known", "regular": "Regular",
                             "card": "Card payment"}[row["kind"]],
            row["label"], row["category"], row["cadence"],
            plain(row["amount_cents"]) if row["direction"] == D.IN else "",
            plain(row["amount_cents"]) if row["direction"] == D.OUT else "",
            "yes" if row["counted"] else "no: on a card, paid with the card",
            row["detail"]])
    if forecast["left_out"]:
        writer.writerow([])
        writer.writerow(["Overdue, not counted"])
        for row in forecast["left_out"]:
            writer.writerow([row["due_date"], row["label"], plain(row["amount_cents"]),
                             f"{row['days_overdue']} days overdue"])
    writer.writerow([])
    writer.writerow([forecast["disclaimer"]])
    return out.getvalue()


__all__ = ["build", "set_floor", "settings_for", "closed_months", "dashboard_line",
           "export", "FinanceError"]
