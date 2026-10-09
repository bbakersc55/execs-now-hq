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
    #: A sub-category's parent (P6 M1). One level only: a parent has none.
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    #: Where a combined category went: it is archived, and remembers.
    merged_into = models.ForeignKey("self", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    #: Money in it is paid to contractors, so each entry wants a person named
    #: for the 1099 report (the month close's fourth line).
    is_contractor = models.BooleanField(default=False, db_default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_category"
        ordering = ["type", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"],
                                    condition=Q(archived_at__isnull=True),
                                    name="finance_category_name_unique_live"),
        ]


class FinanceCategoryChange(TenantScopedModel):
    """A combine or a split: which entries moved between categories, when and
    by whom (P6 M1). It includes entries in closed months, on purpose, so
    "this export differs from the one I sent" has an answer."""

    class Kind(models.TextChoices):
        MERGE = "merge", "Combined"
        SPLIT = "split", "Split"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    from_category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT,
                                      related_name="+")
    to_category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT,
                                    related_name="+")
    entries_moved = models.PositiveIntegerField(default=0)
    #: The dates of the first and last entry it moved.
    first_on = models.DateField(null=True, blank=True)
    last_on = models.DateField(null=True, blank=True)
    #: For a split: the text it chose entries by, when it chose by text.
    contains = models.CharField(max_length=120, blank=True, default="", db_default="")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                           on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_category_change"
        ordering = ["-created_at"]


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
    #: Which way the money went. Income is normally in and an expense out; the
    #: other way round is a refund, and takes away from its category. Chosen
    #: for owner money and tax held; for a transfer, out of `account` and in
    #: to `to_account`.
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
    #: The bank's own id for the line, where its export carries one: the
    #: surest way to know a line is already in the books.
    bank_id = models.CharField(max_length=120, blank=True, default="", db_default="")
    #: Who an expense was paid to, where that is a 1099 payee (§1099).
    payee_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
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
            models.CheckConstraint(condition=Q(direction__in=("in", "out")),
                                   name="finance_entry_direction_in_or_out"),
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

    #: The way money normally goes for each earned kind. The other way is a
    #: refund.
    NATURAL = {Kind.INCOME: Direction.IN, Kind.EXPENSE: Direction.OUT}


class FinanceRule(TenantScopedModel):
    """Remembered from the owner's own choice: a line whose description
    contains this text is this category (or a transfer, or ignored). Applied
    in the next import's dry run, where it is shown beside the row it decided.
    No AI is involved."""

    class As(models.TextChoices):
        CATEGORY = "category", "A category"
        TRANSFER = "transfer", "A transfer"
        IGNORE = "ignore", "Ignore"

    contains = models.CharField(max_length=120)
    #: Empty means any account.
    account = models.ForeignKey(FinanceAccount, null=True, blank=True,
                                on_delete=models.CASCADE, related_name="+")
    treat_as = models.CharField(max_length=8, choices=As.choices, default=As.CATEGORY)
    category = models.ForeignKey(FinanceCategory, null=True, blank=True,
                                 on_delete=models.CASCADE, related_name="+")
    other_account = models.ForeignKey(FinanceAccount, null=True, blank=True,
                                      on_delete=models.CASCADE, related_name="+")
    payee_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_rule"
        ordering = ["position", "created_at"]


class FinanceImportProfile(TenantScopedModel):
    """The column mapping for one account's export, remembered, so next
    month's file from the same bank needs no mapping."""

    account = models.OneToOneField(FinanceAccount, on_delete=models.CASCADE,
                                   related_name="import_profile")
    mapping = models.JSONField(default=dict)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_import_profile"


class FinanceImportBatch(TenantScopedModel):
    """One bank or card export, in three steps: the dry run (which writes only
    this batch and its rows, never the books), the commit, and a rollback.

    Its own tables, not the contact import's: an assistant can read those."""

    class Status(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        COMMITTED = "committed", "Committed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT,
                                related_name="import_batches")
    filename = models.CharField(max_length=255)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRY_RUN)
    #: As the dry run used it, so the commit writes what was shown.
    mapping = models.JSONField(default=dict)
    counts = models.JSONField(default=dict)
    #: The bank's own running balance on the file's last line, where it has one.
    last_balance_cents = models.BigIntegerField(null=True, blank=True)
    last_balance_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    committed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_import_batch"


class FinanceImportRow(TenantScopedModel):
    class Outcome(models.TextChoices):
        NEW = "new", "New entry"
        DUPLICATE = "duplicate", "Already in the books"
        INVOICE_PAYMENT = "invoice_payment", "An invoice payment"
        TRANSFER = "transfer", "A transfer"
        TRANSFER_MATCH = "transfer_match", "The other side of a transfer"
        IGNORE = "ignore", "Ignored"
        ERROR = "error", "Cannot be read"

    batch = models.ForeignKey(FinanceImportBatch, on_delete=models.CASCADE,
                              related_name="rows")
    row_number = models.PositiveIntegerField()
    raw = models.JSONField(default=dict)
    on_date = models.DateField(null=True, blank=True)
    amount_cents = models.BigIntegerField(null=True, blank=True)
    #: Into the account, or out of it.
    direction = models.CharField(max_length=3, blank=True, default="", db_default="")
    description = models.CharField(max_length=255, blank=True, default="", db_default="")
    bank_id = models.CharField(max_length=120, blank=True, default="", db_default="")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    category = models.ForeignKey(FinanceCategory, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    other_account = models.ForeignKey(FinanceAccount, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    payee_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    #: What this line was matched to: an invoice payment's entry, or a
    #: transfer already in the books from its other side.
    matched_entry = models.ForeignKey(FinanceEntry, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="matched_rows")
    #: The rule that decided it, shown beside the row.
    rule = models.ForeignKey(FinanceRule, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    error_text = models.CharField(max_length=255, blank=True, default="", db_default="")
    #: What the commit made.
    entry = models.ForeignKey(FinanceEntry, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="import_rows")

    class Meta(TenantScopedModel.Meta):
        db_table = "finance_import_row"
        ordering = ["row_number"]
        indexes = [models.Index(fields=["tenant", "batch", "outcome"])]
