"""John Carter's personal side (P6 M4 decision 27, read with the brief's
"ALL FOUR" list): the household's money, beside the practice's books.

- **Two personal accounts**, joint checking and joint savings, and **one
  Mixed card** of the practice's ("Everyday Visa"), whose lines were sorted
  to a side: personal ones are owner draws in the books and the spend in the
  ledger; a split one (home internet, 40% business) is both.
- **Six months of lines**, brought in the way the owner would: each month's
  card statement through the books' import and each month's checking and
  savings statements through the personal import, with the owner's rules
  (typed under Settings → Finance → Import rules) deciding most lines, the
  threshold the small ones, and the owner sorting the rest. A business
  subscription paid from joint checking is the practice's, paid personally.
  Card payments and savings moves are transfers, paired across accounts.
  This month's card lines so far are in, the ones no rule knows waiting in
  To sort, with three of last month's checking lines.
- **A spouse with pay** (Dana Carter, a pediatric nurse; the spec's open
  question, answered for the demo), **a mortgage and a car loan**,
  **retirement and investment balances** month by month, **three goals** and
  **this year's tax set-aside in progress**. Debts, balances, goals and the
  set-aside are data only until stops 2–4 draw them.

All of it is built inside the books' own month loop (`money.history`), so
each month's statements are in before that month is reconciled and closed,
as on a real day.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from .clock import at, dice, moment, month_end, months, next_month

#: How far back the personal side goes: six full months before this one.
MONTHS = 6
SPOUSE = "Dana Carter"
SPOUSE_PAY = "MAPLE HILL PEDIATRICS PAYROLL"
CARD = "Everyday Visa"
DRAW_TEXT = "SUMMIT OPS PARTNERS TRANSFER"
TAX_SHARE = Decimal("0.28")
MAPPING = {"date": "Date", "description": "Description", "amount": "Amount",
           "date_format": "%m/%d/%Y", "sign": "negative_is_out", "balance": ""}

#: The owner's rules, typed by hand: (contains, side, business category,
#: personal category, split percent).
RULES = [
    ("MOUNTAIN MARKET", "personal", None, "Groceries", None),
    ("TRAILHEAD GRILL", "personal", None, "Dining", None),
    ("PEAK FUEL", "personal", None, "Fuel", None),
    ("NETFLIX", "personal", None, "Entertainment and subscriptions", None),
    ("XFINITY", "split", "Internet service", "Phone and internet", 40),
    ("AMAZON MKTPLACE", "split", "Supplies", "Everything else", 25),
    ("UPS STORE", "business", "Printing", None, None),
    ("CANVA", "business", "Software and apps", None, None),
    ("PAYMENT THANK YOU", "personal", None, "Transfers", None),
    ("PAYMENT TO EVERYDAY VISA", "personal", None, "Transfers", None),
    ("TRANSFER TO SAVINGS", "personal", None, "Transfers", None),
    ("FRONT RANGE MORTGAGE", "personal", None, "Rent or mortgage", None),
    ("SUMMIT AUTO FINANCE", "personal", None, "Car payment", None),
    ("PEAK ENERGY", "personal", None, "Electric and gas", None),
    ("CITY WATER", "personal", None, "Water and trash", None),
    ("ST JOHNS GIVING", "personal", None, "Church", None),
    ("VANGUARD ROTH", "personal", None, "Savings and retirement", None),
    ("GEICO", "personal", None, "Car insurance", None),
    (SPOUSE_PAY, "personal", None, "Spouse pay", None),
    (DRAW_TEXT, "personal", None, "Pay from the practice", None),
    ("INTEREST PAYMENT", "personal", None, "Other income", None),
]


def _when(world, day: date, hour=9, minute=0):
    return moment(min(day, world.today), hour, minute)


def _window(world) -> date:
    first = world.today.replace(day=1)
    for _ in range(MONTHS):
        first = (first - timedelta(days=1)).replace(day=1)
    return first


def in_window(world, month: date) -> bool:
    return _window(world) <= month < world.today.replace(day=1)


# ---------------------------------------------------------------- begin

def begin(world, books) -> None:
    """Before the first month of the window: the module is on (foundation),
    the ledger, the household, the two personal accounts, the Mixed card and
    the owner's rules."""
    from apps.finance import rules as rule_service
    from apps.finance import services as finance
    from apps.personal import services as personal
    from apps.personal.models import PersonalAccount, PersonalCategory, PersonalMember

    first, owner = _window(world), world.owner
    with at(_when(world, first - timedelta(days=4), 19, 10)):
        ledger = personal.ledger_for(owner)
        you = PersonalMember.objects.create(ledger=ledger, name=owner.full_name,
                                            relation="self", position=0)
        dana = PersonalMember.objects.create(ledger=ledger, name=SPOUSE, relation="spouse",
                                             position=1)
        joint = PersonalAccount.objects.create(
            ledger=ledger, name="Joint checking", kind="bank", last4="2210",
            opening_balance_cents=640_000, opening_on=first)
        savings = PersonalAccount.objects.create(
            ledger=ledger, name="Joint savings", kind="bank", last4="7781",
            opening_balance_cents=2_200_000, opening_on=first)
        card = finance.save_account(world.tenant, actor=owner, name=CARD, kind="card",
                                    last4="5512", opening_balance_cents=0, opening_on=first,
                                    side="mixed")
        mine = {c.name: c for c in PersonalCategory.objects.filter(ledger=ledger)}
        for contains, side, business, own, percent in RULES:
            rule_service.save_rule(
                world.tenant, actor=owner, contains=contains, treat_as="category",
                category=books["category"][business] if business else None, side=side,
                personal_category=mine[own] if own else None, split_percent=percent)
    books["mixed"] = card
    world.extra["household"] = {"ledger": ledger, "you": you, "dana": dana, "joint": joint,
                                "savings": savings, "mine": mine, "card_owed": 0}


# ----------------------------------------------------------- the months

def _line(on, text, cents):
    return {"on": on, "text": text, "signed": cents}


def _draws(world, month: date) -> list:
    """The practice's owner draws of the month (not the estimated tax), which
    arrive in joint checking the next day."""
    from apps.finance.models import FinanceEntry

    return list(FinanceEntry.all_objects.filter(
        tenant=world.tenant, kind="owner", direction="out", estimated_tax="",
        removed_at__isnull=True, on_date__gte=month, on_date__lte=month_end(month),
        side="").exclude(account=None).order_by("on_date"))


def _card_lines(world, month: date, *, until: date | None = None) -> list[dict]:
    roll = dice("everyday visa", month)
    last = min(month_end(month), until or month_end(month))

    def day(n):
        return month.replace(day=min(n, month_end(month).day))

    lines = []
    for n in (3, 10, 17, 24):
        lines.append(_line(day(n + roll.randrange(0, 2)), "MOUNTAIN MARKET #112",
                           -roll.randrange(8_500, 21_000)))
    for n in (6, 20):
        lines.append(_line(day(n), "TRAILHEAD GRILL", -roll.randrange(3_800, 11_500)))
    for n in (8, 22):
        lines.append(_line(day(n), "PEAK FUEL 0447", -roll.randrange(4_200, 6_900)))
    for n in (2, 9, 15, 23, 27):
        lines.append(_line(day(n), "BLUEBIRD COFFEE", -roll.randrange(450, 950)))
    lines.append(_line(day(12), "NETFLIX.COM", -2_299))
    lines.append(_line(day(14), "XFINITY INTERNET", -8_999))
    lines.append(_line(day(18), "AMAZON MKTPLACE PMTS", -roll.randrange(2_800, 9_400)))
    if month.month % 2:
        lines.append(_line(day(11), "UPS STORE 4471 PRINTING", -roll.randrange(2_600, 6_400)))
    # One line a month no rule knows: the owner sorts it, or it waits.
    lines.append(_line(day(25), "PINE STREET GOODS", -roll.randrange(4_000, 15_000)))
    owed = world.extra["household"]["card_owed"]
    if owed:
        lines.append(_line(day(20), "PAYMENT THANK YOU", owed))
    return sorted((x for x in lines if x["on"] <= last and x["on"] < world.today),
                  key=lambda x: x["on"])


def _joint_lines(world, month: date, card_paid: int) -> list[dict]:
    roll = dice("joint checking", month)

    def day(n):
        return month.replace(day=min(n, month_end(month).day))

    lines = [
        _line(day(1), "FRONT RANGE MORTGAGE PMT", -284_000),
        _line(day(1), SPOUSE_PAY, 245_000), _line(day(15), SPOUSE_PAY, 245_000),
        _line(day(10), "SUMMIT AUTO FINANCE", -51_200),
        _line(day(12), "PEAK ENERGY UTILITY", -roll.randrange(11_000, 21_500)),
        _line(day(16), "CITY WATER AND TRASH", -8_450),
        _line(day(7), "ST JOHNS GIVING", -20_000),
        _line(day(5), "TRANSFER TO SAVINGS 7781", -80_000),
        _line(day(18), "VANGUARD ROTH IRA", -50_000),
        _line(day(9), "CANVA PRO", -1_499),
        _line(day(21), "MOUNTAIN MARKET #118", -roll.randrange(6_000, 14_000)),
        _line(day(13), "CORNER DELI", -roll.randrange(900, 2_200)),
    ]
    if month.month in (1, 7):
        lines.append(_line(day(24), "GEICO AUTO INSURANCE", -68_400))
    for entry in _draws(world, month):
        on = entry.on_date + timedelta(days=1)
        lines.append(_line(on, DRAW_TEXT, entry.amount_cents))
        # The set-aside for quarterly tax: a share of each draw, to savings.
        share = int(entry.amount_cents * TAX_SHARE) // 1_000 * 1_000
        lines.append(_line(on + timedelta(days=1), "TRANSFER TO SAVINGS 7781 TAX", -share))
    if card_paid:
        lines.append(_line(day(20), "PAYMENT TO EVERYDAY VISA", -card_paid))
    # Lines no rule knows, sorted by the owner (or waiting, last month).
    lines.append(_line(day(26), "COSTCO WHSE #0661", -roll.randrange(14_000, 32_000)))
    if month.month % 3 == 0:
        lines.append(_line(day(19), "USPS PO 0123", -3_840))
    if month.month % 2 == 0:
        lines.append(_line(day(23), "BELL MEDICAL GROUP", -18_000))
    lines.append(_line(day(27), "CANYON HARDWARE", -roll.randrange(3_000, 16_000)))
    return sorted((x for x in lines if x["on"] <= month_end(month) and x["on"] < world.today),
                  key=lambda x: x["on"])


def _csv(lines) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Description", "Amount"])
    for line in lines:
        writer.writerow([line["on"].strftime("%m/%d/%Y"), line["text"],
                         f"{line['signed'] / 100:.2f}"])
    return out.getvalue().encode()


def month(world, books, month_: date, *, last: bool = False) -> None:
    """One month's three statements, in the week after it ended and before
    it is reconciled and closed: the card through the books' import, then
    joint checking and savings through the personal one."""
    from apps.finance import importer
    from apps.finance.models import FinanceImportRow
    from apps.personal import imports
    from apps.personal import services as personal

    if not in_window(world, month_):
        return
    house, owner, tenant = world.extra["household"], world.owner, world.tenant
    mine = house["mine"]
    after = next_month(month_)
    card_lines = _card_lines(world, month_)
    paid_this_month = next((x["signed"] for x in card_lines
                            if x["text"] == "PAYMENT THANK YOU"), 0)
    with at(_when(world, after + timedelta(days=1), 8, 40)):
        batch = importer.dry_run(tenant, account=books["mixed"],
                                 filename=f"EverydayVisa_{month_:%Y%m}.csv",
                                 file_bytes=_csv(card_lines), mapping=MAPPING, actor=owner)
        importer.commit(batch, actor=owner)
    house["card_owed"] = -sum(x["signed"] for x in card_lines if x["signed"] < 0)
    # The owner sorts what waited, a day later: what the card's odd shop was.
    with at(_when(world, after + timedelta(days=2), 20, 15)):
        for row in FinanceImportRow.objects.filter(batch=batch, side="to_sort") \
                .select_related("entry"):
            if row.entry is None:
                continue
            if dice("pine", row.entry.on_date).random() < 0.5:
                personal.sort_entry(row.entry, actor=owner, side="personal",
                                    personal_category=mine["Gifts"])
            else:
                personal.sort_entry(row.entry, actor=owner, side="business",
                                    category=books["category"]["Supplies"])

    joint_lines = _joint_lines(world, month_, paid_this_month)
    waiting = ("COSTCO WHSE", "BELL MEDICAL", "CANYON HARDWARE")
    with at(_when(world, after + timedelta(days=2), 7, 50)):
        batch = imports.dry_run(tenant, ledger=house["ledger"], account=house["joint"],
                                filename=f"joint_checking_{month_:%Y%m}.csv",
                                file_bytes=_csv(joint_lines), mapping=MAPPING)
        for row in batch.rows.filter(side="to_sort", outcome="new"):
            if last and row.description.startswith(waiting):
                continue                      # still in To sort
            if row.description.startswith("USPS"):
                imports.decide(row, tenant=tenant, actor=owner, decision="line",
                               side="business", business_category=books["category"]["Postage"])
            elif row.description.startswith("BELL MEDICAL"):
                imports.decide(row, tenant=tenant, actor=owner, decision="line",
                               side="personal", category=mine["Doctors and dentists"])
            elif row.description.startswith("CANYON HARDWARE"):
                imports.decide(row, tenant=tenant, actor=owner, decision="line",
                               side="personal", category=mine["Home maintenance"])
            else:
                imports.decide(row, tenant=tenant, actor=owner, decision="line",
                               side="personal", category=mine["Groceries"])
        imports.commit(batch, tenant=tenant, actor=owner)

    roll = dice("savings", month_)
    moves = [_line(x["on"], "TRANSFER FROM CHECKING 2210", -x["signed"])
             for x in joint_lines if x["text"].startswith("TRANSFER TO SAVINGS")]
    interest = _line(month_end(month_), "INTEREST PAYMENT", 1_400 + roll.randrange(0, 900))
    savings_lines = sorted((x for x in moves + [interest] if x["on"] < world.today),
                           key=lambda x: x["on"])
    with at(_when(world, after + timedelta(days=2), 8, 5)):
        batch = imports.dry_run(tenant, ledger=house["ledger"], account=house["savings"],
                                filename=f"joint_savings_{month_:%Y%m}.csv",
                                file_bytes=_csv(savings_lines), mapping=MAPPING)
        imports.commit(batch, tenant=tenant, actor=owner)


def this_month(world, books) -> None:
    """This month's card lines so far, downloaded mid-cycle: the ones no rule
    knows wait in To sort."""
    from apps.finance import importer

    start = world.today.replace(day=1)
    lines = _card_lines(world, start, until=world.today - timedelta(days=1))
    lines += [_line(x, text, -cents) for x, text, cents in (
        (start + timedelta(days=4), "REI #1123 DENVER", 14_865),
        (start + timedelta(days=6), "OFFICE DEPOT 2290", 6_712))
        if x < world.today]
    lines.sort(key=lambda x: x["on"])
    if not lines:
        return
    with at(moment(world.today, 7, 30)):
        batch = importer.dry_run(world.tenant, account=books["mixed"],
                                 filename=f"EverydayVisa_{start:%Y%m}_so_far.csv",
                                 file_bytes=_csv(lines), mapping=MAPPING, actor=world.owner)
        importer.commit(batch, actor=world.owner)


# ------------------------------------------- data only, for stops 2 to 4

def finish(world, books) -> None:
    """Debts, retirement and investments with a balance each month end, three
    goals, this year's set-aside, and last month's savings statement
    reconciled (decision 8: optional; it shows how)."""
    from apps.finance.models import FinanceEntry
    from apps.personal import reconcile
    from apps.personal.models import (
        PersonalBalance, PersonalDebt, PersonalGoal, PersonalHolding, PersonalLine,
        PersonalSetAside,
    )

    house = world.extra["household"]
    ledger, you, dana = house["ledger"], house["you"], house["dana"]
    today, first = world.today, _window(world)
    ends = [month_end(m) for m in months(first, today) if month_end(m) < today]
    with at(moment(today - timedelta(days=1), 20, 30)):
        mortgage = PersonalDebt.objects.create(
            ledger=ledger, name="Home mortgage", kind="mortgage", rate_percent=Decimal("6.125"),
            minimum_cents=284_000, due_day=1, original_cents=36_000_000,
            opened_on=date(2019, 6, 14))
        car = PersonalDebt.objects.create(
            ledger=ledger, name="Subaru Outback loan", kind="auto", whose=dana,
            rate_percent=Decimal("5.900"), minimum_cents=51_200, due_day=10,
            original_cents=3_200_000, opened_on=date(2023, 5, 2))
        holdings = [
            (PersonalHolding.objects.create(ledger=ledger, name="Solo 401(k)",
                                            kind="retirement", whose=you,
                                            target_cents=150_000_000, target_year=2045),
             18_640_000, 0.006),
            (PersonalHolding.objects.create(ledger=ledger, name="Dana's 403(b)",
                                            kind="retirement", whose=dana),
             7_420_000, 0.005),
            (PersonalHolding.objects.create(ledger=ledger, name="John's Roth IRA",
                                            kind="retirement", whose=you), 4_180_000, 0.005),
            (PersonalHolding.objects.create(ledger=ledger, name="Joint brokerage",
                                            kind="investment"), 5_230_000, 0.004),
        ]
        for n, end in enumerate(ends):
            PersonalBalance.objects.create(ledger=ledger, debt=mortgage, on_date=end,
                                           balance_cents=31_420_000 - n * 125_500)
            PersonalBalance.objects.create(ledger=ledger, debt=car, on_date=end,
                                           balance_cents=1_864_000 - n * 42_300)
            for holding, start, growth in holdings:
                wobble = dice("holding", holding.name, end).uniform(-0.012, 0.012)
                PersonalBalance.objects.create(
                    ledger=ledger, holding=holding, on_date=end,
                    balance_cents=int(start * (1 + growth + wobble) ** n)
                    + (50_000 * n if "Roth" in holding.name else 0))
        christmas = date(today.year, 12, 1) if today < date(today.year, 11, 15) \
            else date(today.year + 1, 12, 1)
        for position, (name, target, on, saved) in enumerate((
                ("Emergency fund", 3_000_000, None, 1_840_000),
                ("Car repairs", 250_000, today + timedelta(days=150), 90_000),
                ("Christmas", 180_000, christmas, 60_000))):
            PersonalGoal.objects.create(ledger=ledger, name=name, target_cents=target,
                                        target_on=on, saved_cents=saved,
                                        account=house["savings"], position=position)
        # The set-aside so far: each draw's share, to savings, since the last
        # estimated payment the practice made.
        paid = FinanceEntry.all_objects.filter(
            tenant=world.tenant, removed_at__isnull=True,
            on_date__year=today.year).exclude(estimated_tax="").order_by("-on_date").first()
        since = paid.on_date if paid else date(today.year, 1, 1)
        saved = sum(PersonalLine.objects.filter(
            ledger=ledger, account=house["joint"], removed_at__isnull=True,
            description="TRANSFER TO SAVINGS 7781 TAX", on_date__gt=since)
            .values_list("amount_cents", flat=True))
        PersonalSetAside.objects.create(ledger=ledger, year=today.year,
                                        percent_per_draw=Decimal("28.00"), saved_cents=saved,
                                        account=house["savings"])
        last = ends[-1] if ends else None
        if last is not None:
            rec = reconcile.start(house["savings"], statement_on=last,
                                  statement_balance_cents=reconcile.balance(house["savings"],
                                                                            last))
            reconcile.tick(rec, line_ids=[line.pk for line in reconcile.lines(rec)],
                           cleared=True)
            reconcile.finish(rec)
