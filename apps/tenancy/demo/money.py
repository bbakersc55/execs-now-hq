"""Invoices and the books, from January 2025 to the day the demo is seeded.

The practice grows as `cast.CLIENTS` says: four clients in January 2025,
eleven by the middle of 2026. Each has a recurring schedule; each month its
invoice is drafted by the schedule, made ready, sent and (nearly always) paid,
and the payment becomes income in the books, all through `apps.billing` and
`apps.finance` with the clock moved to the day. Expenses are entered the same
way. The last days of the bank account come in through the bank import
instead, so the demo has a committed import with remembered rules and matched
deposits to show.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import cast
from .clock import at, dice, moment, month_end, months, next_month

RETAINER = "Fractional operations leadership, monthly retainer"
#: Where the books begin, and the day they are locked through.
FIRST = date(2025, 1, 1)
LOCK = date(2025, 12, 31)
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
    for index, month in enumerate(months(first, world.today)):
        if month == date(2026, 2, 1) and world.today >= date(2026, 2, 10):
            with at(date(2026, 2, 10)):
                _finance().update_settings(world.tenant, actor=world.owner,
                                           locked_through=LOCK)
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
    return max(start, LOCK + timedelta(days=1))


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
          direction="", bank_text="", to=None):
    return {"on": on, "account": account, "cents": int(round(cents)), "category": category,
            "text": text, "who": who, "kind": kind, "payee": payee, "direction": direction,
            "bank_text": bank_text or text.upper(), "to": to}


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
        facts.append(_fact(day(n), "card", amount * 100, "Software",
                           what, who=who, bank_text=printed))
    facts.append(_fact(day(23), "card", 2800 + index * 430 + dollars(0, 18),
                       "AI and API usage", "Anthropic API usage", who="Anthropic"))
    facts.append(_fact(day(14), "card", dollars(620, 1280), "Advertising",
                       "LinkedIn campaign: operations for owner-led companies",
                       who="LinkedIn Ads"))
    facts.append(_fact(day(19), "card", 14218, "Phone and internet",
                       "Mobile and hotspot plan", who="Verizon Wireless"))
    for trip in range(1 + (roll.random() < 0.55)):
        city = roll.choice(CITIES)
        start = day(roll.randrange(6, 24))
        facts.append(_fact(start - timedelta(days=4), "card", dollars(340, 610), "Airfare",
                           f"Flight to {city}, client on-site", who="United Airlines"))
        facts.append(_fact(start + timedelta(days=1), "card", dollars(270, 520), "Lodging",
                           f"Hotel, {city}, two nights", who="Hilton Garden Inn"))
        facts.append(_fact(start, "card", dollars(38, 92), "Ground transport",
                           f"Rides to and from the plant, {city}", who="Lyft"))
        facts.append(_fact(start, "card", dollars(62, 148), "Meals",
                           f"Dinner with the leadership team, {city}", who="Restaurant"))
    for _ in range(roll.randrange(2, 5)):
        facts.append(_fact(day(roll.randrange(2, 27)), "card", dollars(24, 96), "Meals",
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
        facts.append(_fact(day(17), "card", dollars(149, 399), "Education and training",
                           "Operations leadership course, quarterly module",
                           who="Front Range Leadership Institute"))

    # --- the bank
    facts += [
        _fact(day(1), "bank", 69500, "Rent and coworking",
              "Coworking membership, dedicated desk", who="Larimer Square Cowork",
              bank_text="ACH DEBIT LARIMER SQ COWORK MEMBERSHIP"),
        _fact(day(3), "bank", 31200, "Business liability",
              "Professional liability and general liability premium",
              who="Front Range Mutual", bank_text="ACH DEBIT FRONT RANGE MUTUAL INS PREM"),
        _fact(day(5), "bank", 45000, "Accounting",
              "Monthly bookkeeping and close", who="Ledger & Quill Bookkeeping",
              bank_text="ACH DEBIT LEDGER AND QUILL BKKPG"),
        _fact(day(8), "bank", 85000, "Website",
              "Website care and search work", who="Aviato Web Studio",
              payee=world.vendors["Erlich Bachman"],
              bank_text="ACH DEBIT AVIATO WEB STUDIO"),
        _fact(day(10), "bank", 145000, "Dues and memberships",
              "Owners' peer group, monthly dues", who="Mile High Owners Roundtable",
              bank_text="ACH DEBIT MILE HIGH OWNERS RNDTBL"),
        _fact(day(15), "bank", 3000, "Bank and merchant fees", "Monthly service fee",
              who="Front Range Bank", bank_text="FRONT RANGE BANK MONTHLY SERVICE FEE"),
    ]
    if month.month == 3:
        facts.append(_fact(day(18), "bank", 185000, "Accounting",
                           f"{month.year - 1} tax return preparation",
                           who="Ledger & Quill Bookkeeping",
                           bank_text="ACH DEBIT LEDGER AND QUILL TAX PREP"))
    if month.month % 3 == 1:
        facts.append(_fact(day(12), "bank", 75000, "Events and sponsorships",
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
                       "Payroll service fees", "Payroll platform fee",
                       who="Gusto", bank_text="GUSTO FEE 6772" + str(10 + index)))

    spent = sum(f["cents"] for f in facts if f["kind"] == "expense")
    net = sum(invoiced.values()) - spent
    draw = max(200_000, int(net * 0.94) // 50_000 * 50_000)
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
    and two refunds."""
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
                lines=[{"description": "Half-day workshop for the owners' forum: running a "
                                       "weekly leadership meeting that ends on time",
                        "quantity": "1", "unit_price_cents": 150_000}])
            billing.make_ready(workshop, actor=owner, role="FF")
            workshop = billing.send(workshop, actor=owner, role="FF")
        paid_on = month.replace(day=22)
        if paid_on < world.today - timedelta(days=10):
            _payment, entry = _pay(world, books, workshop, workshop.total_cents, paid_on,
                                   world.today, "check", dice("workshop"))
            finance.update_entry(entry, actor=owner,
                                 category=books["category"]["Workshops and speaking"])
        world.extra["workshop_invoice"] = workshop
    if month == _months_back(world, 5):
        with at(moment(month.replace(day=16), 15)):
            finance.create_entry(
                tenant, actor=owner, kind="income", direction="out",
                on_date=month.replace(day=16), amount_cents=50_000,
                category=books["category"]["Client fees"], account=books["bank"],
                description="Goodwill credit for the delayed route review, refunded by check",
                counterparty="Dunder Mifflin Paper",
                client_company=world.companies["Dunder Mifflin Paper"],
                reference="Check 2117")
    if month == _months_back(world, 4):
        with at(moment(month.replace(day=12), 15)):
            finance.create_entry(
                tenant, actor=owner, kind="expense", direction="in",
                on_date=month.replace(day=12), amount_cents=11_988,
                category=books["category"]["Software"],
                account=books["card"], counterparty="Adobe",
                description="Refund: second Acrobat seat cancelled after the annual renewal")


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
    world.extra["bank_import"] = batch
