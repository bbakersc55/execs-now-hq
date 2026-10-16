"""The owner's household money (P6 M4, `docs/p6_m4_personal_finance.md`).

**A person's, not a practice's** (the brief; decided 2026-10-15). Every row
here hangs off a `PersonalLedger`, which belongs to one user. These are
deliberately **not** `TenantScopedModel`s: the ledger survives its owner
leaving any practice, and nobody reaches it but its owner. The isolation
family for this is `tests/test_personal_sides.py`, which every model here
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


class PersonalMember(OwnedModel):
    """A person in the household (decision 18): a label, not a sign-in. The
    owner is one ("You"); a spouse or partner is added. Accounts, debts and
    retirement carry whose they are; none is joint."""

    class Relation(models.TextChoices):
        SELF = "self", "You"
        SPOUSE = "spouse", "Spouse"
        PARTNER = "partner", "Partner"
        OTHER = "other", "Someone else"

    name = models.CharField(max_length=120)
    relation = models.CharField(max_length=8, choices=Relation.choices,
                                default=Relation.SPOUSE)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "personal_member"
        ordering = ["position", "name"]


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
    #: Whose it is (decision 18). Empty: joint, or not said.
    whose = models.ForeignKey(PersonalMember, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    #: The columns of this account's CSV export, remembered, as the books
    #: remember a practice account's.
    import_mapping = models.JSONField(default=dict, blank=True, db_default={})

    class Meta:
        db_table = "personal_account"
        ordering = ["kind", "name"]


class PersonalReconciliation(OwnedModel):
    """One statement of a personal account, ticked off against its lines
    (decision 8: optional, and no month close on the personal side). A
    Mixed account is reconciled in the books, with the business month."""

    class State(models.TextChoices):
        OPEN = "open", "In progress"
        FINISHED = "finished", "Reconciled"

    account = models.ForeignKey(PersonalAccount, on_delete=models.PROTECT,
                                related_name="reconciliations")
    statement_on = models.DateField()
    #: What the statement says the account held; for a card, what was owed.
    statement_balance_cents = models.BigIntegerField()
    #: The previous finished statement's ending balance, or the opening one.
    starting_balance_cents = models.BigIntegerField()
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    finished_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_reconciliation"
        ordering = ["statement_on", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=("open", "finished")),
                                   name="personal_reconciliation_state"),
        ]


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
    #: A line of a personal account that was the practice's (decision 3):
    #: the books' entry for it, an expense paid personally. The line stays
    #: here, because the bank shows it, in "Paid for the practice".
    paid_entry = models.ForeignKey("finance.FinanceEntry", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="paid_lines")
    #: Decision 7: the other side of a move between the household's own
    #: accounts, once both are in. A transfer is never spending.
    transfer_pair = models.ForeignKey("self", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    #: Ticked on this statement (decision 8).
    cleared_in = models.ForeignKey(PersonalReconciliation, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="cleared")
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
            # Paid for the practice from a personal account: a line of one.
            models.CheckConstraint(
                condition=Q(paid_entry__isnull=True) | Q(account__isnull=False),
                name="personal_line_paid_from_an_account"),
        ]


# ----------------------------------------- importing into a personal account

class PersonalImport(OwnedModel):
    """One statement of a personal account, in the books' three steps: the
    dry run (this and its rows only), the commit, and a rollback. The
    owner's own, like everything here: not the practice's import tables."""

    class Status(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        COMMITTED = "committed", "Committed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    account = models.ForeignKey(PersonalAccount, on_delete=models.PROTECT,
                                related_name="imports")
    #: Where its business lines went: the practice it was imported from.
    tenant = models.ForeignKey("tenancy.Tenant", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    filename = models.CharField(max_length=255)
    #: "csv", "ofx" or "pdf", as the books' import has them.
    source = models.CharField(max_length=4, default="csv", db_default="csv")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRY_RUN)
    mapping = models.JSONField(default=dict)
    counts = models.JSONField(default=dict)
    # A PDF statement only: what was read from it, and what the read cost.
    # The PDF itself is not kept on the personal side.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    opening_balance_cents = models.BigIntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    last_balance_cents = models.BigIntegerField(null=True, blank=True)
    last_balance_on = models.DateField(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_import"
        ordering = ["-created_at"]


class PersonalImportRow(OwnedModel):
    class Outcome(models.TextChoices):
        NEW = "new", "New line"
        DUPLICATE = "duplicate", "Already in"
        TRANSFER_MATCH = "transfer_match", "The other side of a transfer"
        IGNORE = "ignore", "Ignored"
        ERROR = "error", "Cannot be read"

    class Side(models.TextChoices):
        PERSONAL = "personal", "Personal"
        #: The practice's, paid personally (decision 3).
        BUSINESS = "business", "Business"
        SPLIT = "split", "Split"
        TO_SORT = "to_sort", "To sort"

    batch = models.ForeignKey(PersonalImport, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    raw = models.JSONField(default=dict)
    on_date = models.DateField(null=True, blank=True)
    amount_cents = models.BigIntegerField(null=True, blank=True)
    direction = models.CharField(max_length=3, blank=True, default="", db_default="")
    description = models.CharField(max_length=255, blank=True, default="", db_default="")
    bank_id = models.CharField(max_length=120, blank=True, default="", db_default="")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    side = models.CharField(max_length=8, choices=Side.choices, default=Side.PERSONAL)
    category = models.ForeignKey(PersonalCategory, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    #: For a business or split line: the practice's category.
    business_category = models.ForeignKey("finance.FinanceCategory", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="+")
    split_business_cents = models.BigIntegerField(null=True, blank=True)
    #: The other side of a transfer, already in the ledger.
    matched_line = models.ForeignKey(PersonalLine, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    #: Its category before the commit made it a transfer, for a rollback.
    matched_category_before = models.ForeignKey(PersonalCategory, null=True, blank=True,
                                                on_delete=models.SET_NULL, related_name="+")
    rule = models.ForeignKey("finance.FinanceRule", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    error_text = models.CharField(max_length=255, blank=True, default="", db_default="")
    #: What the commit made: the line; for a business or split line, the
    #: practice's part of it in this account, and the books' entry.
    line = models.ForeignKey(PersonalLine, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    paid_line = models.ForeignKey(PersonalLine, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    paid_entry = models.ForeignKey("finance.FinanceEntry", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "personal_import_row"
        ordering = ["row_number"]


# ------------------- for the later stops: kept now, drawn from stop 2 on

class PersonalDebt(OwnedModel):
    """Decision 16. What it is owed over time is `PersonalBalance` rows."""

    class Kind(models.TextChoices):
        CARD = "card", "Credit card"
        AUTO = "auto", "Car loan"
        MORTGAGE = "mortgage", "Mortgage"
        STUDENT = "student", "Student loan"
        PERSONAL = "personal", "Personal loan"
        MEDICAL = "medical", "Medical"
        OTHER = "other", "Other"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    whose = models.ForeignKey(PersonalMember, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    #: The yearly rate, in percent.
    rate_percent = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    minimum_cents = models.BigIntegerField(null=True, blank=True)
    due_day = models.PositiveSmallIntegerField(null=True, blank=True)
    original_cents = models.BigIntegerField(null=True, blank=True)
    opened_on = models.DateField(null=True, blank=True)
    #: A card that is also an imported account takes its balance from there.
    account = models.ForeignKey(PersonalAccount, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_debt"
        ordering = ["name"]


class PersonalHolding(OwnedModel):
    """Decision 17: a retirement or investment account, with a balance
    history and no live feed."""

    class Kind(models.TextChoices):
        RETIREMENT = "retirement", "Retirement"
        INVESTMENT = "investment", "Investment"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    whose = models.ForeignKey(PersonalMember, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    target_cents = models.BigIntegerField(null=True, blank=True)
    target_year = models.PositiveSmallIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_holding"
        ordering = ["kind", "name"]


class PersonalBalance(OwnedModel):
    """What a debt was owed, or a holding held, on a day: typed monthly or
    taken from a statement."""

    debt = models.ForeignKey(PersonalDebt, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="balances")
    holding = models.ForeignKey(PersonalHolding, null=True, blank=True,
                                on_delete=models.CASCADE, related_name="balances")
    on_date = models.DateField()
    balance_cents = models.BigIntegerField()

    class Meta:
        db_table = "personal_balance"
        ordering = ["on_date"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(debt__isnull=False) & Q(holding__isnull=True))
                | (Q(debt__isnull=True) & Q(holding__isnull=False)),
                name="personal_balance_of_one_thing"),
        ]


class PersonalGoal(OwnedModel):
    """Decision 14: a name, a target, a date or none, what is saved already,
    and the account that holds it."""

    name = models.CharField(max_length=120)
    target_cents = models.BigIntegerField()
    target_on = models.DateField(null=True, blank=True)
    saved_cents = models.BigIntegerField(default=0, db_default=0)
    account = models.ForeignKey(PersonalAccount, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_goal"
        ordering = ["position", "name"]


class PersonalSetAside(OwnedModel):
    """Decision 21: the quarterly tax set-aside for a year, so far."""

    year = models.PositiveSmallIntegerField()
    #: Of each draw from the practice.
    percent_per_draw = models.DecimalField(max_digits=5, decimal_places=2, null=True,
                                           blank=True)
    saved_cents = models.BigIntegerField(default=0, db_default=0)
    account = models.ForeignKey(PersonalAccount, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "personal_set_aside"
        constraints = [
            models.UniqueConstraint(fields=["ledger", "year"],
                                    name="personal_set_aside_one_a_year"),
        ]


#: Every model here, for the isolation family. A new model goes in here or
#: `tests/test_personal_sides.py` fails.
OWNED = (PersonalCategory, PersonalMember, PersonalAccount, PersonalReconciliation,
         PersonalLine, PersonalImport, PersonalImportRow, PersonalDebt, PersonalHolding,
         PersonalBalance, PersonalGoal, PersonalSetAside)
