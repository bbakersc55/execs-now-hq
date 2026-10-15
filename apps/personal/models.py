"""The owner's household money (P6 M4, `docs/p6_m4_personal_finance.md`).

**A person's, not a practice's** (the brief; decided 2026-10-15). Every row
here hangs off a `PersonalLedger`, which belongs to one user. These are
deliberately **not** `TenantScopedModel`s: the ledger survives its owner
leaving any practice, and nobody reaches it but its owner. The isolation
family for this is `tests/test_personal_isolation.py`, which every model here
must be registered in (`OWNED` below).

What crosses into a practice's books does so as that practice's own
`FinanceEntry` rows (an owner draw, or an expense paid personally), linked
from here, never the other way round.

Same rules as the books: money is integer cents and an amount is always
positive (its direction says which way); nothing is deleted, a line is
removed with a reason; account numbers are never stored, only a last four.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.models import UUIDModel


class PersonalLedger(UUIDModel):
    """One person's household money. Made the first time they open it."""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="personal_ledger")
    #: Decision 5: a line with no rule under this goes to Everything else
    #: without asking; only lines at or over it wait in To sort.
    to_sort_threshold_cents = models.PositiveIntegerField(default=2500, db_default=2500)

    class Meta:
        db_table = "personal_ledger"


class OwnedModel(UUIDModel):
    """A row of one person's ledger. Read it through `of(user)`, never bare."""

    ledger = models.ForeignKey(PersonalLedger, on_delete=models.PROTECT,
                               related_name="%(class)s_set")

    class Meta:
        abstract = True

    @classmethod
    def of(cls, user):
        """This person's rows, and nobody else's."""
        return cls.objects.filter(ledger__owner=user)


class PersonalCategory(OwnedModel):
    """The personal chart (decision 4): two levels, separate from the
    practice's chart. A category may carry a Tax-deductible mark naming one
    group of the CPA's Itemized Deduction Worksheet."""

    class Type(models.TextChoices):
        EXPENSE = "expense", "Spending"
        INCOME = "income", "Income"
        #: Money moving between the owner's own accounts: not spending.
        TRANSFER = "transfer", "Transfer"

    class TaxGroup(models.TextChoices):
        NONE = "", "Not tax-deductible"
        MEDICAL = "medical", "Medical and dental"
        HEALTH_INSURANCE = "health_insurance", "Health insurance"
        INTEREST = "interest", "Interest paid"
        PROPERTY_TAX = "property_tax", "Property taxes"
        CHARITABLE = "charitable", "Charitable contributions"
        NON_CASH = "non_cash", "Non-cash donations"

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=8, choices=Type.choices, default=Type.EXPENSE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    position = models.PositiveSmallIntegerField(default=0)
    #: The categories this module relies on: Everything else, Transfers, Pay
    #: from the practice.
    system_code = models.CharField(max_length=24, blank=True, default="", db_default="")
    tax_group = models.CharField(max_length=20, choices=TaxGroup.choices, blank=True,
                                 default="", db_default="")
    archived_at = models.DateTimeField(null=True, blank=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        db_table = "personal_category"
        ordering = ["type", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "name"],
                                    condition=Q(archived_at__isnull=True),
                                    name="personal_category_name_unique_live"),
        ]


class PersonalAccount(OwnedModel):
    """An account that is the household's alone (decision 1: Personal). A
    Mixed account lives in the practice's books, where its business lines
    belong, and is listed beside these."""

    class Kind(models.TextChoices):
        BANK = "bank", "Bank account"
        CARD = "card", "Credit card"
        CASH = "cash", "Cash"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.BANK)
    last4 = models.CharField(max_length=4, blank=True, default="", db_default="")
    opening_balance_cents = models.BigIntegerField(default=0, db_default=0)
    opening_on = models.DateField()
    closed_at = models.DateTimeField(null=True, blank=True)
    # A bank connection (Plaid or similar) later, without rework (brief,
    # "Connections"). Unused in this round: nothing reads or writes them.
    connection_provider = models.CharField(max_length=24, blank=True, default="",
                                           db_default="")
    connection_ref = models.CharField(max_length=120, blank=True, default="", db_default="")
    connection_data = models.JSONField(default=dict, blank=True, db_default={})

    class Meta:
        db_table = "personal_account"
        ordering = ["kind", "name"]


class PersonalLine(OwnedModel):
    """One movement of the household's money, on the personal side.

    From a Personal account, or the personal side of a line in one of the
    practice's Mixed (or Business) accounts. Then `finance_entry` is the
    owner draw the books carry for it, and removing that entry removes this.
    No category yet is **To sort** (decision 5)."""

    class Direction(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"

    class Source(models.TextChoices):
        MANUAL = "manual", "Typed in"
        IMPORT = "import", "From an import"
        #: The personal side of a line in one of the practice's accounts.
        BOOKS = "books", "From a practice account"

    on_date = models.DateField(db_index=True)
    amount_cents = models.BigIntegerField()
    direction = models.CharField(max_length=3, choices=Direction.choices)
    category = models.ForeignKey(PersonalCategory, null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(PersonalAccount, null=True, blank=True,
                                on_delete=models.PROTECT, related_name="lines")
    finance_entry = models.ForeignKey("finance.FinanceEntry", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="personal_lines")
    description = models.CharField(max_length=255, blank=True, default="", db_default="")
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL,
                              db_default=Source.MANUAL)
    removed_at = models.DateTimeField(null=True, blank=True)
    remove_reason = models.TextField(blank=True, default="", db_default="")

    class Meta:
        db_table = "personal_line"
        ordering = ["-on_date", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="personal_line_amount_positive"),
            models.CheckConstraint(condition=Q(direction__in=("in", "out")),
                                   name="personal_line_direction_in_or_out"),
            # From one place: a personal account, or a line in the books.
            models.CheckConstraint(
                condition=Q(account__isnull=True) | Q(finance_entry__isnull=True),
                name="personal_line_one_source"),
        ]


#: Every model here, for the isolation family. A new model goes in here or
#: `tests/test_personal_isolation.py` fails.
OWNED = (PersonalCategory, PersonalAccount, PersonalLine)
