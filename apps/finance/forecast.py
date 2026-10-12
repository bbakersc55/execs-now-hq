"""The cash forecast (`docs/p6_m2_cash_forecast.md`): known, regular and
planned lines, the card, the floor, the owner's adjustments, the what-if, and
how good it has been.

"How much cash is the practice likely to have, week by week, if clients pay
as they have been paying and its costs go on as they have been going."

What this module keeps true:

- **It is arithmetic on the books.** Every figure is a sum of lines, and
  every line says where it came from. Nothing here asks Claude for anything.
- **The forecast itself is never stored.** It is worked out from the books
  and the invoices each time it is asked for, so it cannot disagree with them
  (M2-16). What is kept is what the owner said: the floor, planned lines and
  adjustments; and one snapshot a month, to set beside what happened.
- **A what-if is a look.** It recomputes and saves nothing (M2-9).
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

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.finance import reconcile, reports
from apps.finance.models import (
    FinanceAccount, FinanceEntry, FinanceForecastAdjustment, FinanceForecastPlanned,
    FinanceForecastSettings, FinanceForecastSnapshot, FinanceReconciliation,
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


def _known(tenant, today: date, end: date, adjusted: dict) -> tuple[list[dict], list[dict]]:
    """Invoices sent and unpaid, invoices not yet sent, and the invoices each
    recurring schedule will write. Returns `(lines, left out)`. An invoice
    the owner moved lands on the day they said; one they left out is listed."""
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
        group = f"invoice:{invoice.pk}"
        client = str(invoice.client_company_id or "")
        mine = adjusted.get(group, [])
        moved = next((adj for adj in reversed(mine) if adj.kind == "expected"), None)
        left = next((adj for adj in reversed(mine) if adj.kind == "leave_out"), None)
        old = sent and (today - invoice.due_date).days > LEFT_OUT_AFTER_DAYS
        if left is not None or (old and moved is None):
            left_out.append({
                "id": str(invoice.pk), "group": group, "label": f"{who}: {name}",
                "amount_cents": amount, "due_date": invoice.due_date.isoformat(),
                "days_overdue": max((today - invoice.due_date).days, 0),
                "why": "left out by you" if left is not None
                else f"more than {LEFT_OUT_AFTER_DAYS} days overdue",
                "adjustment": str(left.pk) if left is not None else "",
                "link": f"/invoices/{invoice.pk}"})
            continue
        # One not yet sent is counted as if sent today (M2-3).
        due = invoice.due_date if sent else max(invoice.due_date, today)
        expected = max(due + timedelta(days=habit or 0), today)
        detail = (("Due " if sent else "Not sent yet. As if sent today, due ")
                  + f"{_long(due)}; forecast {_habit(habit)}."
                  + (" Part paid: this is what is left." if invoice.paid_cents and sent
                     else ""))
        said = ""
        if moved is not None:
            expected = max(moved.expected_on, today)
            said = f"You expect it on {_long(moved.expected_on)}."
        if expected > end:
            continue
        lines.append({
            "id": group, "group": group, "client": client, "kind": "known",
            "direction": D.IN, "amount_cents": amount, "on_date": expected,
            "label": f"{who}: {name}", "who": who, "detail": detail, "adjusted": said,
            "adjustment": str(moved.pk) if moved is not None else "",
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
                    "id": f"schedule:{schedule.pk}:{written.isoformat()}",
                    "group": f"schedule:{schedule.pk}",
                    "client": str(schedule.client_company_id), "kind": "known",
                    "who": schedule.client_company.name, "adjusted": "", "adjustment": "",
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


def _entered_since(tenant, after: date, today: date) -> dict:
    """`{(pattern key, month)}` for what has been entered since the last
    closed month, up to today: a regular cost already in the books for a
    month is not forecast again for it."""
    seen = set()
    for entry in FinanceEntry.all_objects.filter(
            tenant=tenant, removed_at__isnull=True, on_date__gt=after,
            on_date__lte=today,
            account__isnull=False, kind__in=(K.EXPENSE, K.INCOME, K.OWNER)):
        key = (entry.kind, entry.direction, entry.category_id, entry.account_id,
               *_who(entry))
        seen.add((key, entry.on_date.replace(day=1)))
    return seen


def _pattern_group(key) -> str:
    return "pattern:" + "|".join(str(part or "") for part in key)


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
    entered = _entered_since(tenant, reconcile.month_end(closed[-1]), today)
    this_month = today.replace(day=1)
    lines, annual = [], []

    def line(key, pattern, on: date, cents: int, cadence: str, detail: str) -> dict:
        entry = pattern.entry
        card = entry.account.kind == CARD
        group = _pattern_group(key)
        return {
            "id": f"{group}:{on}", "group": group, "client": "", "who": _name(entry),
            "adjusted": "", "adjustment": "", "entry_kind": entry.kind,
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
                "group": _pattern_group(key),
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
        on_date__gt=reconcile.month_end(closed[-1]), on_date__lte=today)
        .exclude(estimated_tax="").values_list("estimated_tax", "on_date"))
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
                    "id": f"tax:{mark}:{due.isoformat()}", "group": f"tax:{mark}",
                    "client": "", "who": f"Estimated tax, {mark}", "adjusted": "",
                    "adjustment": "", "entry_kind": "owner", "kind": "regular",
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
                    "id": f"card:{card.pk}:{paid_on.isoformat()}",
                    "group": f"card:{card.pk}", "client": "", "who": card.name,
                    "adjusted": "", "adjustment": "", "kind": "card",
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


# ------------------------------------------------- what the owner has said

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


def set_client_names(tenant, *, actor, include: bool) -> FinanceForecastSettings:
    """"Include client names in AI explanations" (M2-12). Off by default."""
    if not isinstance(include, bool):
        raise FinanceError("include_client_names is true or false.")
    row = settings_for(tenant)
    before = row.include_client_names
    row.include_client_names, row.updated_by = include, actor
    row.save()
    if before != include:
        audit(tenant, "forecast_client_names_changed", actor, row, before=before,
              after=include)
    return row


def _a_day(value, what) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise FinanceError(f"{what} is a date, as YYYY-MM-DD.") from None


def _adjustments(tenant) -> dict:
    """`{line key: [adjustments, oldest first]}`, those not undone."""
    found: dict = {}
    for row in FinanceForecastAdjustment.all_objects.filter(
            tenant=tenant, undone_at__isnull=True).select_related("by").order_by("created_at"):
        found.setdefault(row.line_key, []).append(row)
    return found


def _say(adj) -> str:
    A = FinanceForecastAdjustment.Kind
    since = f" from {_long(adj.from_date)}" if adj.from_date else ""
    return {
        A.AMOUNT: f"You set it to {_money(adj.amount_cents or 0)}{since}.",
        A.DAY: f"You moved it to the {_ordinal(adj.day_of_month or 1)}{since}.",
        A.PAUSE: (f"You paused it{since}"
                  + (f" until {_long(adj.until_date)}." if adj.until_date else ".")),
        A.END: f"You ended it{since}.",
        A.NOT_REGULAR: "You said it is not regular.",
        A.EXPECTED: (f"You expect it on {_long(adj.expected_on)}." if adj.expected_on
                     else ""),
        A.LEAVE_OUT: "You left it out.",
    }[adj.kind]


def _apply(lines: list[dict], adjusted: dict, today: date) -> list[dict]:
    """The owner's corrections to regular lines (§3), each from its own date,
    in the order they were made."""
    A = FinanceForecastAdjustment.Kind
    out = []
    for row in lines:
        mine = adjusted.get(row["group"], [])
        keep, said = True, []
        for adj in mine:
            start = adj.from_date or today
            if adj.kind == A.NOT_REGULAR:
                keep = False
            elif adj.kind == A.END and row["on_date"] >= start:
                keep = False
            elif adj.kind == A.PAUSE and row["on_date"] >= start and (
                    adj.until_date is None or row["on_date"] <= adj.until_date):
                keep = False
            elif adj.kind == A.AMOUNT and row["on_date"] >= start:
                row = {**row, "amount_cents": adj.amount_cents}
                said.append(_say(adj))
            elif adj.kind == A.DAY and row["on_date"] >= start:
                row = {**row, "on_date": max(_add_months(row["on_date"], 0,
                                                         adj.day_of_month), today)}
                said.append(_say(adj))
        if keep:
            if said:
                row = {**row, "adjusted": " ".join(said), "adjustment": str(mine[-1].pk)}
            out.append(row)
    return out


def _planned(tenant, today: date, end: date) -> tuple[list[dict], list[dict]]:
    """What the owner typed (§2.4). Returns `(lines, the planned items as the
    screen lists them)`. A what-if is a line that is not counted."""
    lines, listed = [], []
    for row in FinanceForecastPlanned.all_objects.filter(
            tenant=tenant, removed_at__isnull=True).select_related("created_by"):
        dates = []
        if row.happened_at is None:
            step = {"monthly": 1, "quarterly": 3}.get(row.repeat, 0)
            on, last = row.on_date, min(row.until or end, end)
            while on <= last:
                if on >= today:
                    dates.append(on)
                if not step:
                    break
                on = _add_months(on, step, row.on_date.day)
        # A single one whose date passed a week ago with nothing said.
        lapsed = (row.happened_at is None and not row.repeat
                  and row.on_date < today - timedelta(days=7))
        if not row.repeat and row.happened_at is None and not lapsed \
                and row.on_date < today:
            dates = [today]                  # just past: still expected
        state = ("happened" if row.happened_at else "lapsed" if lapsed
                 else "what_if" if row.is_what_if else "planned")
        listed.append({
            "id": str(row.pk), "description": row.description, "direction": row.direction,
            "amount_cents": row.amount_cents, "on_date": row.on_date.isoformat(),
            "repeat": row.repeat, "until": row.until.isoformat() if row.until else None,
            "is_what_if": row.is_what_if, "source": row.source, "state": state,
            "next_on": dates[0].isoformat() if dates else None})
        for on in dates:
            lines.append({
                "id": f"planned:{row.pk}:{on.isoformat()}", "group": f"planned:{row.pk}",
                "client": "", "who": row.description, "adjusted": "", "adjustment": "",
                "kind": "planned", "direction": row.direction,
                "amount_cents": row.amount_cents, "on_date": on, "label": row.description,
                "detail": ("A what-if: drawn beside the forecast, not counted in it."
                           if row.is_what_if else "Planned by you."
                           + {"review": " From a review.", "annual": " Confirmed as annual."}
                           .get(row.source, "")),
                "cadence": row.repeat, "category": "", "link": "/finance/forecast",
                "counted": not row.is_what_if, "what_if": row.is_what_if, "on_card": ""})
    return lines, listed


# ------------------------------------------------------------- the forecast

def closed_months(tenant) -> list[date]:
    """The months the forecast may read: closed, not "locked before month
    close began" (M1-9)."""
    return sorted(reconcile.standing(tenant))


def _spans(today: date) -> tuple[list, list, date]:
    weeks = [(today + timedelta(days=7 * i), today + timedelta(days=7 * i + 6),
              f"Week of {(today + timedelta(days=7 * i)):%b} "
              f"{(today + timedelta(days=7 * i)).day}") for i in range(WEEKS)]
    months, month = [], today.replace(day=1)
    for i in range(MONTHS):
        months.append((today if i == 0 else month, reconcile.month_end(month),
                       reconcile.month_name(month)))
        month = reconcile.next_month(month)
    return weeks, months, max(weeks[-1][1], months[-1][1])


def _gather(tenant, today: date, *, adjusted: dict | None = None) -> dict:
    """Every line, with the owner's adjustments applied (or, with
    `adjusted={}`, as the books alone give them)."""
    closed = closed_months(tenant)
    ready = len(closed) >= CLOSED_MONTHS_NEEDED
    _weeks, _months, end = _spans(today)
    adjusted = _adjustments(tenant) if adjusted is None else adjusted
    known, left_out = _known(tenant, today, end, adjusted)
    regular, annual = [], []
    if ready:
        regular, annual = _regular(tenant, today, end, closed)
        regular += _estimated_tax(tenant, today, end, closed)
        regular = _apply(regular, adjusted, today)
        # One confirmed as a planned line, or said not to be regular, is no
        # longer "to confirm".
        taken = set(FinanceForecastPlanned.all_objects.filter(
            tenant=tenant, removed_at__isnull=True).exclude(line_key="")
            .values_list("line_key", flat=True))
        annual = [row for row in annual if row["group"] not in taken and not any(
            adj.kind == "not_regular" for adj in adjusted.get(row["group"], []))]
    planned, listed = _planned(tenant, today, end)
    return {"closed": closed, "ready": ready, "end": end, "known": known,
            "left_out": left_out, "regular": regular, "annual": annual,
            "planned": planned, "planned_listed": listed, "adjusted": adjusted}


def _table(tenant, today: date, parts: dict, opening: int, floor, *, known, regular,
           planned) -> dict:
    """The rows and their summaries for one set of lines. The card's payments
    are worked out from the regular lines given, so a what-if moves them too."""
    weeks, months, end = _spans(today)
    cards = _card_payments(tenant, today, end, parts["closed"] if parts["ready"] else [],
                           regular)
    lines = sorted(known + regular + cards + planned,
                   key=lambda row: (row["on_date"], row["id"]))
    week_rows = _rows(weeks, opening, lines, floor)
    month_rows = _rows(months, opening, lines, floor)
    return {"lines": lines, "weeks": week_rows, "months": month_rows,
            "views": {**{days: _summary(week_rows[:count]) for days, count in VIEWS.items()},
                      "months": _summary(month_rows)}}


def _public(row: dict) -> dict:
    return {**{key: value for key, value in row.items() if key != "entry_kind"},
            "on_date": row["on_date"].isoformat()}


def build(tenant, today: date | None = None, *, what_if: dict | None = None,
          snapshot: bool = True) -> dict:
    """The whole forecast, from the books as they are now. `what_if` is a
    look and saves nothing: `{"off": [groups or "client:<id>"], "on": [planned
    what-if ids], "amounts": {group: cents}}`."""
    from apps.finance.disclaimer import DISCLAIMER

    today = today or timezone.localdate()
    config = settings_for(tenant)
    floor = config.floor_cents
    parts = _gather(tenant, today)
    accounts, cash = _accounts(tenant, today)
    unplaced = _unplaced(tenant, today)
    opening = cash + unplaced
    table = _table(tenant, today, parts, opening, floor, known=parts["known"],
                   regular=parts["regular"], planned=parts["planned"])
    if snapshot and parts["ready"]:
        _take_snapshot(tenant, today, table, opening)

    adjustments = [{
        "id": str(adj.pk), "group": adj.line_key, "label": adj.label, "kind": adj.kind,
        "text": _say(adj), "source": adj.source, "at": adj.created_at.isoformat(),
        "by": (adj.by.full_name or adj.by.email) if adj.by_id else ""}
        for rows in parts["adjusted"].values() for adj in rows]
    clients = {}
    for row in parts["known"]:
        if row["client"]:
            clients[row["client"]] = row["who"]
    result = {
        "as_of": today.isoformat(), "ready": parts["ready"],
        "closed_months": len(parts["closed"]),
        "closed_through": (reconcile.month_end(parts["closed"][-1]).isoformat()
                           if parts["closed"] else None),
        "note": "" if parts["ready"] else NOT_READY,
        "cash_today_cents": opening, "accounts": accounts, "unplaced_cents": unplaced,
        "floor_cents": floor, "include_client_names": config.include_client_names,
        "weeks": table["weeks"], "months": table["months"], "views": table["views"],
        "lines": [_public(row) for row in table["lines"]],
        "left_out": parts["left_out"], "likely_annual": parts["annual"],
        "planned": parts["planned_listed"],
        "adjustments": sorted(adjustments, key=lambda row: row["at"], reverse=True),
        "clients": [{"id": pk, "name": name}
                    for pk, name in sorted(clients.items(), key=lambda item: item[1])],
        "history": history(tenant),
        "what_if": None, "disclaimer": DISCLAIMER,
    }
    if what_if:
        result["what_if"] = _what_if(tenant, today, parts, opening, floor, table, what_if)
    return result


def _what_if(tenant, today, parts, opening, floor, table, what_if: dict) -> dict:
    """The forecast with some lines switched off, some what-if lines switched
    on, and some amounts changed. Nothing is saved."""
    off = {str(item) for item in (what_if.get("off") or [])}
    on = {str(item) for item in (what_if.get("on") or [])}
    amounts = what_if.get("amounts") or {}
    if not isinstance(amounts, dict):
        raise FinanceError("amounts is a line and the amount to try for it.")
    for group, cents in amounts.items():
        _cents(cents, "An amount to try")

    def kept(rows):
        out = []
        for row in rows:
            if row["group"] in off or (row["client"] and f"client:{row['client']}" in off):
                continue
            if row["group"] in amounts:
                row = {**row, "amount_cents": amounts[row["group"]]}
            out.append(row)
        return [row for row in out if row["amount_cents"] > 0]

    planned = []
    for row in kept(parts["planned"]):
        if row.get("what_if"):
            if row["group"].removeprefix("planned:") not in on:
                continue
            row = {**row, "counted": True}
        planned.append(row)
    other = _table(tenant, today, parts, opening, floor, known=kept(parts["known"]),
                   regular=kept(parts["regular"]), planned=planned)
    # A card payment is its own line too: "what if I do not pay the card".
    if any(group.startswith("card:") for group in off):
        lines = [row for row in other["lines"] if row["group"] not in off]
        weeks, months, _end = _spans(today)
        week_rows, month_rows = _rows(weeks, opening, lines, floor), \
            _rows(months, opening, lines, floor)
        other = {"lines": lines, "weeks": week_rows, "months": month_rows,
                 "views": {**{days: _summary(week_rows[:count])
                              for days, count in VIEWS.items()},
                           "months": _summary(month_rows)}}
    return {
        "weeks": other["weeks"], "months": other["months"], "views": other["views"],
        # At each view's low point: the what-if less the forecast as it stands.
        "difference_at_low": {view: other["views"][view]["low_cents"]
                              - table["views"][view]["low_cents"] for view in table["views"]},
        "off": sorted(off), "on": sorted(on), "amounts": amounts}


def groups(tenant, today: date | None = None) -> dict:
    """`{line key: what it is called}` for every line the books give, before
    any adjustment: what an adjustment may name."""
    today = today or timezone.localdate()
    parts = _gather(tenant, today, adjusted={})
    found = {row["group"]: row["label"] for row in parts["known"] + parts["regular"]}
    found.update({row["group"]: row["label"] for row in parts["left_out"]})
    found.update({row["group"]: row["label"] for row in parts["annual"]})
    return found


# ------------------------------------------------- planned lines, adjustments

PLANNED_FIELDS = ("description", "direction", "amount_cents", "on_date", "repeat", "until",
                  "is_what_if")


@transaction.atomic
def save_planned(tenant, *, actor, planned=None, source="", line_key="", **fields):
    """Add or change a planned line. The amount is the owner's own: nothing
    here takes a figure from anywhere else."""
    unknown = set(fields) - set(PLANNED_FIELDS)
    if unknown:
        raise FinanceError(f"Not a field of a planned line: {', '.join(sorted(unknown))}.")
    made = planned is None
    row = planned or FinanceForecastPlanned(tenant=tenant, created_by=actor, source=source,
                                            line_key=line_key[:400])
    if not made and (row.removed_at or row.happened_at):
        raise FinanceError("That planned line is finished with.", status=409)
    if made and not {"description", "amount_cents", "on_date"} <= set(fields):
        raise FinanceError("A planned line has a description, an amount and a date.")
    if "description" in fields:
        row.description = " ".join(str(fields["description"] or "").split())[:200]
        if not row.description:
            raise FinanceError("Say what it is.")
    if "direction" in fields or made:
        row.direction = fields.get("direction", "out")
        if row.direction not in (D.IN, D.OUT):
            raise FinanceError("direction is in or out.")
    if "amount_cents" in fields:
        row.amount_cents = _cents(fields["amount_cents"], "The amount")
        if row.amount_cents <= 0:
            raise FinanceError("A planned line is for more than nothing.")
    if "on_date" in fields:
        row.on_date = _a_day(fields["on_date"], "The date")
    if "repeat" in fields:
        row.repeat = fields["repeat"] or ""
        if row.repeat not in FinanceForecastPlanned.Repeat.values:
            raise FinanceError("repeat is monthly, quarterly, or nothing.")
    if "until" in fields:
        row.until = _a_day(fields["until"], "The last date") if fields["until"] else None
    if row.until and (not row.repeat or row.until < row.on_date):
        raise FinanceError("\"Until\" is for a line that repeats, and is on or after its "
                           "first date.")
    if "is_what_if" in fields:
        if not isinstance(fields["is_what_if"], bool):
            raise FinanceError("is_what_if is true or false.")
        row.is_what_if = fields["is_what_if"]
    row.save()
    audit(tenant, "forecast_planned_added" if made else "forecast_planned_changed", actor,
          row, description=row.description, direction=row.direction,
          amount_cents=row.amount_cents, on_date=row.on_date.isoformat(),
          repeat=row.repeat, is_what_if=row.is_what_if, source=row.source)
    return row


@transaction.atomic
def finish_planned(planned, *, actor, how: str):
    """`happened`: the real thing is in the books now. `removed`: it is not
    going to happen."""
    if how not in ("happened", "removed"):
        raise FinanceError("how is happened or removed.")
    if planned.removed_at or planned.happened_at:
        raise FinanceError("That planned line is finished with.", status=409)
    setattr(planned, f"{how}_at", timezone.now())
    planned.save()
    audit(planned.tenant, f"forecast_planned_{how}", actor, planned,
          description=planned.description)
    return planned


#: Which adjustments each kind of line takes.
ADJUSTABLE = {
    "pattern": ("amount", "day", "pause", "end", "not_regular"),
    "tax": ("amount", "pause", "end", "not_regular"),
    "invoice": ("expected", "leave_out"),
}


@transaction.atomic
def adjust(tenant, *, actor, group, kind, amount_cents=None, day_of_month=None,
           from_date=None, until_date=None, expected_on=None, source=""):
    """One correction by the owner to a line the forecast found (§3)."""
    today = timezone.localdate()
    known = groups(tenant, today)
    group = str(group or "")
    if group not in known:
        raise FinanceError("That line is not in this practice's forecast.", status=404)
    family = group.split(":", 1)[0]
    if kind not in ADJUSTABLE.get(family, ()):
        raise FinanceError("That line cannot be changed that way.")
    row = FinanceForecastAdjustment(tenant=tenant, line_key=group, label=known[group][:255],
                                    kind=kind, by=actor, source=source)
    if kind == "amount":
        row.amount_cents = _cents(amount_cents, "The amount")
        if row.amount_cents <= 0:
            raise FinanceError("An amount is more than nothing. End it instead.")
    if kind == "day":
        if isinstance(day_of_month, bool) or not isinstance(day_of_month, int) \
                or not 1 <= day_of_month <= 31:
            raise FinanceError("The day of the month is from 1 to 31.")
        row.day_of_month = day_of_month
    if kind in ("amount", "day", "pause", "end"):
        row.from_date = _a_day(from_date, "The date it starts") if from_date else today
    if kind == "pause":
        row.until_date = _a_day(until_date, "The date it resumes") if until_date else None
        if row.until_date and row.until_date < row.from_date:
            raise FinanceError("It cannot resume before it is paused.")
    if kind == "expected":
        row.expected_on = _a_day(expected_on, "The day you expect it")
    row.save()
    audit(tenant, "forecast_adjusted", actor, row, line=row.label, kind=kind,
          text=_say(row), source=source)
    return row


@transaction.atomic
def undo(adjustment, *, actor):
    if adjustment.undone_at is not None:
        raise FinanceError("That was already undone.", status=409)
    adjustment.undone_at = timezone.now()
    adjustment.save(update_fields=["undone_at", "updated_at"])
    audit(adjustment.tenant, "forecast_adjustment_undone", actor, adjustment,
          line=adjustment.label, kind=adjustment.kind)
    return adjustment


# ------------------------------------------------------ how good it has been

CLIENTS = "Client invoices"


def _by_name(rows: list[dict]) -> dict:
    """Forecast lines by what they will be compared under: a regular line by
    its category, an invoice as "Client invoices", a card payment and a
    planned line by their own names."""
    found: dict = {}
    for row in rows:
        name = (CLIENTS if row["kind"] == "known" else row["category"] or row["label"])
        cell = found.setdefault(name, {"in": 0, "out": 0})
        cell[row["direction"]] += row["amount_cents"]
    return found


def keep_month(tenant, today: date) -> bool:
    """The scheduled job's (`tasks.keep_month_forecast`): keep this month's
    forecast if it is not kept yet and there are the closed months to make
    one. True when it kept one. Nothing else of the forecast is worked out."""
    if FinanceForecastSnapshot.all_objects.filter(
            tenant=tenant, month=today.replace(day=1)).exists():
        return False
    parts = _gather(tenant, today)
    if not parts["ready"]:
        return False
    _accounts_listed, cash = _accounts(tenant, today)
    opening = cash + _unplaced(tenant, today)
    table = _table(tenant, today, parts, opening, settings_for(tenant).floor_cents,
                   known=parts["known"], regular=parts["regular"],
                   planned=parts["planned"])
    _take_snapshot(tenant, today, table, opening)
    return True


def _take_snapshot(tenant, today: date, table: dict, opening: int) -> None:
    """The forecast for this month as it stood when it was first worked out
    in the month: by the job on the 1st, or, for a practice the job has not
    reached, the first time anyone looks. Taken once and never changed."""
    month = today.replace(day=1)
    if FinanceForecastSnapshot.all_objects.filter(tenant=tenant, month=month).exists():
        return
    last = reconcile.month_end(month)
    mine = [row for row in table["lines"] if row["counted"] and row["on_date"] <= last]
    money_in = sum(row["amount_cents"] for row in mine if row["direction"] == D.IN)
    money_out = sum(row["amount_cents"] for row in mine if row["direction"] == D.OUT)
    FinanceForecastSnapshot.all_objects.get_or_create(
        tenant=tenant, month=month, defaults={"taken_on": today, "forecast": {
            "start_cents": opening, "in_cents": money_in, "out_cents": money_out,
            "end_cents": opening + money_in - money_out, "by": _by_name(mine)}})


def _actual(tenant, snapshot) -> dict:
    """What the books say happened to cash from when the snapshot was taken
    to the end of its month."""
    last = reconcile.month_end(snapshot.month)
    accounts = [account for account in FinanceAccount.all_objects.filter(tenant=tenant)
                .exclude(kind=CARD) if account.opening_on <= last]
    cash = {account.pk for account in accounts}
    end = sum(reports.account_balance(tenant, account, last) for account in accounts
              if account.closed_at is None or account.closed_at.date() > last)
    end += FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, account__isnull=True, direction=D.IN,
        on_date__lte=last).aggregate(t=Sum("amount_cents"))["t"] or 0
    by: dict = {}
    money_in = money_out = 0
    # From after the snapshot: what was already in the books that day was in
    # the cash it started from, and was not forecast.
    entries = FinanceEntry.all_objects.filter(
        Q(on_date__gt=snapshot.taken_on)
        | Q(on_date=snapshot.taken_on, created_at__gt=snapshot.created_at),
        tenant=tenant, removed_at__isnull=True,
        on_date__lte=last).select_related("category", "category__parent", "to_account")
    for entry in entries:
        if entry.kind == K.TRANSFER:
            # Between the practice's own cash accounts it is not a movement;
            # to a card it is the card's payment.
            if entry.account_id in cash and entry.to_account_id not in cash:
                name, way = f"{entry.to_account.name} payment", D.OUT
            elif entry.to_account_id in cash and entry.account_id not in cash:
                name, way = "From a card", D.IN
            else:
                continue
        elif entry.account_id is not None and entry.account_id not in cash:
            continue                        # on a card: cash when the card is paid
        else:
            way = entry.direction
            name = CLIENTS if entry.source == FinanceEntry.Source.INVOICE \
                else _category_name(entry.category) or "(no category yet)"
        cell = by.setdefault(name, {"in": 0, "out": 0})
        cell[way] += entry.amount_cents
        if way == D.IN:
            money_in += entry.amount_cents
        else:
            money_out += entry.amount_cents
    return {"in_cents": money_in, "out_cents": money_out, "end_cents": end, "by": by}


def month_closed(tenant, month: date) -> None:
    """Called when a month is closed: what happened is set beside what was
    forecast for it, where a forecast was kept."""
    snapshot = FinanceForecastSnapshot.all_objects.filter(tenant=tenant, month=month).first()
    if snapshot is not None:
        snapshot.actual = _actual(tenant, snapshot)
        snapshot.save(update_fields=["actual", "updated_at"])


def history(tenant) -> list[dict]:
    """The last six closed months that have a forecast to set beside them:
    cash at the end, money in and out, forecast and actual, and the three
    largest differences by line. No score (M2-10)."""
    closed = set(closed_months(tenant))
    rows = []
    for snapshot in FinanceForecastSnapshot.all_objects.filter(
            tenant=tenant, month__in=closed).order_by("-month")[:6]:
        if snapshot.actual is None:
            snapshot.actual = _actual(tenant, snapshot)
            snapshot.save(update_fields=["actual", "updated_at"])
        forecast, actual = snapshot.forecast, snapshot.actual
        gaps = []
        for name in set(forecast["by"]) | set(actual["by"]):
            was = forecast["by"].get(name, {"in": 0, "out": 0})
            now = actual["by"].get(name, {"in": 0, "out": 0})
            net_forecast, net_actual = was["in"] - was["out"], now["in"] - now["out"]
            if net_forecast != net_actual:
                gaps.append({"name": name, "forecast_cents": net_forecast,
                             "actual_cents": net_actual,
                             "difference_cents": net_actual - net_forecast})
        gaps.sort(key=lambda row: (-abs(row["difference_cents"]), row["name"]))
        rows.append({
            "month": snapshot.month.isoformat()[:7],
            "label": reconcile.month_name(snapshot.month),
            "taken_on": snapshot.taken_on.isoformat(),
            "forecast": {key: forecast[key] for key in ("in_cents", "out_cents",
                                                        "end_cents")},
            "actual": {key: actual[key] for key in ("in_cents", "out_cents", "end_cents")},
            "largest": gaps[:3]})
    return rows


# ----------------------------------------------- the dashboard, the download

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
                     "Money out", "In the cash line", "Where it comes from",
                     "What you changed"])
    last = forecast["weeks"][-1]["end"]
    for row in forecast["lines"]:
        if row["on_date"] > last:
            continue
        writer.writerow([
            row["on_date"], {"known": "Known", "regular": "Regular", "planned": "Planned",
                             "card": "Card payment"}[row["kind"]],
            row["label"], row["category"], row["cadence"],
            plain(row["amount_cents"]) if row["direction"] == D.IN else "",
            plain(row["amount_cents"]) if row["direction"] == D.OUT else "",
            "yes" if row["counted"] else ("no: a what-if" if row.get("what_if")
                                          else "no: on a card, paid with the card"),
            row["detail"], row["adjusted"]])
    if forecast["left_out"]:
        writer.writerow([])
        writer.writerow(["Not counted"])
        for row in forecast["left_out"]:
            writer.writerow([row["due_date"], row["label"], plain(row["amount_cents"]),
                             row["why"]])
    writer.writerow([])
    writer.writerow([forecast["disclaimer"]])
    return out.getvalue()
