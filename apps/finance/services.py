"""Keeping the books (`docs/p5_finance_accounting.md` §1–§3).

Accounts, categories and entries; the lock; and the one hook from invoicing:
a payment recorded against an invoice becomes income in the same transaction.

What this module keeps true:

- **Nothing dated in a locked period changes.** Every write passes `_unlocked`.
- **An entry made from an invoice payment follows the payment.** Its amount
  and date are changed on the invoice, never here.
- **Every write is audited**, with what it was before and after.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceEntry, FinanceSettings,
)
from apps.tenancy.models import AuditEvent

K = FinanceEntry.Kind
D = FinanceEntry.Direction
T = FinanceCategory.Type

CLIENT_FEES = "client_fees"
SALES_TAX = "sales_tax"

#: The chart a practice starts with (owner, 2026-10-08, F7). Edited freely
#: afterwards: this is only ever the beginning.
DEFAULT_CHART = (
    (T.INCOME, ("Client fees", "Project fees", "Workshops and speaking",
                "Referral fees received", "Reimbursed expenses", "Other income")),
    (T.EXPENSE, ("Contractors and associates", "Payroll and wages",
                 "Payroll taxes and benefits", "Software and subscriptions",
                 "AI and API usage", "Marketing and advertising", "Travel", "Meals",
                 "Professional services (legal, accounting)", "Insurance",
                 "Office and supplies", "Rent and coworking", "Phone and internet",
                 "Education and training", "Dues and memberships",
                 "Bank and merchant fees", "Referral fees paid", "Taxes and licenses",
                 "Interest", "Other expenses")),
    (T.OWNER, ("Owner contribution", "Owner draw")),
    (T.HELD, ("Sales tax collected",)),
)
SYSTEM_CODES = {"Client fees": CLIENT_FEES, "Sales tax collected": SALES_TAX}

#: Which category types an entry of each kind may sit in.
TYPE_FOR_KIND = {K.INCOME: T.INCOME, K.EXPENSE: T.EXPENSE, K.OWNER: T.OWNER, K.HELD: T.HELD}


class FinanceError(Exception):
    """Refused, with a sentence for whoever asked."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def audit(tenant, verb, actor, target, **payload):
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb=f"finance.{verb}",
        target_type=target._meta.db_table, target_id=target.pk, payload=payload)


def _a_date(value, what) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise FinanceError(f"{what} is a date, as YYYY-MM-DD.") from None


def _cents(value, what, *, signed=False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinanceError(f"{what} is a whole number of cents.")
    if value < 0 and not signed:
        raise FinanceError(f"{what} cannot be negative.")
    return value


# ------------------------------------------------- the chart and the settings

@transaction.atomic
def ensure_chart(tenant) -> None:
    """The starting chart, once, for a practice that has no categories at all.
    A practice that has archived or renamed every one of them still has rows,
    so this never puts the defaults back."""
    if FinanceCategory.all_objects.filter(tenant=tenant).exists():
        return
    for kind, names in DEFAULT_CHART:
        for position, name in enumerate(names):
            FinanceCategory.all_objects.create(
                tenant=tenant, name=name, type=kind, position=position,
                system_code=SYSTEM_CODES.get(name, ""))


def settings_for(tenant) -> FinanceSettings:
    ensure_chart(tenant)
    row, made = FinanceSettings.all_objects.get_or_create(tenant=tenant)
    if made or row.invoice_income_category_id is None:
        row.invoice_income_category = FinanceCategory.all_objects.filter(
            tenant=tenant, system_code=CLIENT_FEES, archived_at__isnull=True).first()
        row.save(update_fields=["invoice_income_category", "updated_at"])
    return row


def _unlocked(tenant, *dates) -> None:
    """F8: nothing dated on or before the lock is added, changed or removed."""
    locked = settings_for(tenant).locked_through
    if locked is None:
        return
    for day in dates:
        if day is not None and day <= locked:
            raise FinanceError(
                f"The books are locked through {locked:%B} {locked.day}, {locked.year}. "
                "Move the lock back in the finance settings to change anything dated "
                "on or before it.", status=409)


@transaction.atomic
def update_settings(tenant, *, actor, locked_through=..., invoice_income_category=...):
    row = FinanceSettings.all_objects.select_for_update().get(pk=settings_for(tenant).pk)
    before = {"locked_through": row.locked_through.isoformat() if row.locked_through else None,
              "invoice_income_category": str(row.invoice_income_category_id or "")}
    if locked_through is not ...:
        row.locked_through = _a_date(locked_through, "The lock date") if locked_through \
            else None
        if row.locked_through and row.locked_through > timezone.localdate():
            raise FinanceError("The books cannot be locked into the future.")
    if invoice_income_category is not ...:
        category = invoice_income_category
        if category is None or category.type != T.INCOME or category.archived_at:
            raise FinanceError("Paid invoices go to an income category that is in use.")
        row.invoice_income_category = category
    row.save()
    audit(tenant, "settings_changed", actor, row, before=before, after={
        "locked_through": row.locked_through.isoformat() if row.locked_through else None,
        "invoice_income_category": str(row.invoice_income_category_id or "")})
    return row


# ------------------------------------------------------------------ accounts

def _clean_name(name, what) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise FinanceError(f"{what} needs a name.")
    if len(name) > 120:
        raise FinanceError(f"{what}'s name is 120 characters at most.")
    return name


@transaction.atomic
def save_account(tenant, *, actor, account=None, name=None, kind=None, last4=None,
                 opening_balance_cents=None, opening_on=None) -> FinanceAccount:
    made = account is None
    if made:
        account = FinanceAccount(tenant=tenant, opening_on=timezone.localdate())
        if name is None:
            raise FinanceError("An account needs a name.")
    if name is not None:
        account.name = _clean_name(name, "An account")
        clash = FinanceAccount.all_objects.filter(
            tenant=tenant, name__iexact=account.name, closed_at__isnull=True)
        if clash.exclude(pk=account.pk).exists():
            raise FinanceError(f"There is already an account called “{account.name}”.",
                               status=409)
    if kind is not None:
        if kind not in FinanceAccount.Kind.values:
            raise FinanceError("kind is bank, card or cash.")
        if not made and kind != account.kind and \
                FinanceEntry.all_objects.filter(Q(account=account) | Q(to_account=account),
                                                removed_at__isnull=True).exists():
            raise FinanceError("An account with entries keeps its kind: its balance "
                               "means something different as a card.", status=409)
        account.kind = kind
    if last4 is not None:
        last4 = str(last4).strip()
        if last4 and (len(last4) != 4 or not last4.isdigit()):
            raise FinanceError("The last four digits are four digits.")
        account.last4 = last4
    if opening_balance_cents is not None:
        account.opening_balance_cents = _cents(opening_balance_cents, "An opening balance",
                                               signed=True)
    if opening_on is not None:
        account.opening_on = _a_date(opening_on, "The opening date")
    account.save()
    audit(tenant, "account_created" if made else "account_changed", actor, account,
          name=account.name, kind=account.kind,
          opening_balance_cents=account.opening_balance_cents,
          opening_on=account.opening_on.isoformat())
    return account


@transaction.atomic
def set_account_closed(account, *, actor, closed: bool) -> FinanceAccount:
    account.closed_at = (account.closed_at or timezone.now()) if closed else None
    account.save(update_fields=["closed_at", "updated_at"])
    audit(account.tenant, "account_closed" if closed else "account_reopened", actor, account,
          name=account.name)
    return account


# ---------------------------------------------------------------- categories

def _used(category) -> bool:
    return FinanceEntry.all_objects.filter(category=category).exists()


@transaction.atomic
def save_category(tenant, *, actor, category=None, name=None, type=None, cpa_code=None):
    ensure_chart(tenant)
    made = category is None
    if made:
        if type not in T.values:
            raise FinanceError("type is income, expense, owner or held.")
        last = FinanceCategory.all_objects.filter(tenant=tenant, type=type).aggregate(
            last=Max("position"))["last"]
        category = FinanceCategory(tenant=tenant, type=type,
                                   position=(last + 1) if last is not None else 0)
        if name is None:
            raise FinanceError("A category needs a name.")
    elif type is not None and type != category.type:
        # Fixed once used: an expense that became income would rewrite every
        # report that has already been read.
        if _used(category) or category.system_code:
            raise FinanceError(f"“{category.name}” has entries, so its type is fixed. "
                               "Add a new category instead.", status=409)
        if type not in T.values:
            raise FinanceError("type is income, expense, owner or held.")
        category.type = type
    if name is not None:
        category.name = _clean_name(name, "A category")
        clash = FinanceCategory.all_objects.filter(
            tenant=tenant, name__iexact=category.name, archived_at__isnull=True)
        if clash.exclude(pk=category.pk).exists():
            raise FinanceError(f"There is already a category called “{category.name}”.",
                               status=409)
    if cpa_code is not None:
        cpa_code = " ".join(str(cpa_code).split())
        if len(cpa_code) > 40:
            raise FinanceError("A CPA code is 40 characters at most.")
        category.cpa_code = cpa_code
    category.save()
    audit(tenant, "category_created" if made else "category_changed", actor, category,
          name=category.name, type=category.type, cpa_code=category.cpa_code)
    return category


@transaction.atomic
def set_category_archived(category, *, actor, archived: bool) -> FinanceCategory:
    if archived:
        if category.system_code == SALES_TAX:
            raise FinanceError("“Sales tax collected” is where tax on a paid invoice is "
                               "held, and stays.", status=409)
        if settings_for(category.tenant).invoice_income_category_id == category.pk:
            raise FinanceError(f"Paid invoices go to “{category.name}”. Choose another "
                               "category for them in the finance settings first.",
                               status=409)
        category.archived_at = category.archived_at or timezone.now()
    else:
        if FinanceCategory.all_objects.filter(
                tenant=category.tenant, name__iexact=category.name,
                archived_at__isnull=True).exclude(pk=category.pk).exists():
            raise FinanceError(f"There is another category called “{category.name}” now. "
                               "Rename one of them first.", status=409)
        category.archived_at = None
    category.save(update_fields=["archived_at", "updated_at"])
    audit(category.tenant, "category_archived" if archived else "category_restored", actor,
          category, name=category.name)
    return category


@transaction.atomic
def reorder_categories(tenant, *, actor, type, ids) -> None:
    rows = {str(row.pk): row for row in FinanceCategory.all_objects.filter(
        tenant=tenant, type=type, archived_at__isnull=True)}
    if not isinstance(ids, list) or sorted(str(i) for i in ids) != sorted(rows):
        raise FinanceError("The order has to name every category of that type, once.")
    for position, pk in enumerate(ids):
        row = rows[str(pk)]
        if row.position != position:
            row.position = position
            row.save(update_fields=["position", "updated_at"])


# ------------------------------------------------------------------- entries

def _state(entry) -> dict:
    return {"kind": entry.kind, "direction": entry.direction,
            "on_date": entry.on_date.isoformat(), "amount_cents": entry.amount_cents,
            "category": str(entry.category_id or ""), "account": str(entry.account_id or ""),
            "to_account": str(entry.to_account_id or ""), "description": entry.description,
            "counterparty": entry.counterparty}


def _own(tenant, row, what):
    if row is not None and row.tenant_id != tenant.pk:
        raise FinanceError(f"That {what} is not in this practice.", status=404)
    return row


def _shape(entry) -> None:
    """Hold an entry to what its kind means, in words, before the database
    refuses it in constraint names."""
    if entry.kind not in K.values:
        raise FinanceError("kind is income, expense, transfer, owner or held.")
    if entry.amount_cents <= 0:
        raise FinanceError("An entry is for more than nothing.")
    if entry.kind == K.TRANSFER:
        if entry.account_id is None or entry.to_account_id is None:
            raise FinanceError("A transfer names the account the money left and the one "
                               "it reached.")
        if entry.account_id == entry.to_account_id:
            raise FinanceError("A transfer is between two different accounts.")
        if entry.category_id is not None:
            raise FinanceError("A transfer has no category: it is not income or a cost.")
        entry.direction = D.OUT
        return
    if entry.to_account_id is not None:
        raise FinanceError("Only a transfer names a second account.")
    if entry.kind == K.INCOME:
        entry.direction = D.IN
    elif entry.kind == K.EXPENSE:
        entry.direction = D.OUT
    elif entry.direction not in D.values:
        raise FinanceError("Say whether the money came in or went out.")
    category = entry.category
    if category is not None:
        if category.type != TYPE_FOR_KIND[entry.kind]:
            raise FinanceError(f"“{category.name}” is not {_an(entry.kind)} category.")
    elif entry.kind in (K.OWNER, K.HELD):
        raise FinanceError("Choose a category.")
    if entry.account_id is None and entry.source != FinanceEntry.Source.INVOICE:
        raise FinanceError("Choose the account the money moved through.")


def _an(kind) -> str:
    return {"income": "an income", "expense": "an expense", "owner": "an owner",
            "held": "a held"}[kind]


EDITABLE = ("kind", "direction", "on_date", "amount_cents", "category", "account",
            "to_account", "description", "counterparty", "client_company", "reference")
#: What stays the invoice's own on an entry made from a payment (§3).
FROM_THE_INVOICE = ("kind", "direction", "on_date", "amount_cents", "to_account",
                    "client_company", "reference")


def _apply(tenant, entry, changes: dict) -> None:
    if "kind" in changes:
        entry.kind = changes["kind"]
    if "direction" in changes:
        entry.direction = changes["direction"] or ""
    if "on_date" in changes:
        entry.on_date = _a_date(changes["on_date"], "The date")
        if entry.on_date > timezone.localdate():
            raise FinanceError("An entry cannot be dated in the future.")
    if "amount_cents" in changes:
        entry.amount_cents = _cents(changes["amount_cents"], "An amount")
    for field, what in (("category", "category"), ("account", "account"),
                        ("to_account", "account"), ("client_company", "company")):
        if field in changes:
            setattr(entry, field, _own(tenant, changes[field], what))
    for field, most in (("description", 255), ("counterparty", 160), ("reference", 120)):
        if field in changes:
            setattr(entry, field, " ".join(str(changes[field] or "").split())[:most])
    for account in (entry.account, entry.to_account):
        if account is not None and account.closed_at is not None and \
                ("account" in changes or "to_account" in changes):
            raise FinanceError(f"“{account.name}” is closed.")
    if entry.category is not None and entry.category.archived_at is not None \
            and "category" in changes:
        raise FinanceError(f"“{entry.category.name}” is archived.")


@transaction.atomic
def create_entry(tenant, *, actor, **changes) -> FinanceEntry:
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise FinanceError(f"Not a field of an entry: {', '.join(sorted(unknown))}.")
    ensure_chart(tenant)
    entry = FinanceEntry(tenant=tenant, created_by=actor, amount_cents=0,
                         on_date=timezone.localdate(), kind="", direction="")
    _apply(tenant, entry, changes)
    _shape(entry)
    _unlocked(tenant, entry.on_date)
    entry.save()
    audit(tenant, "entry_added", actor, entry, after=_state(entry))
    return entry


@transaction.atomic
def update_entry(entry, *, actor, **changes) -> FinanceEntry:
    entry = FinanceEntry.all_objects.select_for_update().get(pk=entry.pk)
    if entry.removed_at is not None:
        raise FinanceError("That entry was removed.", status=409)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise FinanceError(f"Not a field of an entry: {', '.join(sorted(unknown))}.")
    if entry.source == FinanceEntry.Source.INVOICE:
        fixed = sorted(set(changes) & set(FROM_THE_INVOICE))
        if fixed:
            raise FinanceError(
                "This entry is an invoice payment. Its amount, date and client are the "
                "payment's: change them on the invoice. Here you can change its "
                "category, the account it landed in and its description.", status=409)
    before, was = _state(entry), entry.on_date
    _apply(entry.tenant, entry, changes)
    _shape(entry)
    _unlocked(entry.tenant, was, entry.on_date)
    entry.save()
    audit(entry.tenant, "entry_changed", actor, entry, before=before, after=_state(entry))
    return entry


@transaction.atomic
def remove_entry(entry, *, actor, reason, from_invoice=False) -> FinanceEntry:
    reason = str(reason or "").strip()
    if not reason:
        raise FinanceError("Say why the entry is being removed.")
    entry = FinanceEntry.all_objects.select_for_update().get(pk=entry.pk)
    if entry.removed_at is not None:
        raise FinanceError("That entry was already removed.", status=409)
    if entry.source == FinanceEntry.Source.INVOICE and not from_invoice:
        raise FinanceError("This entry is an invoice payment. Remove the payment on the "
                           "invoice, and this goes with it.", status=409)
    _unlocked(entry.tenant, entry.on_date)
    entry.removed_at = timezone.now()
    entry.removed_by = actor
    entry.remove_reason = reason
    entry.save(update_fields=["removed_at", "removed_by", "remove_reason", "updated_at"])
    audit(entry.tenant, "entry_removed", actor, entry, before=_state(entry), reason=reason)
    return entry


@transaction.atomic
def recategorize(tenant, *, actor, entries, category) -> int:
    """Several at once. All or nothing: one that cannot take the category
    refuses the lot, by name."""
    _own(tenant, category, "category")
    if category is None or category.archived_at is not None:
        raise FinanceError("Choose a category that is in use.")
    rows = list(FinanceEntry.all_objects.select_for_update().filter(
        tenant=tenant, pk__in=[entry.pk for entry in entries], removed_at__isnull=True))
    for entry in rows:
        if TYPE_FOR_KIND.get(entry.kind) != category.type:
            raise FinanceError(f"“{category.name}” is not {_an(category.type)} category "
                               f"an entry of {entry.on_date:%B} {entry.on_date.day} "
                               f"({entry.get_kind_display().lower()}) can take.")
        _unlocked(tenant, entry.on_date)
    for entry in rows:
        if entry.category_id == category.pk:
            continue
        before = _state(entry)
        entry.category = category
        entry.save(update_fields=["category", "updated_at"])
        audit(tenant, "entry_changed", actor, entry, before=before, after=_state(entry))
    return len(rows)


# -------------------------------------------------- paid invoices as income

def _tax_share(payment, invoice) -> int:
    """How much of this payment is sales tax, in the invoice's own proportion
    (F5). The last payment takes whatever tax is left, so the pieces add up to
    the invoice's tax exactly, however the cents fell before."""
    if invoice.tax_cents <= 0 or invoice.total_cents <= 0:
        return 0
    allocated = FinanceEntry.all_objects.filter(
        tenant_id=invoice.tenant_id, client_payment__invoice=invoice, kind=K.HELD,
        removed_at__isnull=True).aggregate(total=Sum("amount_cents"))["total"] or 0
    left = max(invoice.tax_cents - allocated, 0)
    if invoice.paid_cents >= invoice.total_cents:
        return min(left, payment.amount_cents)
    share = int((Decimal(payment.amount_cents) * invoice.tax_cents
                 / Decimal(invoice.total_cents)).quantize(Decimal("1"),
                                                         rounding=ROUND_HALF_UP))
    return min(share, left, payment.amount_cents)


@transaction.atomic
def payment_recorded(payment, *, actor=None) -> list[FinanceEntry]:
    """A payment recorded against an invoice becomes income, here, in the
    transaction that recorded it (§3). Safe to call again: a payment that has
    its entries gets no more."""
    invoice = payment.invoice
    tenant = invoice.tenant
    if payment.removed_at is not None or FinanceEntry.all_objects.filter(
            tenant=tenant, client_payment=payment, removed_at__isnull=True).exists():
        return []
    _unlocked(tenant, payment.paid_on)
    config = settings_for(tenant)
    tax = _tax_share(payment, invoice)
    fee = payment.amount_cents - tax
    who = invoice.client_company.name if invoice.client_company_id else str(invoice.contact)
    common = dict(
        tenant=tenant, on_date=payment.paid_on, client_company=invoice.client_company,
        client_payment=payment, description=f"Invoice {invoice.number}"[:255],
        counterparty=who[:160], reference=payment.reference,
        source=FinanceEntry.Source.INVOICE, created_by=actor)
    made = []
    if fee > 0:
        made.append(FinanceEntry.all_objects.create(
            kind=K.INCOME, direction=D.IN, amount_cents=fee,
            category=config.invoice_income_category, **common))
    if tax > 0:
        held = FinanceCategory.all_objects.filter(
            tenant=tenant, system_code=SALES_TAX).first()
        made.append(FinanceEntry.all_objects.create(
            kind=K.HELD, direction=D.IN, amount_cents=tax, category=held, **common))
    for entry in made:
        audit(tenant, "entry_added", actor, entry, after=_state(entry),
              invoice=invoice.number)
    return made


@transaction.atomic
def payment_removed(payment, *, actor=None, reason="") -> int:
    entries = FinanceEntry.all_objects.filter(
        tenant_id=payment.tenant_id, client_payment=payment, removed_at__isnull=True)
    count = 0
    for entry in entries:
        remove_entry(entry, actor=actor, from_invoice=True,
                     reason=reason or "The payment was removed from the invoice.")
        count += 1
    return count


def backfill_payments(tenant, *, apply: bool) -> int:
    """Entries for invoice payments recorded before the books existed (F13).
    Counts what it would write; writes only when told to."""
    from apps.billing.models import ClientPayment

    entered = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, client_payment__isnull=False)
    waiting = ClientPayment.all_objects.filter(
        tenant=tenant, removed_at__isnull=True).exclude(
            pk__in=entered.values("client_payment_id")).order_by("paid_on", "created_at")
    count = 0
    for payment in waiting:
        count += 1
        if apply:
            payment_recorded(payment)
    return count
