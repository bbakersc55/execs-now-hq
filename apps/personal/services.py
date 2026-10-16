"""The personal side's rules (P6 M4 stop 1): the ledger, its chart, and how a
line crosses between the practice's books and the owner's ledger.

**Decision 3, the marriage of the two sides.** A line in one of the
practice's accounts that is the owner's personal spending is, in the books,
an owner draw (money in: an owner contribution), and in the ledger the spend
itself, in its category. The draw is a real `FinanceEntry` of the practice,
so the books balance and the CPA sees the draw; the ledger line links to it,
and removing the draw (by hand, or an import's rollback) removes the line.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.finance import services as books
from apps.finance.models import FinanceCategory, FinanceEntry
from apps.personal.models import PersonalCategory, PersonalLedger, PersonalLine

K, D = FinanceEntry.Kind, FinanceEntry.Direction
EVERYTHING_ELSE = "everything_else"
TRANSFERS = "transfers"
PAY_FROM_PRACTICE = "pay_from_practice"
#: A personal account's line that was the practice's (decision 3): not the
#: household's spending, so a transfer-type category.
FOR_THE_PRACTICE = "for_the_practice"
G = PersonalCategory.TaxGroup

#: Decision 4's starting chart, two levels. A sub-category may carry the
#: Tax-deductible mark of one of the CPA's six groups (the placeholder's
#: table of 2026-10-10). "Everything else" is where small lines with no rule
#: go without asking (decision 5).
CHART = (
    ("expense", (
        ("Housing", (("Rent or mortgage", ""), ("Mortgage interest", G.INTEREST),
                     ("Home equity interest", G.INTEREST),
                     ("Property taxes", G.PROPERTY_TAX), ("Home maintenance", ""),
                     ("HOA dues", ""))),
        ("Utilities", (("Electric and gas", ""), ("Water and trash", ""),
                       ("Phone and internet", ""))),
        ("Groceries", ()),
        ("Dining", ()),
        ("Transportation", (("Fuel", ""), ("Car payment", ""), ("Car maintenance", ""),
                            ("Parking and tolls", ""), ("Rides and transit", ""))),
        ("Health", (("Doctors and dentists", G.MEDICAL), ("Prescriptions", G.MEDICAL),
                    ("Hospitals and nursing homes", G.MEDICAL),
                    ("Eyeglasses and contacts", G.MEDICAL),
                    ("Travel for medical", G.MEDICAL), ("Other medical", G.MEDICAL))),
        ("Insurance", (("Medical premiums", G.HEALTH_INSURANCE),
                       ("Medicare Part B", G.HEALTH_INSURANCE),
                       ("Long-term care premiums", G.HEALTH_INSURANCE),
                       ("Car insurance", ""), ("Home insurance", ""), ("Life insurance", ""))),
        ("Childcare and education", ()),
        ("Giving", (("Church", G.CHARITABLE), ("Schools", G.CHARITABLE),
                    ("Health charities", G.CHARITABLE), ("Other charities", G.CHARITABLE),
                    ("Non-cash donations", G.NON_CASH))),
        ("Personal care", ()),
        ("Entertainment and subscriptions", ()),
        ("Travel", ()),
        ("Gifts", ()),
        ("Pets", ()),
        ("Debt payments", (("Loan payments", ""), ("Student loans", ""))),
        ("Savings and retirement", ()),
        ("Taxes", (("Federal estimated tax", ""), ("State estimated tax", ""))),
        ("Everything else", ()),
    )),
    ("income", (
        ("Income", (("Pay from the practice", ""), ("Spouse pay", ""), ("Other income", ""))),
    )),
    ("transfer", (
        ("Transfers", ()),
        ("Paid for the practice", ()),
    )),
)
SYSTEM = {"Everything else": EVERYTHING_ELSE, "Transfers": TRANSFERS,
          "Pay from the practice": PAY_FROM_PRACTICE,
          "Paid for the practice": FOR_THE_PRACTICE}


class PersonalError(Exception):
    """Refused, with a sentence for whoever asked."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------- the ledger

@transaction.atomic
def ledger_for(user) -> PersonalLedger:
    """This person's ledger, made with its starting chart the first time."""
    ledger, made = PersonalLedger.objects.get_or_create(owner=user)
    if made or not PersonalCategory.objects.filter(ledger=ledger).exists():
        _seed_chart(ledger)
    return ledger


def _seed_chart(ledger) -> None:
    position = 0
    for type_, parents in CHART:
        for name, subs in parents:
            position += 1
            parent = PersonalCategory.objects.create(
                ledger=ledger, name=name, type=type_, position=position,
                system_code=SYSTEM.get(name, ""))
            for sub_position, (sub, mark) in enumerate(subs):
                PersonalCategory.objects.create(
                    ledger=ledger, name=sub, type=type_, parent=parent,
                    position=sub_position, tax_group=mark, system_code=SYSTEM.get(sub, ""))


def system_category(ledger, code) -> PersonalCategory | None:
    found = PersonalCategory.objects.filter(ledger=ledger, system_code=code,
                                            archived_at__isnull=True).first()
    if found is None and code == FOR_THE_PRACTICE:
        # A ledger made before this category was in the starting chart.
        name = next(name for name, value in SYSTEM.items() if value == code)
        found = PersonalCategory.objects.create(
            ledger=ledger, name=name, type=PersonalCategory.Type.TRANSFER,
            system_code=code, position=PersonalCategory.objects.filter(
                ledger=ledger, parent__isnull=True).count() + 1)
    return found


def personal_category(ledger, pk) -> PersonalCategory:
    """One of this ledger's live categories, or a refusal: another person's
    category is not found, as if it did not exist."""
    found = PersonalCategory.objects.filter(ledger=ledger, pk=pk).first() if pk else None
    if found is None:
        raise PersonalError("That personal category is not yours.", status=404)
    if found.archived_at is not None:
        raise PersonalError("Choose a category that is in use.")
    return found


# ---------------------------------------------- crossing into the books

def owner_category(tenant, direction) -> FinanceCategory:
    """Where the books carry the owner's personal spending: Owner draw for
    money out, Owner contribution for money in (the starting chart's)."""
    books.ensure_chart(tenant)
    name = "Owner draw" if direction == D.OUT else "Owner contribution"
    found = FinanceCategory.all_objects.filter(
        tenant=tenant, type=FinanceCategory.Type.OWNER, name=name,
        archived_at__isnull=True).first() or FinanceCategory.all_objects.filter(
        tenant=tenant, type=FinanceCategory.Type.OWNER, archived_at__isnull=True,
        parent__isnull=True).order_by("position").first()
    if found is None:
        raise PersonalError("This practice's chart has no owner category to carry personal "
                            "spending. Add Owner draw under Settings → Finance.")
    return found


def line_for_entry(entry, *, ledger, category, description=None) -> PersonalLine:
    """The ledger's line for an owner draw that stands for personal spending.
    One per entry: a second call updates it."""
    line = PersonalLine.objects.filter(finance_entry=entry, removed_at__isnull=True).first()
    fields = {"on_date": entry.on_date, "amount_cents": entry.amount_cents,
              "direction": entry.direction, "category": category,
              "description": entry.description if description is None else description}
    if line is None:
        return PersonalLine.objects.create(ledger=ledger, finance_entry=entry,
                                           source=PersonalLine.Source.BOOKS, **fields)
    for name, value in fields.items():
        setattr(line, name, value)
    line.save()
    return line


def entry_removed(entry, reason: str) -> int:
    """An entry left the books: its personal line leaves the ledger with it.
    A line paid personally stays, because the bank shows it, and waits to be
    sorted again."""
    paid_entry_left(entry)
    return PersonalLine.objects.filter(finance_entry=entry, removed_at__isnull=True).update(
        removed_at=timezone.now(), remove_reason=reason, updated_at=timezone.now())


def paid_entry_left(entry) -> int:
    """The books no longer carry this as paid personally: the personal
    account's line for it goes back to To sort."""
    return PersonalLine.objects.filter(paid_entry=entry, removed_at__isnull=True).update(
        paid_entry=None, category=None, updated_at=timezone.now())


def paid_personally(tenant, *, actor, line, category, amount_cents=None) -> FinanceEntry:
    """Decision 3: a line of a personal account that was the practice's. In
    the books, an income or expense in its category and in none of the
    practice's accounts (`Side.PAID_PERSONALLY`); in the ledger, the line
    stays in its account, in "Paid for the practice", linked to it."""
    if category is None or category.tenant_id != tenant.pk \
            or category.archived_at is not None \
            or category.type not in (FinanceCategory.Type.INCOME, FinanceCategory.Type.EXPENSE):
        raise PersonalError("Choose the practice's income or expense category for it.")
    from apps.finance.importer import _kind_for

    books._unlocked(tenant, line.on_date)
    entry = FinanceEntry.all_objects.create(
        tenant=tenant, kind=_kind_for(category, line.direction), direction=line.direction,
        on_date=line.on_date, amount_cents=amount_cents or line.amount_cents,
        category=category, account=None, description=line.description,
        source=FinanceEntry.Source.IMPORT if line.source == PersonalLine.Source.IMPORT
        else FinanceEntry.Source.MANUAL,
        side=FinanceEntry.Side.PAID_PERSONALLY, created_by=actor)
    books.audit(tenant, "entry_added", actor, entry, after=books._state(entry),
                paid_personally=True)
    return entry


@transaction.atomic
def sort_line(line, *, tenant, actor, side, category=None, personal_category=None,
              remember=None) -> PersonalLine:
    """A personal account's line put on a side after it is in (decision 2):
    personal, in `personal_category`; or the practice's, paid personally, in
    the business `category`."""
    line = PersonalLine.objects.select_for_update().get(pk=line.pk)
    if line.removed_at is not None:
        raise PersonalError("That line was removed.", status=409)
    if line.finance_entry_id is not None:
        return line             # the books' line: sorted through its entry
    if line.account_id is None:
        raise PersonalError("Only a line of one of your accounts can be put on a side.")
    if line.paid_entry_id is not None and side == "business":
        raise PersonalError("That line is already the practice's, paid personally.",
                            status=409)
    if side == "personal":
        if line.paid_entry_id is not None:
            books.remove_entry(line.paid_entry, actor=actor,
                               reason="Sorted to the personal side.")
            line.refresh_from_db()
        line.category = personal_category
    elif side == "business":
        entry = paid_personally(tenant, actor=actor, line=line, category=category)
        line.paid_entry = entry
        line.category = system_category(line.ledger, FOR_THE_PRACTICE)
    else:
        raise PersonalError("side is business or personal.")
    line.save()
    if remember:
        remember_rule(tenant, actor=actor, contains=remember, side=side,
                      category=category, personal_category=personal_category)
    return line


# ------------------------------------------------- the household's transfers

#: The two sides of a move rarely post on the same day (as the books').
TRANSFER_DAYS = 5


def transfer_candidates(ledger, *, account, on_date, amount_cents, direction):
    """Lines already in the ledger that could be the other side of this one
    (decision 7): another of the household's accounts (or the personal side
    of a Mixed account's line), the other way, the same amount, within a few
    days, not paired, and not yet sorted or already a transfer."""
    from datetime import timedelta

    from django.db.models import Q

    other_way = "in" if direction == "out" else "out"
    return (PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, transfer_pair__isnull=True,
        paid_entry__isnull=True, direction=other_way, amount_cents=amount_cents,
        on_date__gte=on_date - timedelta(days=TRANSFER_DAYS),
        on_date__lte=on_date + timedelta(days=TRANSFER_DAYS))
        .exclude(account=account)
        .filter(Q(category__isnull=True) | Q(category__type=PersonalCategory.Type.TRANSFER))
        .order_by("on_date", "created_at"))


def pair(one, other) -> None:
    """Two lines, one move: both in Transfers unless already a transfer."""
    transfers = system_category(one.ledger, TRANSFERS)
    for line, mate in ((one, other), (other, one)):
        line.transfer_pair = mate
        if line.category_id is None or line.category.type != PersonalCategory.Type.TRANSFER:
            line.category = transfers
        line.save(update_fields=["transfer_pair", "category", "updated_at"])


def unpair(line) -> None:
    PersonalLine.objects.filter(transfer_pair=line).update(transfer_pair=None,
                                                          updated_at=timezone.now())
    if line.transfer_pair_id:
        line.transfer_pair = None
        line.save(update_fields=["transfer_pair", "updated_at"])


def entry_changed(entry) -> None:
    """An owner draw edited in the books: its ledger line follows its date,
    amount and way, and keeps its category."""
    PersonalLine.objects.filter(finance_entry=entry, removed_at__isnull=True).update(
        on_date=entry.on_date, amount_cents=entry.amount_cents, direction=entry.direction,
        updated_at=timezone.now())


def threshold_category(ledger, amount_cents) -> PersonalCategory | None:
    """Decision 5: a line with no rule under the threshold is Everything else
    without asking; at or over it, nothing (it waits in To sort)."""
    if amount_cents < ledger.to_sort_threshold_cents:
        return system_category(ledger, EVERYTHING_ELSE)
    return None


@transaction.atomic
def sort_entry(entry, *, actor, side, category=None, personal_category=None,
               remember=None) -> FinanceEntry:
    """Put a line of one of the practice's accounts on a side after it is in
    the books (decision 2): from To sort, or moved from one side to the other.

    - `business`: an income or expense of the practice, in `category` (a
      business category, or none yet).
    - `personal`: an owner draw (contribution, for money in), and the spend in
      the owner's ledger under `personal_category`.

    Nothing moves in the bank: only what the line is. `remember` keeps the
    choice as a rule for lines that contain that text.
    """
    from apps.finance.importer import _kind_for

    entry = FinanceEntry.all_objects.select_for_update().get(pk=entry.pk)
    tenant = entry.tenant
    if entry.removed_at is not None:
        raise PersonalError("That entry was removed.", status=409)
    if entry.kind in (K.TRANSFER, K.HELD) or entry.client_payment_id \
            or entry.account_id is None:
        raise PersonalError("Only a line of one of your accounts can be put on a side.")
    if entry.side == FinanceEntry.Side.BUSINESS and entry.kind == K.OWNER:
        raise PersonalError("That is already the practice's owner money.")
    books._unlocked(tenant, entry.on_date)
    before = books._state(entry)
    ledger = ledger_for(actor)
    if side == "business":
        if category is not None and (category.tenant_id != tenant.pk
                                     or category.archived_at is not None
                                     or category.type not in ("income", "expense")):
            raise PersonalError("Choose an income or expense category that is in use.")
        entry.kind = _kind_for(category, entry.direction)
        entry.category = category
        entry.side = FinanceEntry.Side.BUSINESS if category else FinanceEntry.Side.TO_SORT
        entry.save()
        entry_removed(entry, "Sorted to the business side.")
    elif side == "personal":
        if personal_category is not None and personal_category.ledger_id != ledger.pk:
            raise PersonalError("That personal category is not yours.", status=404)
        entry.kind, entry.side = K.OWNER, FinanceEntry.Side.PERSONAL
        entry.category = owner_category(tenant, entry.direction)
        entry.estimated_tax = ""
        entry.payee_contact = None
        entry.save()
        line_for_entry(entry, ledger=ledger, category=personal_category)
    else:
        raise PersonalError("side is business or personal.")
    books.audit(tenant, "entry_sided", actor, entry, side=side, before=before,
                after=books._state(entry))
    if remember:
        remember_rule(tenant, actor=actor, contains=remember, side=side,
                      category=category, personal_category=personal_category,
                      account=entry.account)
    return entry


def remember_rule(tenant, *, actor, contains, side, category=None, personal_category=None,
                  account=None, split_percent=None):
    """Rules learn from every choice (decision 5)."""
    from apps.finance import rules as rule_service

    return rule_service.save_rule(
        tenant, actor=actor, contains=contains, treat_as="category",
        category=category if side in ("business", "split") else None,
        side=side, personal_category=personal_category if side != "business" else None,
        split_percent=split_percent if side == "split" else None)
