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

from decimal import Decimal

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
    #: Decision 15: "I want at least this much in the household's accounts."
    forecast_floor_cents = models.BigIntegerField(null=True, blank=True)
    #: Decision 16: the payoff plan. Snowball (smallest balance first) is
    #: the default; Avalanche (highest rate first) a switch away.
    payoff_order = models.CharField(max_length=10, default="snowball", db_default="snowball")
    payoff_extra_cents = models.BigIntegerField(default=0, db_default=0)
    #: Decision 17: the yearly return assumed for retirement and investments.
    assumed_return_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                                 default=Decimal("6.00"),
                                                 db_default=Decimal("6.00"))

    class Meta:
        db_table = "personal_ledger"
        constraints = [
            models.CheckConstraint(condition=Q(payoff_order__in=("snowball", "avalanche")),
                                   name="personal_ledger_payoff_order"),
            models.CheckConstraint(condition=Q(payoff_extra_cents__gte=0),
                                   name="personal_ledger_payoff_extra_not_negative"),
        ]


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
    #: Decision 18, for an income category: whose pay it is. Empty: joint.
    whose = models.ForeignKey("PersonalMember", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")

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
    #: Decision 18: a spouse's expected W-2 withholding for the year, kept
    #: for the tax estimate (stop 4). Nothing reads it before then.
    expected_withholding_cents = models.BigIntegerField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

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
    #: The category its payments land in (a mortgage in "Rent or mortgage"):
    #: the forecast draws the payment as a Known line, not a Regular one.
    category = models.ForeignKey(PersonalCategory, null=True, blank=True,
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
    #: Contributions recognized from transfers: a line out of a household
    #: account whose description has this in it ("VANGUARD ROTH").
    contribution_text = models.CharField(max_length=120, blank=True, default="",
                                         db_default="")
    #: What goes in a month where no line shows it (paid from the practice,
    #: or from pay): typed by the owner.
    monthly_cents = models.BigIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_holding"
        ordering = ["kind", "name"]


class PersonalAsset(OwnedModel):
    """Decision 19: something owned with a value entered by hand (a home, a
    vehicle), valued on a date; no valuations fetched. A home against its
    mortgage is equity."""

    class Kind(models.TextChoices):
        HOME = "home", "Home"
        VEHICLE = "vehicle", "Vehicle"
        OTHER = "other", "Something else"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.HOME)
    whose = models.ForeignKey(PersonalMember, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    #: The loan against it: its value less that balance is the equity.
    debt = models.ForeignKey(PersonalDebt, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_asset"
        ordering = ["kind", "name"]


class PersonalBalance(OwnedModel):
    """What a debt was owed, a holding held, or a thing owned was worth, on a
    day: typed monthly or taken from a statement."""

    debt = models.ForeignKey(PersonalDebt, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="balances")
    holding = models.ForeignKey(PersonalHolding, null=True, blank=True,
                                on_delete=models.CASCADE, related_name="balances")
    asset = models.ForeignKey(PersonalAsset, null=True, blank=True, on_delete=models.CASCADE,
                              related_name="balances")
    on_date = models.DateField()
    balance_cents = models.BigIntegerField()

    class Meta:
        db_table = "personal_balance"
        ordering = ["on_date"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(debt__isnull=False) & Q(holding__isnull=True)
                           & Q(asset__isnull=True))
                | (Q(debt__isnull=True) & Q(holding__isnull=False) & Q(asset__isnull=True))
                | (Q(debt__isnull=True) & Q(holding__isnull=True) & Q(asset__isnull=False)),
                name="personal_balance_of_one_thing"),
        ]


class PersonalGoal(OwnedModel):
    """Decision 14: a name, a target, a date or none, what is saved already,
    and the account that holds it. Its envelope (`PersonalEnvelope.goal`)
    rolls, and its target is a planned line (`PersonalPlanned.goal`)."""

    name = models.CharField(max_length=120)
    target_cents = models.BigIntegerField()
    #: An emergency fund: the target is this many months of the everyday
    #: envelopes, worked out again whenever they change.
    months_of_envelopes = models.PositiveSmallIntegerField(null=True, blank=True)
    #: With no date, the monthly amount the owner chose; with a date it is
    #: worked out, and this is empty.
    monthly_cents = models.BigIntegerField(null=True, blank=True)
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


# -------------------------------------------- the budget (P6 M4 stop 2)

class PersonalEnvelope(OwnedModel):
    """Decision 10: a category with a monthly amount; or a goal's (decision
    14). Each month shows Planned, Spent and Left (`apps/personal/budget.py`
    works them out; nothing about a month is stored but moves and "let it
    stand"). Income categories have one too: what is planned to come in."""

    class Kind(models.TextChoices):
        EVERYDAY = "everyday", "Everyday"
        #: Goals, yearly bills, the tax envelope: Left rolls forward.
        SAVINGS = "savings", "Saving up"
        INCOME = "income", "Income"

    class Source(models.TextChoices):
        HISTORY = "history", "From your history"
        TYPED = "typed", "Set by you"
        GOAL = "goal", "For a goal"
        YEARLY = "yearly", "A yearly bill, spread"
        #: Decision 16: the payoff plan's extra a month.
        DEBT = "debt", "Extra toward debts"

    category = models.ForeignKey(PersonalCategory, null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="envelopes")
    goal = models.OneToOneField(PersonalGoal, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="envelope")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.EVERYDAY)
    #: Decision 11: Left carries into next month. The default follows the kind.
    rolls = models.BooleanField(default=False)
    planned_cents = models.BigIntegerField(default=0)
    #: What history proposed when it was made, kept beside what is planned.
    history_cents = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.HISTORY)
    #: A yearly bill spread monthly: the bill, and the month it falls in.
    yearly_cents = models.BigIntegerField(null=True, blank=True)
    yearly_month = models.PositiveSmallIntegerField(null=True, blank=True)
    #: The first month it counts in.
    start_month = models.DateField()
    #: Months an overspend was let stand ("YYYY-MM"): not asked about again.
    stood_months = models.JSONField(default=list, blank=True, db_default=[])
    position = models.PositiveSmallIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_envelope"
        ordering = ["kind", "position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "category"],
                                    condition=Q(archived_at__isnull=True,
                                                category__isnull=False),
                                    name="personal_envelope_one_per_category"),
            models.CheckConstraint(
                condition=Q(category__isnull=False) | Q(goal__isnull=False),
                name="personal_envelope_of_a_category_or_goal"),
        ]


class PersonalEnvelopeMove(OwnedModel):
    """Decision 10: an overspend covered from another envelope's Left, in one
    month. Made only when the owner chooses it."""

    month = models.DateField()
    from_envelope = models.ForeignKey(PersonalEnvelope, on_delete=models.CASCADE,
                                      related_name="moves_out")
    to_envelope = models.ForeignKey(PersonalEnvelope, on_delete=models.CASCADE,
                                    related_name="moves_in")
    amount_cents = models.BigIntegerField()

    class Meta:
        db_table = "personal_envelope_move"
        ordering = ["month", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="personal_envelope_move_positive"),
        ]


class PersonalPlanned(OwnedModel):
    """Something coming that history does not show (decision 13's last
    question), or a goal's target on its date (decision 14): a planned line,
    for the personal forecast (stop 3) and the Overview's "Coming up"."""

    class Direction(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"

    name = models.CharField(max_length=120)
    on_date = models.DateField()
    amount_cents = models.BigIntegerField()
    direction = models.CharField(max_length=3, choices=Direction.choices, default=Direction.OUT)
    goal = models.OneToOneField(PersonalGoal, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="planned")
    #: Decision 15: monthly, quarterly, yearly, or once ("").
    repeat = models.CharField(max_length=10, blank=True, default="", db_default="")
    #: A what-if: drawn beside the forecast when tried, never counted in it.
    is_what_if = models.BooleanField(default=False, db_default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_planned"
        ordering = ["on_date", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="personal_planned_amount_positive"),
        ]


class PersonalQuestion(OwnedModel):
    """Decision 13: one of the app's own questions about the budget, one
    screen each, any of them skippable. Asked after the proposal, and again
    when a category drifts 25% from plan for two months. `key` says what it
    is about, so the same question is never asked twice."""

    class Kind(models.TextChoices):
        KEEP_OR_TARGET = "keep", "Keep that, or set a target?"
        WHICH_NORMAL = "normal", "Which is normal?"
        YEARLY = "yearly", "A yearly bill?"
        COMING = "coming", "Anything coming?"

    class State(models.TextChoices):
        OPEN = "open", "Waiting"
        ANSWERED = "answered", "Answered"
        SKIPPED = "skipped", "Skipped"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    #: "proposal" or "drift".
    run = models.CharField(max_length=8, default="proposal")
    key = models.CharField(max_length=120)
    envelope = models.ForeignKey(PersonalEnvelope, null=True, blank=True,
                                 on_delete=models.CASCADE, related_name="+")
    category = models.ForeignKey(PersonalCategory, null=True, blank=True,
                                 on_delete=models.CASCADE, related_name="+")
    #: The question's words and its figures, as asked.
    text = models.CharField(max_length=300)
    detail = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    answer = models.JSONField(default=dict, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "personal_question"
        ordering = ["created_at", "position"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "key"],
                                    name="personal_question_once"),
        ]


# ------------------------------------- the personal forecast (stop 3)

class PersonalForecastSnapshot(OwnedModel):
    """Decision 15, "How good it has been": the forecast for a month as it
    stood when it was first worked out in that month. Never changed after it
    is taken. What happened is worked out from the lines each time it is
    shown: there is no month close on this side, and a statement often comes
    in days after its month ends."""

    month = models.DateField()
    taken_on = models.DateField()
    forecast = models.JSONField(default=dict)

    class Meta:
        db_table = "personal_forecast_snapshot"
        ordering = ["-month"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "month"],
                                    name="personal_forecast_snapshot_one_a_month"),
        ]


class PersonalForecastAdjustment(OwnedModel):
    """The owner's correction to a Regular line the forecast found: it is
    not regular, or it is another amount from a date. Undone, not deleted."""

    class Kind(models.TextChoices):
        NOT_REGULAR = "not_regular", "Not regular"
        AMOUNT = "amount", "Another amount"

    line_key = models.CharField(max_length=400)
    label = models.CharField(max_length=255)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount_cents = models.BigIntegerField(null=True, blank=True)
    from_date = models.DateField(null=True, blank=True)
    #: "review" when it came from "Review with Claude", confirmed by the owner.
    source = models.CharField(max_length=8, blank=True, default="", db_default="")
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_forecast_adjustment"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=("not_regular", "amount")),
                                   name="personal_forecast_adjustment_kind"),
        ]


#: Every model here, for the isolation family. A new model goes in here or
#: `tests/test_personal_sides.py` fails.
OWNED = (PersonalCategory, PersonalMember, PersonalAccount, PersonalReconciliation,
         PersonalLine, PersonalImport, PersonalImportRow, PersonalDebt, PersonalHolding,
         PersonalBalance, PersonalGoal, PersonalSetAside, PersonalEnvelope,
         PersonalEnvelopeMove, PersonalPlanned, PersonalQuestion, PersonalAsset,
         PersonalForecastSnapshot, PersonalForecastAdjustment)
