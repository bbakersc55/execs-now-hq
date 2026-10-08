"""The practice's books (`docs/p5_finance_accounting.md`).

Single-entry and cash-basis: one line per movement of money, in one category.
Income counts when the money arrives and an expense when it leaves. It is not
double-entry and it has no journal.

What these models hold to:

- **Money is integer cents, and an entry's amount is always positive.** Its
  kind (and, for owner money and tax held, its direction) says which way it
  went.
- **Only income and expense are in the P&L.** A transfer between the
  practice's own accounts, the owner's own money, and sales tax held for
  someone else are not earnings or costs.
- **Nothing is deleted.** An entry is removed with a reason and kept; an
  account is closed; a category is archived.
- **The practice owner's only** (matrix 13.1, 13.6–13.10). Nothing here is
  read by any other role, through any route.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.tenancy.models import TenantScopedModel


class FinanceAccount(TenantScopedModel):
    """Where the practice's money sits."""

    class Kind(models.TextChoices):
        BANK = "bank", "Bank account"
        CARD = "card", "Credit card"
        CASH = "cash", "Cash"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.BANK)
    last4 = models.CharField(max_length=4, blank=True, default="", db_default="")
    #: For a bank or cash account, what it held; for a card, what was owed.
    opening_balance_cents = models.BigIntegerField(default=0, db_default=0)
    opening_on = models.DateField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_account"
        ordering = ["kind", "name"]


class FinanceCategory(TenantScopedModel):
    class Type(models.TextChoices):
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"
        #: The owner's own money, in or out. Not earnings and not a cost.
        OWNER = "owner", "Owner"
        #: Collected for someone else (sales tax), until it is paid over.
        HELD = "held", "Held"

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=8, choices=Type.choices)
    position = models.PositiveSmallIntegerField(default=0)
    #: Free text the practice's CPA can ask for; carried into the export.
    cpa_code = models.CharField(max_length=40, blank=True, default="", db_default="")
    #: Set on the categories this module itself relies on.
    system_code = models.CharField(max_length=24, blank=True, default="", db_default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_category"
        ordering = ["type", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"],
                                    condition=Q(archived_at__isnull=True),
                                    name="finance_category_name_unique_live"),
        ]


class FinanceSettings(TenantScopedModel):
    #: Where a paid invoice's fee is entered ("Client fees" to begin with).
    invoice_income_category = models.ForeignKey(
        FinanceCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    #: Nothing dated on or before this can be added, changed or removed.
    locked_through = models.DateField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_settings"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="finance_settings_one_per_practice"),
        ]


class FinanceEntry(TenantScopedModel):
    class Kind(models.TextChoices):
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"
        TRANSFER = "transfer", "Transfer"
        OWNER = "owner", "Owner"
        HELD = "held", "Held"

    class Direction(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"

    class Source(models.TextChoices):
        MANUAL = "manual", "Typed in"
        INVOICE = "invoice", "From an invoice payment"
        IMPORT = "import", "From an import"

    #: The kinds the P&L is made of.
    EARNED = (Kind.INCOME, Kind.EXPENSE)

    kind = models.CharField(max_length=8, choices=Kind.choices)
    #: Which way the money went. Fixed by the kind for income (in) and expense
    #: (out); chosen for owner money and tax held; for a transfer, out of
    #: `account` and in to `to_account`.
    direction = models.CharField(max_length=3, choices=Direction.choices)
    on_date = models.DateField(db_index=True)
    amount_cents = models.BigIntegerField()
    category = models.ForeignKey(FinanceCategory, null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="entries")
    #: Empty on an invoice payment not yet placed in a bank account.
    account = models.ForeignKey(FinanceAccount, null=True, blank=True,
                                on_delete=models.PROTECT, related_name="entries")
    to_account = models.ForeignKey(FinanceAccount, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="entries_in")
    description = models.CharField(max_length=255, blank=True, default="", db_default="")
    counterparty = models.CharField(max_length=160, blank=True, default="", db_default="")
    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    reference = models.CharField(max_length=120, blank=True, default="", db_default="")
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL,
                              db_default=Source.MANUAL)
    client_payment = models.ForeignKey("billing.ClientPayment", null=True, blank=True,
                                       on_delete=models.PROTECT,
                                       related_name="finance_entries")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    remove_reason = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_entry"
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="finance_entry_amount_positive"),
            # A transfer moves between two different accounts and has no
            # category; nothing else names a second account.
            models.CheckConstraint(
                condition=(Q(kind="transfer", account__isnull=False,
                             to_account__isnull=False, category__isnull=True)
                           & ~Q(account=F("to_account")))
                | (~Q(kind="transfer") & Q(to_account__isnull=True)),
                name="finance_entry_transfer_shape"),
            models.CheckConstraint(
                condition=(~Q(kind="income") | Q(direction="in"))
                & (~Q(kind="expense") | Q(direction="out")),
                name="finance_entry_direction_fits_kind"),
            # One fee entry and at most one tax entry for an invoice payment.
            models.UniqueConstraint(fields=["tenant", "client_payment", "kind"],
                                    condition=Q(removed_at__isnull=True,
                                                client_payment__isnull=False),
                                    name="finance_entry_one_per_payment_and_kind"),
        ]
        indexes = [
            models.Index(fields=["tenant", "on_date"]),
            models.Index(fields=["tenant", "kind", "on_date"]),
        ]
