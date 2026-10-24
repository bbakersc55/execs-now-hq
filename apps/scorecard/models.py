"""The KPI scorecard (M5, `docs/p6_m5_kpi_scorecard.md`), part 1: by hand.

One scorecard per client company (decision 1), split into pages the practice
names, each with an audience. A KPI is a definition; its numbers are readings,
one per period (one per person per period on a per-person KPI). Saving a
reading again replaces its value and keeps every value it has held in
`KpiReadingChange`, with who and when. Nothing here is ever deleted by the
app: a page or a KPI is archived and its readings kept.

Audiences reuse the levels and teams of the company's Teams card (P7): who
sees what is worked out from them when asked (`access.py`), never copied, so a
change on the Teams card shows on the scorecard at once.

A reading is a decimal in the KPI's own unit, as it was typed: a percent as
82, not 0.82; money in dollars; a duration in the KPI's hours or minutes.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.models import TenantScopedModel


class Scorecard(TenantScopedModel):
    """A client company's one scorecard. Made with its first page."""

    class WeekStart(models.TextChoices):
        MONDAY = "monday", "Monday to Sunday"
        SUNDAY = "sunday", "Sunday to Saturday"

    company = models.OneToOneField("crm.Company", on_delete=models.CASCADE,
                                   related_name="scorecard")
    #: Decided after the mock-up: a setting per company, Monday by default.
    week_start = models.CharField(max_length=6, choices=WeekStart.choices,
                                  default=WeekStart.MONDAY, db_default=WeekStart.MONDAY)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "scorecard"


class Audience(models.TextChoices):
    """Decision 6. Practice users always see everything."""

    EVERYONE = "everyone", "Everyone at the company"
    LEADERSHIP = "leadership", "Senior leadership and up"
    TEAM = "team", "One team"
    EACH_PERSON = "each_person", "Each person sees their own"


class ScorecardPage(TenantScopedModel):
    """A named page of the scorecard ("Weekly scorecard", "Sales") with its
    audience. A team audience whose team is archived reads as senior
    leadership and up: it narrows, never widens."""

    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="pages")
    name = models.CharField(max_length=80)
    position = models.PositiveSmallIntegerField(default=0, db_default=0)
    audience = models.CharField(max_length=12, choices=Audience.choices,
                                default=Audience.EVERYONE, db_default=Audience.EVERYONE)
    team = models.ForeignKey("work.ClientTeam", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "scorecard_page"
        ordering = ["position", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(audience="team") | Q(team__isnull=True),
                                   name="scorecard_page_team_only_for_a_team_audience"),
        ]


class Kpi(TenantScopedModel):
    """One KPI's definition (spec, "A KPI")."""

    class Kind(models.TextChoices):
        NUMBER = "number", "Number"
        PERCENT = "percent", "Percent"
        MONEY = "money", "Money"
        COUNT = "count", "Count"
        DURATION = "duration", "Duration"
        RATING = "rating", "Rating"

    class Direction(models.TextChoices):
        HIGHER = "higher", "Higher is better"
        LOWER = "lower", "Lower is better"
        RANGE = "range", "Within a range"

    class Cadence(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"

    class Rollup(models.TextChoices):
        SUM = "sum", "Sum"
        AVERAGE = "average", "Average"
        LAST = "last", "Last"

    class Tile(models.TextChoices):
        NUMBER_TREND = "number_trend", "Number with trend"
        GAUGE = "gauge", "Gauge"
        PROGRESS = "progress", "Progress"
        BARS = "bars", "Bars by period"
        LINE = "line", "Line"
        STATUS = "status", "Status"
        LEADERBOARD = "leaderboard", "Leaderboard"
        MY_ROW = "my_row", "My row"

    class KpiAudience(models.TextChoices):
        """A KPI narrows its page's audience, never widens it."""

        PAGE = "page", "Same as its page"
        LEADERSHIP = "leadership", "Senior leadership and up"
        TEAM = "team", "One team"
        EACH_PERSON = "each_person", "Each person sees their own"

    class DurationUnit(models.TextChoices):
        DAYS = "days", "Days"
        HOURS = "hours", "Hours"
        MINUTES = "minutes", "Minutes"

    class PersonTotal(models.TextChoices):
        SUM = "sum", "Sum"
        AVERAGE = "average", "Average"

    class Component(models.TextChoices):
        """The Six Key Components of the strategy session."""

        VISION = "vision", "Vision"
        PEOPLE = "people", "People"
        DATA = "data", "Data"
        ISSUES = "issues", "Issues"
        PROCESS = "process", "Process"
        TRACTION = "traction", "Traction"

    class Feed(models.TextChoices):
        HAND = "hand", "By hand"
        SHEET = "sheet", "Google Sheet"

    class Formula(models.TextChoices):
        """A computed KPI, one step only (spec, "Computed KPIs"): two other
        KPIs of the same scorecard and cadence, never themselves computed."""

        SUM = "sum", "Sum"
        DIFFERENCE = "difference", "Difference"
        RATIO = "ratio", "Ratio"
        AVERAGE = "average", "Average"

    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="kpis")
    page = models.ForeignKey(ScorecardPage, on_delete=models.PROTECT, related_name="kpis")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    direction = models.CharField(max_length=8, choices=Direction.choices,
                                 default=Direction.HIGHER, db_default=Direction.HIGHER)
    cadence = models.CharField(max_length=10, choices=Cadence.choices,
                               default=Cadence.WEEKLY, db_default=Cadence.WEEKLY)
    rollup = models.CharField(max_length=8, choices=Rollup.choices,
                              default=Rollup.SUM, db_default=Rollup.SUM)
    #: The fixed target; a seasonal KPI's month targets (`KpiMonthTarget`)
    #: take its place in the months they name.
    target_value = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    range_low = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    range_high = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    #: Decision 5: within this many percent short is Behind, worse is Off track.
    behind_band_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                          default=10, db_default=10)
    duration_unit = models.CharField(max_length=8, choices=DurationUnit.choices,
                                     blank=True, default="", db_default="")
    rating_scale = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Who is asked for the number when a period closes: a portal user of the
    #: company or someone at the practice.
    reading_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    per_person = models.BooleanField(default=False, db_default=False)
    person_total = models.CharField(max_length=8, choices=PersonTotal.choices,
                                    default=PersonTotal.SUM, db_default=PersonTotal.SUM)
    #: Decision 9: off by default.
    leaderboard = models.BooleanField(default=False, db_default=False)
    feed = models.CharField(max_length=12, choices=Feed.choices,
                            default=Feed.HAND, db_default=Feed.HAND)
    tile = models.CharField(max_length=14, choices=Tile.choices,
                            default=Tile.NUMBER_TREND, db_default=Tile.NUMBER_TREND)
    audience = models.CharField(max_length=12, choices=KpiAudience.choices,
                                default=KpiAudience.PAGE, db_default=KpiAudience.PAGE)
    audience_team = models.ForeignKey("work.ClientTeam", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=200, blank=True, default="", db_default="")
    strategy_component = models.CharField(max_length=10, choices=Component.choices,
                                          blank=True, default="", db_default="")
    #: Blank for a KPI with readings of its own; otherwise its value in each
    #: period is worked out from `source_a` and `source_b` and nobody enters it.
    formula = models.CharField(max_length=10, choices=Formula.choices, blank=True,
                               default="", db_default="")
    source_a = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    source_b = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    position = models.PositiveSmallIntegerField(default=0, db_default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    @property
    def is_computed(self) -> bool:
        return bool(self.formula)

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi"
        ordering = ["position", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(audience="team") | Q(audience_team__isnull=True),
                name="kpi_team_only_for_a_team_audience"),
            models.CheckConstraint(
                condition=Q(behind_band_pct__gte=0) & Q(behind_band_pct__lte=100),
                name="kpi_behind_band_is_a_percent"),
            models.CheckConstraint(
                condition=(Q(formula="") & Q(source_a__isnull=True) & Q(source_b__isnull=True))
                | (~Q(formula="") & Q(source_a__isnull=False) & Q(source_b__isnull=False)
                   & Q(per_person=False)),
                name="kpi_computed_has_two_sources"),
            models.CheckConstraint(
                condition=~Q(direction="range")
                | (Q(range_low__isnull=False) & Q(range_high__isnull=False)
                   & Q(range_low__lte=models.F("range_high"))),
                name="kpi_range_has_low_and_high"),
        ]

    def __str__(self):
        return self.name


class KpiMonthTarget(TenantScopedModel):
    """A seasonal KPI's target for one calendar month (decided after the
    mock-up: in part 1). A month with none uses the KPI's fixed target."""

    kpi = models.ForeignKey(Kpi, on_delete=models.CASCADE, related_name="month_targets")
    month = models.PositiveSmallIntegerField()
    value = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_month_target"
        constraints = [
            models.UniqueConstraint(fields=["kpi", "month"], name="kpi_month_target_once"),
            models.CheckConstraint(condition=Q(month__gte=1) & Q(month__lte=12),
                                   name="kpi_month_target_month_1_to_12"),
        ]


class KpiPerson(TenantScopedModel):
    """A person a per-person KPI tracks: a portal user of the company."""

    kpi = models.ForeignKey(Kpi, on_delete=models.CASCADE, related_name="people")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_person"
        constraints = [
            models.UniqueConstraint(fields=["kpi", "membership"], name="kpi_person_once"),
        ]


class KpiReading(TenantScopedModel):
    """One period's value of a KPI, or of one person on a per-person KPI.
    `period_start` is the first day of the KPI's period (the company's week
    start for a weekly one)."""

    class Source(models.TextChoices):
        HAND = "hand", "By hand"
        SHEET = "sheet", "Google Sheet"

    kpi = models.ForeignKey(Kpi, on_delete=models.CASCADE, related_name="readings")
    period_start = models.DateField()
    membership = models.ForeignKey("tenancy.Membership", null=True, blank=True,
                                   on_delete=models.CASCADE, related_name="+")
    value = models.DecimalField(max_digits=16, decimal_places=4)
    source = models.CharField(max_length=12, choices=Source.choices,
                              default=Source.HAND, db_default=Source.HAND)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    entered_at = models.DateTimeField()
    #: How many times the value has been replaced: a tile marks it "edited".
    times_changed = models.PositiveSmallIntegerField(default=0, db_default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_reading"
        constraints = [
            models.UniqueConstraint(fields=["kpi", "period_start"],
                                    condition=Q(membership__isnull=True),
                                    name="kpi_reading_one_per_period"),
            models.UniqueConstraint(fields=["kpi", "period_start", "membership"],
                                    condition=Q(membership__isnull=False),
                                    name="kpi_reading_one_per_person_per_period"),
        ]
        indexes = [models.Index(fields=["kpi", "period_start"], name="kpi_reading_by_period")]


class KpiReadingChange(TenantScopedModel):
    """Every value a reading has held, the first included, with who and when."""

    reading = models.ForeignKey(KpiReading, on_delete=models.CASCADE, related_name="changes")
    value = models.DecimalField(max_digits=16, decimal_places=4)
    previous_value = models.DecimalField(max_digits=16, decimal_places=4,
                                         null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_reading_change"
        ordering = ["created_at"]


class KpiReminder(TenantScopedModel):
    """The one reminder a reading owner gets when a period closes without a
    value. It shows in the app until the reading is in."""

    kpi = models.ForeignKey(Kpi, on_delete=models.CASCADE, related_name="reminders")
    period_start = models.DateField()
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="+")
    #: The client digest that carried it, once one did ("and in the next
    #: digest"). A digest that expires or is skipped gives it back.
    digest = models.ForeignKey("work.Digest", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_reminder"
        constraints = [
            models.UniqueConstraint(fields=["kpi", "period_start"], name="kpi_reminder_once"),
        ]


class KpiFeed(TenantScopedModel):
    """Where a KPI's readings come from when not by hand (M5 part 3, spec
    "Feeds"): a Google Sheet, read through the practice's Google connection
    in column mode (a date column, a value column and, per person, a name
    column) or cell mode (one cell, read at each period's close). A column is
    remembered by its heading as well as its letter, so a column inserted in
    the sheet moves nothing, and a heading that disappears is said by name.

    Stopping a feed keeps it here (inactive) and keeps every reading it made."""

    class Mode(models.TextChoices):
        COLUMN = "column", "By column"
        CELL = "cell", "One cell"

    class Refresh(models.TextChoices):
        HOURLY = "hourly", "Every hour"
        DAILY = "daily", "Once a day"

    kpi = models.OneToOneField(Kpi, on_delete=models.CASCADE, related_name="sheet_feed")
    #: The practice's Google connection it reads through. Checked against
    #: the feed's practice before every read (`feeds.client_for`).
    connection = models.ForeignKey("crm.GmailConnection", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    spreadsheet_id = models.CharField(max_length=128)
    spreadsheet_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    tab = models.CharField(max_length=200)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.COLUMN,
                            db_default=Mode.COLUMN)
    refresh = models.CharField(max_length=8, choices=Refresh.choices, default=Refresh.DAILY,
                               db_default=Refresh.DAILY)
    date_column = models.CharField(max_length=3, blank=True, default="", db_default="")
    date_header = models.CharField(max_length=200, blank=True, default="", db_default="")
    value_column = models.CharField(max_length=3, blank=True, default="", db_default="")
    value_header = models.CharField(max_length=200, blank=True, default="", db_default="")
    name_column = models.CharField(max_length=3, blank=True, default="", db_default="")
    name_header = models.CharField(max_length=200, blank=True, default="", db_default="")
    #: The row of headings, counted from 0; none when the data starts at the top.
    header_row = models.PositiveSmallIntegerField(null=True, blank=True)
    cell = models.CharField(max_length=12, blank=True, default="", db_default="")
    #: A cell feed's first period: the one open when it was set up. A period
    #: that had closed by then is never given the cell's later number.
    cell_from = models.DateField(null=True, blank=True)
    #: Names in the sheet chosen on the mapping screen: name -> membership id.
    people = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True, db_default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    #: What went wrong at the last read, in the reading owner's words; blank
    #: once a read succeeds. `error_since` is when this failure began.
    last_error = models.TextField(blank=True, default="", db_default="")
    error_since = models.DateTimeField(null=True, blank=True)
    last_counts = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "kpi_feed"
        constraints = [
            models.CheckConstraint(condition=~Q(mode="cell") | ~Q(cell=""),
                                   name="kpi_feed_cell_mode_has_a_cell"),
        ]

    def config(self) -> dict:
        """The mapping, as `feeds.clean` gives it."""
        return {"spreadsheet_id": self.spreadsheet_id, "tab": self.tab, "mode": self.mode,
                "refresh": self.refresh, "spreadsheet_name": self.spreadsheet_name,
                "date_column": self.date_column, "date_header": self.date_header,
                "value_column": self.value_column, "value_header": self.value_header,
                "name_column": self.name_column, "name_header": self.name_header,
                "header_row": self.header_row, "cell": self.cell, "people": self.people or {}}


# ---------------------------------------------------------------- bonus plans

def default_tiers():
    """The spec's tier table: under 80% earns nothing, 80 to 100 half, 100 to
    110 all of it, 110 and over 120%. Each row is where a tier starts (an
    achievement percent) and the share of the component it earns."""
    return [{"from": 0, "share": 0}, {"from": 80, "share": 50},
            {"from": 100, "share": 100}, {"from": 110, "share": 120}]


class BonusPlan(TenantScopedModel):
    """A bonus plan for one period of one company (M5 part 2, spec "Per-person
    KPIs and bonus plans"): the people on it, the amount each earns for a full
    period, and two to five weighted components. Copying it forward makes the
    next period's plan in the same `series`, which is how a person's earlier
    periods are found. It shows what is earned; it pays nothing (decision 8).

    Closing it freezes it: every person's result, with the readings, targets,
    weights and tiers it came from, is kept in `BonusResult` and shown from
    there ever after. A reading corrected later changes a closed period only
    when the client owner confirms (`BonusReopen`)."""

    class Period(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"

    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE,
                                  related_name="bonus_plans")
    series = models.UUIDField()
    name = models.CharField(max_length=120)
    period = models.CharField(max_length=10, choices=Period.choices,
                              default=Period.MONTHLY, db_default=Period.MONTHLY)
    period_start = models.DateField()
    #: Dollars for a full period, for everyone on the plan unless a person
    #: has an amount of their own.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    #: A straight line instead of tiers: the share is the achievement, capped.
    straight_line = models.BooleanField(default=False, db_default=False)
    cap_pct = models.DecimalField(max_digits=6, decimal_places=2, default=120,
                                  db_default=120)
    copied_from = models.ForeignKey("self", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "bonus_plan"
        ordering = ["-period_start", "name"]
        constraints = [
            models.UniqueConstraint(fields=["series", "period_start"],
                                    name="bonus_plan_one_per_period_of_a_series"),
            models.CheckConstraint(condition=Q(amount__gte=0),
                                   name="bonus_plan_amount_not_negative"),
            models.CheckConstraint(condition=Q(cap_pct__gte=0) & Q(cap_pct__lte=500),
                                   name="bonus_plan_cap_is_a_percent"),
        ]

    def __str__(self):
        return self.name


class BonusComponent(TenantScopedModel):
    """One weighted component of a plan: a per-person KPI, its weight (the
    weights of a plan add to 100), the period's target when it differs from
    what the KPI's own targets add up to, and its tier table."""

    plan = models.ForeignKey(BonusPlan, on_delete=models.CASCADE, related_name="components")
    kpi = models.ForeignKey(Kpi, on_delete=models.PROTECT, related_name="+")
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    target_value = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    tiers = models.JSONField(default=default_tiers)
    position = models.PositiveSmallIntegerField(default=0, db_default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "bonus_component"
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "kpi"], name="bonus_component_kpi_once"),
            models.CheckConstraint(condition=Q(weight__gt=0) & Q(weight__lte=100),
                                   name="bonus_component_weight_is_a_percent"),
        ]


class BonusPerson(TenantScopedModel):
    """A person on a plan: a portal user of the company. `amount` is theirs
    when it differs from the plan's; `joined_on` and `left_on` inside the
    period prorate them by days."""

    plan = models.ForeignKey(BonusPlan, on_delete=models.CASCADE, related_name="people")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="+")
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    left_on = models.DateField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "bonus_person"
        constraints = [
            models.UniqueConstraint(fields=["plan", "membership"],
                                    name="bonus_person_once_on_a_plan"),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0),
                                   name="bonus_person_amount_not_negative"),
        ]


class BonusResult(TenantScopedModel):
    """One person's result for a closed plan, frozen at the close: the amount
    earned and, in `detail`, every component's readings, target, achievement,
    tier and share it was worked out from. The Payroll list is these rows."""

    plan = models.ForeignKey(BonusPlan, on_delete=models.CASCADE, related_name="results")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="+")
    name = models.CharField(max_length=200)
    full_amount = models.DecimalField(max_digits=12, decimal_places=2)
    earned = models.DecimalField(max_digits=12, decimal_places=2)
    detail = models.JSONField(default=dict)

    class Meta(TenantScopedModel.Meta):
        db_table = "bonus_result"
        constraints = [
            models.UniqueConstraint(fields=["plan", "membership"],
                                    name="bonus_result_once_per_person"),
        ]


class BonusReopen(TenantScopedModel):
    """A closed plan's amounts worked out again from corrected readings, with
    the client owner's confirmation: who confirmed, and every person's amount
    before and after."""

    plan = models.ForeignKey(BonusPlan, on_delete=models.CASCADE, related_name="reopens")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                     on_delete=models.SET_NULL, related_name="+")
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)

    class Meta(TenantScopedModel.Meta):
        db_table = "bonus_reopen"
        ordering = ["created_at"]
