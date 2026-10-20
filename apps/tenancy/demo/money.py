"""Invoices and the books, from January 2025 to the day the demo is seeded.

The practice grows as `cast.CLIENTS` says: four clients in January 2025,
eleven by the middle of 2026. Each has a recurring schedule; each month its
invoice is drafted by the schedule, made ready, sent and (nearly always) paid,
and the payment becomes income in the books, all through `apps.billing` and
`apps.finance` with the clock moved to the day. Expenses are entered the same
way. The last days of the bank account come in through the bank import
instead, so the demo has a committed import with remembered rules and matched
deposits to show.

Each month is then reconciled, bank and card, and closed (P6 M1 §10), by the
reconcile code with the clock moved to the week after the month ended. So the
books are locked through the end of last month by their closes, not by a date
anyone typed, and this month is open with the bank reconciliation in progress.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import ahead, cast, household
from .clock import at, dice, moment, month_end, months, next_month

RETAINER = "Fractional operations leadership, monthly retainer"
#: Where the books begin.
FIRST = date(2025, 1, 1)
#: The card's statement ends on this day of the month; the bank's on the last.
CARD_STATEMENT_DAY = 25
#: The months the owner pays estimated tax: January, April, June, September.
ESTIMATED_TAX_MONTHS = (1, 4, 6, 9)
#: A category the owner used for a while and then combined into the chart's own.
OLD_COURSES = "Courses and conferences"
#: Last month's invoice is still unpaid for these two, and half paid for the third.
OVERDUE = ("Globex Logistics", "Dunder Mifflin Paper")
PART_PAID = "Initech Software"
METHODS = {"Wayne Industries": "wire", "Acme Fasteners": "check",
           "Dunder Mifflin Paper": "check", "Vandelay Import-Export": "check"}

#: Card subscriptions: (day, who, what it is, as the statement prints it, dollars).
SOFTWARE = [
    (2, "Google", "Google Workspace, six seats", "GOOGLE*WORKSPACE SUMMITOPS", 86.40),
    (4, "Zoom", "Zoom, one host", "ZOOM.US 888-799-9666", 21.99),
    (6, "Slack", "Slack, five members", "SLACK T04SUMMIT", 43.75),
    (9, "Adobe", "Acrobat Pro", "ADOBE *ACROBAT PRO", 29.99),
    (11, "Intuit", "QuickBooks Online", "INTUIT *QBOOKS ONLINE", 99.00),
    (13, "Calendly", "Calendly, one seat", "CALENDLY.COM", 20.00),
    (16, "LinkedIn", "Sales Navigator", "LINKEDIN SALES NAV", 99.99),
    (18, "Notion", "Notion, team plan", "NOTION LABS INC", 24.00),
    (21, "DocuSign", "DocuSign, standard", "DOCUSIGN INC", 45.00),
]
CITIES = ["Tucson", "Newark", "Portland", "Austin", "San Jose", "New York", "Scranton"]


def history(world) -> None:
    books = _open_the_books(world)
    first = FIRST
    window_start = _import_window(world)
    held_back: list[dict] = []          # bank lines that arrive by import instead
    card_owed = books["card"].opening_balance_cents
    previous = None
    for index, month in enumerate(months(first, world.today)):
        if household.in_window(world, month) and "mixed" not in books:
            household.begin(world, books)
        # Last month waits for the bank import, which still has lines to bring
        # into it; every month before that is reconciled and closed here, in
        # the week after it ended. The household's statements of the month
        # (P6 M4) come in first, as they would.
        if previous is not None and month != _this_month(world):
            household.month(world, books, previous)
            _reconcile_and_close(world, books, previous)
            if previous == _months_back(world, 4):
                _late_refund(world, books, previous)
        previous = month
        # How good the forecast has been: he looks at it on the first of each
        # of the last months, and what he saw is kept (P6 M2 §4).
        if month >= _months_back(world, 6):
            ahead.look_on_the_first(world, month)
        invoiced = _invoice_the_month(world, books, month, window_start)
        facts = _expenses(world, books, month, index, invoiced, card_owed)
        card_owed = sum(f["cents"] for f in facts
                        if f["account"] == "card" and f["kind"] == "expense")
        for fact in facts:
            if fact["on"] > world.today:
                continue
            if fact["account"] == "bank" and window_start <= fact["on"] < world.today:
                held_back.append(fact)
            else:
                _enter(world, books, fact)
        _oddities(world, books, month)
    _bank_import(world, books, held_back, window_start)
    if _last_month(world) >= first:
        household.month(world, books, _last_month(world), last=True)
        _reconcile_and_close(world, books, _last_month(world))
        _pdf_statement(world, books)
        _correcting_entry(world, books)
    _this_month_in_progress(world, books)
    if "mixed" in books:
        household.this_month(world, books)
        household.finish(world, books)
    _reshape_the_chart(world, books)
    _year_end_facts(world)
    ahead.looking_ahead(world)
    world.extra["books"] = books


def _this_month(world) -> date:
    return world.today.replace(day=1)


def _last_month(world) -> date:
    return (_this_month(world) - timedelta(days=1)).replace(day=1)


def _paid_on(name: str, month: date) -> date:
    """The day this client pays this month's invoice: four to thirteen days
    after the first."""
    return month + timedelta(days=dice("paid", name, month).randrange(4, 14))


def _import_window(world) -> date:
    """The bank import covers the last ten days, or further back when that is
    what it takes to hold a client's deposit, so there is always one for it
    to match to an invoice."""
    quiet = set(OVERDUE) | {PART_PAID}
    recent = [_paid_on(name, month)
              for month in (_last_month(world), _this_month(world))
              for name, _i, _c, (year, m), *_rest in cast.CLIENTS
              if name not in quiet and date(year, m, 1) <= month]
    cleared = [day for day in recent if day + timedelta(days=1) < world.today]
    start = world.today - timedelta(days=10)
    if cleared:
        start = min(start, max(cleared) - timedelta(days=1))
    return max(start, FIRST)


def _finance():
    from apps.finance import services

    return services


def _open_the_books(world) -> dict:
    from apps.billing import services as billing
    from apps.finance.models import FinanceCategory

    finance = _finance()
    with at(FIRST - timedelta(days=12)):
        billing.update_settings(world.tenant, {
            "prefix": "SOP-", "terms_days": 15,
            "pay_instructions": ("Pay by ACH to Summit Operations Partners LLC, Front Range "
                                 "Bank, routing 000000000, account ending 4417; or by check "
                                 "to 1600 Larimer Street, Suite 400, Denver, CO 80202."),
            "default_terms": "Net 15. Thank you for your business.",
        }, actor=world.owner)
        finance.ensure_chart(world.tenant)
        bank = finance.save_account(
            world.tenant, actor=world.owner, name="Front Range Bank checking", kind="bank",
            last4="4417", opening_balance_cents=1_850_000, opening_on=FIRST)
        card = finance.save_account(
            world.tenant, actor=world.owner, name="Business Visa", kind="card",
            last4="0932", opening_balance_cents=124_000, opening_on=FIRST)
        finance.save_category(world.tenant, actor=world.owner, name=OLD_COURSES,
                              type="expense")
    categories = {c.name: c for c in FinanceCategory.objects.all()}
    return {"bank": bank, "card": card, "category": categories, "unplaced": [],
            "scheduled": set()}


# ---------------------------------------------------------------- invoices

def _invoice_the_month(world, books, month: date, window_start: date) -> dict:
    """This month's invoices: drafted by each client's schedule, made ready,
    sent, and paid on the day the client paid. Returns cents by company."""
    from apps.billing import services as billing
    owner, tenant = world.owner, world.tenant
    is_current = month == _this_month(world)
    is_last = month == _last_month(world)
    with at(moment(month, 8, 5)):
        for name, company in world.companies.items():
            if world.start[name] <= month and name not in books["scheduled"]:
                books["scheduled"].add(name)
                billing.save_schedule(
                    tenant, actor=owner, client_company=company,
                    contact=world.people[name][0], day_of_month=1, starts_on=month,
                    lines=[{"description": RETAINER, "quantity": "1",
                            "unit_price_cents": world.fee[name]}])
        drafts = billing.run_schedules(tenant, today=month)
    invoiced = {}
    for draft in drafts:
        name = draft.client_company.name
        with at(moment(month, 8, 30)):
            billing.make_ready(draft, actor=owner, role="FF")
            invoice = billing.send(draft, actor=owner, role="FF")
        invoiced[name] = invoice.total_cents
        roll = dice("paid", name, month)
        paid_on = _paid_on(name, month)
        amount = invoice.total_cents
        if (is_last or is_current) and name in OVERDUE:
            continue
        if name == PART_PAID and (is_last or is_current):
            # Half of this month's invoice, paid on the 2nd, once the month is
            # old enough to have a 2nd; before that, half of last month's.
            this_month_has_it = world.today.day >= 3
            if is_current and this_month_has_it:
                amount, paid_on = amount // 2, month + timedelta(days=1)
            elif is_last and not this_month_has_it:
                amount //= 2
            elif is_current:
                continue
        if paid_on >= world.today:
            continue
        _pay(world, books, invoice, amount, paid_on, window_start,
             METHODS.get(name, "ach"), roll)
    return invoiced


def _pay(world, books, invoice, amount, paid_on, window_start, method, roll):
    from apps.billing import services as billing
    from apps.finance.models import FinanceEntry

    reference = {"ach": f"ACH {roll.randrange(10000, 99999)}",
                 "check": f"Check {roll.randrange(1000, 9999)}",
                 "wire": f"Wire {roll.randrange(100000, 999999)}"}.get(method, "")
    with at(moment(paid_on, 14, 20)):
        payment = billing.record_payment(invoice, actor=world.owner, amount_cents=amount,
                                         paid_on=paid_on, method=method,
                                         reference=reference)
        entry = FinanceEntry.objects.filter(client_payment=payment).first()
        if window_start <= paid_on and paid_on + timedelta(days=1) < world.today:
            # Left for the bank import to place: its deposit line finds it.
            books["unplaced"].append((payment, entry))
        else:
            _finance().update_entry(entry, actor=world.owner, account=books["bank"])
    return payment, entry


# ---------------------------------------------------------------- expenses

def _fact(on, account, cents, category, text, *, who="", kind="expense", payee=None,
          direction="", bank_text="", to=None, estimated_tax=""):
    return {"on": on, "account": account, "cents": int(round(cents)), "category": category,
            "text": text, "who": who, "kind": kind, "payee": payee, "direction": direction,
            "bank_text": bank_text or text.upper(), "to": to, "estimated_tax": estimated_tax}


def _expenses(world, books, month: date, index: int, invoiced: dict, card_owed: int):
    """Everything the practice spent in a month, as facts to enter."""
    roll = dice("spend", month)
    facts = []

    def day(n):
        return month.replace(day=n)

    def dollars(low, high):
        return roll.randrange(int(low * 100), int(high * 100))

    # --- the card
    for n, who, what, printed, amount in SOFTWARE:
        facts.append(_fact(day(n), "card", amount * 100, "Software and apps",
                           what, who=who, bank_text=printed))
    facts.append(_fact(day(23), "card", 2800 + index * 430 + dollars(0, 18),
                       "Software and apps", "Anthropic API usage", who="Anthropic"))
    facts.append(_fact(day(14), "card", dollars(620, 1280), "Online ads",
                       "LinkedIn campaign: operations for owner-led companies",
                       who="LinkedIn Ads"))
    facts.append(_fact(day(19), "card", 14218, "Mobile phone",
                       "Mobile and hotspot plan", who="Verizon Wireless"))
    for trip in range(1 + (roll.random() < 0.55)):
        city = roll.choice(CITIES)
        start = day(roll.randrange(6, 24))
        facts.append(_fact(start - timedelta(days=4), "card", dollars(340, 610), "Airfare",
                           f"Flight to {city}, client on-site", who="United Airlines"))
        facts.append(_fact(start + timedelta(days=1), "card", dollars(270, 520), "Lodging",
                           f"Hotel, {city}, two nights", who="Hilton Garden Inn"))
        facts.append(_fact(start, "card", dollars(38, 92), "Rental car and ground transport",
                           f"Rides to and from the plant, {city}", who="Lyft"))
        facts.append(_fact(start, "card", dollars(62, 148), "Meals while traveling",
                           f"Dinner with the leadership team, {city}", who="Restaurant"))
    for _ in range(roll.randrange(2, 5)):
        facts.append(_fact(day(roll.randrange(2, 27)), "card", dollars(24, 96),
                           "Meals with clients and partners",
                           roll.choice(["Lunch with a referral partner",
                                        "Coffee with a prospect",
                                        "Working lunch, quarterly planning",
                                        "Breakfast with a client owner"]),
                           who=roll.choice(["Snooze Eatery", "Mercantile", "Pigtrain Coffee",
                                            "Rioja"])))
    if roll.random() < 0.6:
        facts.append(_fact(day(roll.randrange(3, 26)), "card", dollars(32, 128),
                           "Supplies", "Whiteboard markers, binders and printing",
                           who="Office Depot"))
    if month.month % 3 == 2:
        facts.append(_fact(day(17), "card", dollars(149, 399), OLD_COURSES,
                           "Operations leadership course, quarterly module",
                           who="Front Range Leadership Institute"))

    # --- the bank
    facts += [
        _fact(day(1), "bank", 69500, "Coworking and meeting rooms",
              "Coworking membership, dedicated desk", who="Larimer Square Cowork",
              bank_text="ACH DEBIT LARIMER SQ COWORK MEMBERSHIP"),
        _fact(day(3), "bank", 31200, "Professional liability (E&O)",
              "Professional liability and general liability premium",
              who="Front Range Mutual", bank_text="ACH DEBIT FRONT RANGE MUTUAL INS PREM"),
        _fact(day(5), "bank", 45000, "Bookkeeping",
              "Monthly bookkeeping and close", who="Ledger & Quill Bookkeeping",
              bank_text="ACH DEBIT LEDGER AND QUILL BKKPG"),
        _fact(day(8), "bank", 85000, "Website and hosting",
              "Website care and search work", who="Aviato Web Studio",
              payee=world.vendors["Erlich Bachman"],
              bank_text="ACH DEBIT AVIATO WEB STUDIO"),
        _fact(day(10), "bank", 145000, "Professional memberships",
              "Owners' peer group, monthly dues", who="Mile High Owners Roundtable",
              bank_text="ACH DEBIT MILE HIGH OWNERS RNDTBL"),
        _fact(day(15), "bank", 3000, "Bank fees", "Monthly service fee",
              who="Front Range Bank", bank_text="FRONT RANGE BANK MONTHLY SERVICE FEE"),
    ]
    if month.month == 3:
        facts.append(_fact(day(18), "bank", 185000, "Tax preparation",
                           f"{month.year - 1} tax return preparation",
                           who="Ledger & Quill Bookkeeping",
                           bank_text="ACH DEBIT LEDGER AND QUILL TAX PREP"))
    if month.month % 3 == 1:
        facts.append(_fact(day(12), "bank", 75000, "Sponsorships and events",
                           "Quarterly sponsorship, owners' breakfast series",
                           who="Denver Metro Chamber", bank_text="CHECK 10" + str(40 + index)))
    # The card is paid from the bank: not a cost, a transfer.
    facts.append(_fact(day(20), "bank", card_owed, None, "Card payment", kind="transfer",
                       to="card", bank_text="ONLINE PMT BUSINESS VISA 0932"))

    contractors = 0
    for key, name, _email, _joined, share in cast.ASSOCIATES:
        if world.extra["joined"][key] > month:
            continue
        theirs = [c for c, user in world.lead.items() if user == world.staff[key]]
        base = sum(invoiced.get(c, 0) for c in theirs)
        if base:
            contractors += 1
            facts.append(_fact(day(25), "bank", base * share // 100, "Associates",
                               f"{name}, {share}% of {month:%B} fees: " + ", ".join(theirs),
                               who=name, payee=world.staff_contacts[key],
                               bank_text=f"GUSTO CONTRACTOR PAY {name.upper()}"))
    for key, name, _email, _joined, rate in cast.ASSISTANTS:
        if world.extra["joined"][key] > month:
            continue
        hours = roll.randrange(60, 81)
        contractors += 1
        facts.append(_fact(day(27), "bank", hours * rate * 100, "Assistants",
                           f"{name}, {hours} hours at ${rate}", who=name,
                           payee=world.staff_contacts[key],
                           bank_text=f"GUSTO CONTRACTOR PAY {name.upper()}"))
    facts.append(_fact(day(15), "bank", 3500 + 600 * contractors,
                       "Other outside services", "Payroll platform fee",
                       who="Gusto", bank_text="GUSTO FEE 6772" + str(10 + index)))

    spent = sum(f["cents"] for f in facts if f["kind"] == "expense")
    net = sum(invoiced.values()) - spent
    draw = max(200_000, int(net * 0.94) // 50_000 * 50_000)
    if month.month in ESTIMATED_TAX_MONTHS:
        # Quarterly estimated tax, paid from the practice's account on the
        # 15th: the owner's own money, not an expense. It comes out of what
        # the owner would otherwise have drawn that month.
        for which, share, to in (("federal", 0.18, "IRS USATAXPYMT"),
                                 ("state", 0.04, "COLO DEPT REVENUE")):
            tax = int(draw * share) // 10_000 * 10_000
            if which == "state" and household.state_from_savings(world, day(15)):
                # P6 M4 stop 4: this year's last two state payments were made
                # from joint savings, where the set-aside is kept.
                world.extra["household"]["state_tax"][day(15)] = tax
                draw -= tax
                continue
            facts.append(_fact(day(15), "bank", tax, "Owner draw",
                               f"Estimated tax, {which}, paid {month:%B} {month.year}",
                               kind="owner", direction="out", who=to.title(),
                               bank_text=f"{to} {month:%m%y}", estimated_tax=which))
            draw -= tax
    facts.append(_fact(day(28), "bank", draw, "Draws", f"Owner draw, {month:%B}",
                       kind="owner", direction="out", who=world.owner.full_name,
                       bank_text="ONLINE TRANSFER TO PERSONAL CHK 8801"))
    return sorted(facts, key=lambda f: f["on"])


def _enter(world, books, fact):
    finance = _finance()
    changes = {"kind": fact["kind"], "on_date": fact["on"], "amount_cents": fact["cents"],
               "account": books[fact["account"]], "description": fact["text"],
               "counterparty": fact["who"]}
    if fact["kind"] == "transfer":
        changes["to_account"] = books[fact["to"]]
    else:
        changes["category"] = books["category"][fact["category"]]
    if fact["direction"]:
        changes["direction"] = fact["direction"]
    if fact["payee"] is not None:
        changes["payee_contact"] = fact["payee"]
    if fact["estimated_tax"]:
        changes["estimated_tax"] = fact["estimated_tax"]
    # Typed in a couple of days after it happened, by the owner: the books
    # are the practice owner's alone.
    with at(moment(min(fact["on"] + timedelta(days=2), world.today), 17, 10)):
        return finance.create_entry(world.tenant, actor=world.owner, **changes)


# ---------------------------------------------------------------- oddities

def _months_back(world, n: int) -> date:
    day = world.today.replace(day=1)
    for _ in range(n):
        day = (day - timedelta(days=1)).replace(day=1)
    return day


def _oddities(world, books, month: date) -> None:
    """The handful of things that are not the monthly rhythm: an invoice
    issued twice and voided, a workshop billed to someone who is not a client,
    and a refund. (The other refund is entered late: `_late_refund`.)"""
    from apps.billing import services as billing
    from apps.billing.models import ClientInvoice

    owner, tenant, finance = world.owner, world.tenant, _finance()
    if month == _months_back(world, 3):
        name = "Hooli Field Services"
        with at(moment(month.replace(day=2), 10)):
            twice = billing.create_draft(
                tenant, actor=owner, kind=ClientInvoice.Kind.ONE_OFF,
                client_company=world.companies[name], contact=world.people[name][0],
                lines=[{"description": RETAINER, "quantity": "1",
                        "unit_price_cents": world.fee[name]}])
            billing.make_ready(twice, actor=owner, role="FF")
            billing.send(twice, actor=owner, role="FF")
        with at(moment(month.replace(day=4), 9, 40)):
            billing.void(twice, actor=owner,
                         reason=f"Issued twice in error: {month:%B}'s retainer is already "
                                "on the scheduled invoice. Gavin was told the same day.")
        world.extra["void_invoice"] = twice
    if month == _months_back(world, 2):
        partner = next(p for p in world.partners if p.last_name == "Welton")
        with at(moment(month.replace(day=9), 11)):
            workshop = billing.create_draft(
                tenant, actor=owner, kind=ClientInvoice.Kind.CONTACT, contact=partner,
                # Named on the invoice: not what a one-off usually goes to.
                income_category=books["category"]["Workshops and speaking"],
                lines=[{"description": "Half-day workshop for the owners' forum: running a "
                                       "weekly leadership meeting that ends on time",
                        "quantity": "1", "unit_price_cents": 150_000}])
            billing.make_ready(workshop, actor=owner, role="FF")
            workshop = billing.send(workshop, actor=owner, role="FF")
        paid_on = month.replace(day=22)
        if paid_on < world.today - timedelta(days=10):
            _pay(world, books, workshop, workshop.total_cents, paid_on, world.today,
                 "check", dice("workshop"))
        world.extra["workshop_invoice"] = workshop
    if month == _months_back(world, 5):
        with at(moment(month.replace(day=16), 15)):
            finance.create_entry(
                tenant, actor=owner, kind="income", direction="out",
                on_date=month.replace(day=16), amount_cents=50_000,
                # A refund of a retainer, so it takes away from Retainers.
                category=books["category"]["Retainers"], account=books["bank"],
                description="Goodwill credit for the delayed route review, refunded by check",
                counterparty="Dunder Mifflin Paper",
                client_company=world.companies["Dunder Mifflin Paper"],
                reference="Check 2117")


# ----------------------------------------------------------- the bank import

def _bank_import(world, books, held_back: list[dict], window_start: date) -> None:
    """The last days of the bank account, read from the bank's own export:
    a dry run, the owner's decisions (two of them remembered as rules), and
    a commit. Deposits find the invoice payments they are."""
    import csv
    import io

    from apps.finance import importer, reports
    from apps.finance.models import FinanceImportRow

    owner, tenant, bank = world.owner, world.tenant, books["bank"]
    lines = [{"on": f["on"], "text": f["bank_text"], "signed": -f["cents"], "fact": f}
             for f in held_back]
    for payment, _entry in books["unplaced"]:
        invoice = payment.invoice
        who = (invoice.client_company.name if invoice.client_company_id
               else str(invoice.contact)).upper()
        lines.append({"on": payment.paid_on + timedelta(days=1),
                      "text": f"DEPOSIT {payment.reference.upper()} {who}"[:60],
                      "signed": payment.amount_cents, "fact": None})
    lines = sorted((line for line in lines if line["on"] < world.today),
                   key=lambda line: line["on"])
    if not lines:
        return
    balance = reports.account_balance(tenant, bank, lines[0]["on"] - timedelta(days=1))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Posted Date", "Description", "Amount", "Balance"])
    for line in lines:
        balance += line["signed"]
        writer.writerow([line["on"].strftime("%m/%d/%Y"), line["text"],
                         f"{line['signed'] / 100:.2f}", f"{balance / 100:.2f}"])
    name = f"FrontRange_checking_{lines[0]['on']:%Y%m%d}_{lines[-1]['on']:%Y%m%d}.csv"
    with at(moment(world.today, 7, 45)):
        batch = importer.dry_run(
            tenant, account=bank, filename=name, file_bytes=out.getvalue().encode(),
            actor=owner, mapping={"date": "Posted Date", "description": "Description",
                                  "amount": "Amount", "balance": "Balance",
                                  "date_format": "%m/%d/%Y", "sign": "negative_is_out"})
        by_text = {line["text"]: line["fact"] for line in lines if line["fact"]}
        remembered = {"FRONT RANGE BANK MONTHLY": None, "LARIMER SQ COWORK": None,
                      "FRONT RANGE MUTUAL": None, "LEDGER AND QUILL": None,
                      "GUSTO FEE": None}
        for row in FinanceImportRow.objects.filter(batch=batch).order_by("row_number"):
            row.refresh_from_db()
            fact = by_text.get(row.description)
            if fact is None or row.outcome != FinanceImportRow.Outcome.NEW:
                continue
            if fact["kind"] == "transfer":
                importer.decide(row, decision="transfer", other_account=books[fact["to"]],
                                remember="ONLINE PMT BUSINESS VISA", actor=owner)
                continue
            if row.category_id is not None:
                continue                      # a rule remembered above took it
            phrase = next((p for p in remembered if p in row.description
                           and remembered[p] is None and fact["payee"] is None), None)
            importer.decide(row, decision="entry",
                            category=books["category"][fact["category"]],
                            payee_contact=fact["payee"], remember=phrase, actor=owner)
            if phrase:
                remembered[phrase] = True
        importer.commit(batch, actor=owner)
        # A bank's file does not say which draw was an estimated tax payment.
        for row in FinanceImportRow.objects.filter(batch=batch).select_related("entry"):
            fact = by_text.get(row.description)
            if fact and fact["estimated_tax"] and row.entry_id:
                _finance().update_entry(row.entry, actor=owner,
                                        estimated_tax=fact["estimated_tax"])
    world.extra["bank_import"] = batch


# ------------------------------------------- reconciling and closing (P6 M1)

def _reconcile():
    from apps.finance import reconcile

    return reconcile


def _written_by_check(line) -> bool:
    """The owner's own checks, which the bank shows the month after they are
    written: the Chamber's sponsorship and the one refund."""
    return line["description"].startswith("Quarterly sponsorship") \
        or "refunded by check" in line["description"]


def _statement(world, books, key: str, month: date, when, *, statement_on=None):
    """One statement, ticked as the owner would: everything it shows, and not
    the checks written this month and not yet cashed. Its balance is what
    that comes to, so it finishes at zero, as a real one does once it is
    right."""
    reconcile, owner = _reconcile(), world.owner
    account = books[key]
    statement_on = statement_on or (
        month.replace(day=CARD_STATEMENT_DAY) if key == "card" else month_end(month))
    with at(when):
        rec = reconcile.start(world.tenant, actor=owner, account=account,
                              statement_on=statement_on, statement_balance_cents=0)
        reconcile.tick(rec, actor=owner, everything=True)
        waiting = [line["id"] for line in reconcile.lines(rec)
                   if not line["carried"] and _written_by_check(line)]
        if waiting:
            reconcile.tick(rec, actor=owner, entry_ids=waiting, cleared=False)
        reconcile.update(rec, actor=owner,
                         statement_balance_cents=reconcile.totals(rec)["expected_cents"])
    return rec


def _reconcile_and_close(world, books, month: date) -> None:
    reconcile, owner = _reconcile(), world.owner
    after = next_month(month)
    day = min(after + timedelta(days=5), world.today)
    keys = [("bank", 5), ("card", 40)]
    if "mixed" in books and books["mixed"].opening_on <= month:
        # P6 M4 decision 8: a Mixed card reconciles once, with the business month.
        keys.append(("mixed", 50))
    for key, minute in keys:
        when = moment(day, 16, minute)
        rec = _statement(world, books, key, month, when)
        with at(when + timedelta(minutes=25)):
            reconcile.finish(rec, actor=owner)
    with at(moment(min(after + timedelta(days=6), world.today), 17, 30)):
        reconcile.close(world.tenant, actor=owner, month=month)


STATEMENT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: Letter; margin: 0.7in; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #222; }}
h1 {{ font-size: 16pt; margin: 0; }} .muted {{ color: #666; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 14pt; }}
th {{ text-align: left; border-bottom: 1px solid #999; padding: 3pt 4pt; }}
td {{ padding: 2.5pt 4pt; border-bottom: 1px solid #eee; }}
.n {{ text-align: right; white-space: nowrap; }} .sum td {{ font-weight: bold; }}
</style></head><body>
<h1>Front Range Bank</h1>
<p class="muted">A fictional bank, for a demonstration. This is not a real statement.</p>
<p><strong>Business checking, account ending {last4}</strong><br>
{practice}<br>Statement period {start} to {end}</p>
<table><tr><td>Beginning balance on {start}</td><td class="n">{opening}</td></tr>
<tr><td>Deposits and other credits</td><td class="n">{money_in}</td></tr>
<tr><td>Withdrawals and other debits</td><td class="n">{money_out}</td></tr>
<tr class="sum"><td>Ending balance on {end}</td><td class="n">{closing}</td></tr></table>
<table><tr><th>Date</th><th>Description</th><th class="n">Withdrawals</th>
<th class="n">Deposits</th></tr>{rows}</table>
</body></html>"""


def _pdf_statement(world, books) -> None:
    """Last month's bank statement, as a PDF, imported (owner, 2026-10-14),
    so the PDF import and the statement on the Reconcile screen can be shown.

    **Written without Claude,** as everything in the seed is: the PDF is drawn
    from what last month's reconciliation ticked, and the import is recorded
    as it would stand after a read, with every line already in the books
    (the month was entered and reconciled before its statement was filed).
    So it has no `ai_call`, and its screen shows no cost. The bank is
    fictional and the page says so."""
    import html

    from weasyprint import HTML

    from apps.finance import importer, statement_pdf
    from apps.finance.models import (
        FinanceImportBatch, FinanceImportRow, FinanceReconciliation,
    )
    from apps.tenancy import storage

    reconcile, finance = _reconcile(), _finance()
    owner, tenant, bank, month = world.owner, world.tenant, books["bank"], _last_month(world)
    rec = FinanceReconciliation.objects.filter(account=bank, month=month).first()
    if rec is None:
        return
    shown = [line for line in reconcile.lines(rec) if line["cleared"]]
    sums = reconcile.totals(rec)

    def dollars(cents: int) -> str:
        return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"

    def words(line) -> str:
        return " ".join((line["counterparty"] or line["description"]).upper().split())[:60]

    def day(value) -> str:
        return f"{value:%B} {value.day}, {value.year}"

    rows = "".join(
        f"<tr><td>{date.fromisoformat(line['on_date']):%m/%d}</td>"
        f"<td>{html.escape(words(line))}</td>"
        f"<td class='n'>{dollars(line['amount_cents']) if line['way'] == 'out' else ''}</td>"
        f"<td class='n'>{dollars(line['amount_cents']) if line['way'] == 'in' else ''}</td></tr>"
        for line in shown)
    content = HTML(string=STATEMENT_HTML.format(
        last4=bank.last4 or "0000", practice=html.escape(tenant.name), start=day(month),
        end=day(rec.statement_on), opening=dollars(sums["starting_balance_cents"]),
        money_in=dollars(sums["cleared_in_cents"]),
        money_out=dollars(sums["cleared_out_cents"]),
        closing=dollars(rec.statement_balance_cents), rows=rows)).write_pdf()
    name = f"FrontRange_statement_{month:%Y_%m}.pdf"
    filed = min(next_month(month) + timedelta(days=5), world.today)
    with at(moment(filed, 15, 50)) as now:
        batch = FinanceImportBatch.objects.create(
            tenant=tenant, account=bank, filename=name, created_by=owner,
            source=FinanceImportBatch.Source.PDF, mapping=dict(statement_pdf.MAPPING),
            status=FinanceImportBatch.Status.COMMITTED, committed_at=now,
            statement_file=storage.save(
                tenant=tenant, content=content,
                object_key=storage.object_key("statements", name),
                purpose=statement_pdf.STORED_AS, content_type="application/pdf"),
            period_start=month, period_end=rec.statement_on,
            opening_balance_cents=sums["starting_balance_cents"],
            last_balance_cents=rec.statement_balance_cents, last_balance_on=rec.statement_on)
        for number, line in enumerate(shown, start=2):
            signed = line["amount_cents"] if line["way"] == "in" else -line["amount_cents"]
            FinanceImportRow.objects.create(
                tenant=tenant, batch=batch, row_number=number,
                raw={"Date": line["on_date"], "Description": words(line),
                     "Amount": f"{signed / 100:.2f}"},
                on_date=date.fromisoformat(line["on_date"]),
                amount_cents=line["amount_cents"], direction=line["way"],
                description=words(line), outcome=FinanceImportRow.Outcome.DUPLICATE)
        batch.counts = importer._counts(batch)
        batch.save(update_fields=["counts", "updated_at"])
        finance.audit(tenant, "import_committed", owner, batch, account=bank.name,
                      filename=name, counts=batch.counts)
    world.extra["pdf_statement"] = batch


def _late_refund(world, books, month: date) -> None:
    """A month closed, reopened and closed again (§10): Adobe's refund was on
    that month's card statement and had never been entered. It was the newest
    closed month when it was found, so reopening it was the right fix."""
    from apps.finance.models import FinanceReconciliation

    reconcile, finance, owner, tenant = _reconcile(), _finance(), world.owner, world.tenant
    why = (f"Adobe's refund for the cancelled second seat is on the {month:%B} card "
           "statement and was never entered.")
    with at(moment(next_month(month) + timedelta(days=8), 10, 15)):
        reconcile.reopen_month(tenant, actor=owner, month=month, reason=why)
        rec = FinanceReconciliation.objects.get(account=books["card"], month=month)
        reconcile.reopen(rec, actor=owner, reason=why)
        refund = finance.create_entry(
            tenant, actor=owner, kind="expense", direction="in",
            on_date=month.replace(day=12), amount_cents=11_988,
            category=books["category"]["Software and apps"],
            account=books["card"], counterparty="Adobe",
            description="Refund: second Acrobat seat cancelled after the annual renewal")
        reconcile.tick(rec, actor=owner, entry_ids=[str(refund.pk)])
        reconcile.update(rec, actor=owner,
                         statement_balance_cents=reconcile.totals(rec)["expected_cents"])
        reconcile.finish(rec, actor=owner)
        reconcile.close(tenant, actor=owner, month=month)
    world.extra["reopened_month"] = month


def _correcting_entry(world, books) -> None:
    """A mistake found in a closed month is corrected in the open one (§1.5),
    and the entry says what it corrects. The closed month stays as it was."""
    last = _last_month(world)
    on = min(world.today, _this_month(world) + timedelta(days=2))
    with at(moment(on, 11, 5)):
        entry = _finance().create_entry(
            world.tenant, actor=world.owner, kind="expense", direction="in", on_date=on,
            amount_cents=1_500, category=books["category"]["Bank fees"],
            account=books["bank"], counterparty="Front Range Bank",
            description=(f"Correcting entry: the bank gave back half of {last:%B}'s "
                         f"monthly service fee after {last:%B} was closed. Entered here; "
                         f"{last:%B} stays as it was sent."))
    world.extra["correcting_entry"] = entry


def _this_month_in_progress(world, books) -> None:
    """This month's bank reconciliation, begun and not finished: everything
    through yesterday is ticked but one deposit, so the difference is that
    deposit. The card is not started."""
    reconcile, owner = _reconcile(), world.owner
    month = _this_month(world)
    through = max(month, world.today - timedelta(days=1))
    when = moment(world.today, 8, 20)
    rec = _statement(world, books, "bank", month, when, statement_on=through)
    deposits = [line for line in reconcile.lines(rec)
                if line["cleared"] and line["way"] == "in" and not line["carried"]
                and line["kind"] == "income"]
    if deposits:
        with at(when + timedelta(minutes=10)):
            reconcile.tick(rec, actor=owner, entry_ids=[deposits[-1]["id"]], cleared=False)
    world.extra["open_reconciliation"] = rec


def _reshape_the_chart(world, books) -> None:
    """One combine and one split on record (§10), as the owner would do them
    bringing the chart to what the CPA asked for. Both include closed months
    and change no total."""
    from apps.finance import chart

    owner, cats = world.owner, books["category"]
    with at(moment(max(FIRST, world.today - timedelta(days=3)), 15, 30)):
        chart.merge(cats[OLD_COURSES], cats["Education and training"], actor=owner)
        chart.split(cats["Software and apps"], actor=owner, name="Sales tools", as_sub=False,
                    contains="Sales Navigator")


def _year_end_facts(world) -> None:
    """What the CPA's worksheet asks for and the books cannot know: last
    year's miles and square feet, whole; this year's square feet, with the
    miles still to come."""
    finance, today = _finance(), world.today
    with at(moment(max(FIRST, today - timedelta(days=2)), 9, 40)):
        if today.year - 1 >= FIRST.year:
            finance.save_year_facts(
                world.tenant, actor=world.owner, year=today.year - 1, total_miles=14_820,
                business_miles=6_310, home_square_feet=2_400, office_square_feet=180)
        finance.save_year_facts(world.tenant, actor=world.owner, year=today.year,
                                home_square_feet=2_400, office_square_feet=180)
