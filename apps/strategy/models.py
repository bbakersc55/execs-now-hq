"""Module 4 — the strategy session (data model §6).

The shape of this module is set by one guarantee, AC-4.12: **a completed
session renders from its own frozen `template_snapshot` for ever.** Nothing in
a session points at a live template row — answers carry a `question_key` that
resolves inside the snapshot, and there is deliberately no foreign key to
`strategy_question`. Editing, reordering or deleting a question in the live
template therefore cannot cascade, cannot block, and cannot change a byte of
what a past session displays.

The soft delete on a question (`deleted_at`, with a key that is never reused)
is defence in depth, not the guarantee: it keeps keys resolvable for
forward-looking work — reporting across sessions, diffing a template against a
session, seeding a new template from an old one — so that a deleted-and-recreated
question can never quietly change what a historical answer appears to answer.

The second rule running through here is that **Claude proposes and a person
disposes** (R8). Drafted map rows land as `proposed` and reach the map only
when a person accepts them; the drafted mirror is held in its own
`proposed_mirror_*` columns so that accepting is a deliberate copy, never an
overwrite of something a person wrote.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class AskWhen(models.TextChoices):
    PRECALL = "precall", "On the pre-call form"
    LIVE = "live", "In the call"


class ResponseSchema(models.TextChoices):
    """FR-4.3 — what `strategy_answer.value` must look like, per question.

    The shapes: `free_text` {"text"}, `rating_1_10` {"rating", "comment"},
    `diagnostic_triple` {"said", "cause", "tried"}, `value_pair` {"value",
    "why"}, `agreed_note` {"agreed", "notes"}, `path_reaction` {"path",
    "reaction", "risk", "leaning"}. Validation reads the schema recorded in the
    session's snapshot, never the live question.
    """

    FREE_TEXT = "free_text", "Free text"
    RATING_1_10 = "rating_1_10", "Rating 1–10"
    DIAGNOSTIC_TRIPLE = "diagnostic_triple", "Said / cause / tried"
    VALUE_PAIR = "value_pair", "Value and why"
    AGREED_NOTE = "agreed_note", "Agreed, with notes"
    PATH_REACTION = "path_reaction", "Path reaction"


# FR-4.24 — the five things that never reach the prospect's PDF unless a person
# deliberately turns them on, one at a time. All false at creation (AC-4.9).
PDF_FLAG_KEYS = (
    "fractional_notes",          # the private note beside any answer
    "mechanics",                 # strategy_map_row.mechanics_note
    "diagnostic_observations",   # §4 observations written during the call
    "alignment_observation",     # §3 item 4 — never asked aloud (FR-4.17)
    "investment",                # all of §9 (also hidden from a VA, AC-4.13)
)


def default_pdf_include_flags() -> dict:
    return {key: False for key in PDF_FLAG_KEYS}


class StrategyTemplate(TenantScopedModel):
    """A tenant's question set. Beta seeds one: the owner's Operations template,
    verbatim from `docs/strategy_session_seed.md`."""

    name = models.CharField(max_length=200)
    discipline = models.CharField(max_length=40, default="operations")
    version = models.PositiveSmallIntegerField(default=1)
    is_default = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_template"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name", "version"],
                                    name="strategy_template_unique_name_version"),
            # "The default" has to mean one thing when a session is started.
            models.UniqueConstraint(
                fields=["tenant", "discipline"], condition=models.Q(is_default=True),
                name="strategy_template_one_default_per_discipline"),
        ]


class StrategySection(TenantScopedModel):
    """The seed's nine sections, with the time budgets that drive the live
    view's pacing (FR-4.15): 10 / 25 / 5 / 15 / 5 / 10 minutes."""

    template = models.ForeignKey(StrategyTemplate, on_delete=models.CASCADE,
                                 related_name="sections")
    code = models.CharField(max_length=40)
    title = models.CharField(max_length=255)
    position = models.PositiveSmallIntegerField(default=0)
    time_budget_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_section"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "template", "code"],
                                    name="strategy_section_unique_code"),
        ]


class StrategyQuestion(TenantScopedModel):
    """One question in the live template.

    `template` is carried alongside `section` on purpose: the key's uniqueness
    is per template, and a constraint cannot reach through a relation.
    """

    template = models.ForeignKey(StrategyTemplate, on_delete=models.CASCADE,
                                 related_name="questions")
    section = models.ForeignKey(StrategySection, on_delete=models.CASCADE,
                                related_name="questions")
    # Assigned once, never reused, and what a historical answer resolves by.
    key = models.CharField(max_length=80)
    prompt = models.TextField()
    ask_when = models.CharField(max_length=8, choices=AskWhen.choices,
                                default=AskWhen.LIVE)
    must_ask = models.BooleanField(default=False)           # the seed's ★
    area = models.CharField(max_length=80, blank=True, default="")
    response_schema = models.CharField(max_length=20, choices=ResponseSchema.choices,
                                       default=ResponseSchema.FREE_TEXT)
    is_fractional_observation = models.BooleanField(default=False)   # FR-4.17
    has_fractional_note = models.BooleanField(default=False)
    is_financial = models.BooleanField(default=False)                # AC-4.13
    position = models.PositiveSmallIntegerField(default=0)
    # Questions are never hard-deleted: a reused key would change what a past
    # answer appears to answer.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_question"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "template", "key"],
                                    name="strategy_question_unique_key"),
        ]
        indexes = [models.Index(fields=["tenant", "section", "position"])]


class StrategySession(TenantScopedModel):
    """One session with one prospect, from invite to conversion."""

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PRECALL_SENT = "precall_sent", "Pre-call form sent"
        PRECALL_COMPLETE = "precall_complete", "Pre-call form complete"
        IN_CALL = "in_call", "In the call"
        COMPLETE = "complete", "Complete"
        CONVERTED = "converted", "Converted to work"
        LOST = "lost", "Lost"

    # FR-4.5 — the whole template as it was run. This, not `template`, is what
    # a completed session renders from.
    template_snapshot = models.JSONField(default=dict, blank=True)
    # Provenance only, and nullable so retiring a template cannot take a
    # session's history with it.
    template = models.ForeignKey(StrategyTemplate, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="sessions")
    # PROTECT, not CASCADE: a session is a record of a real meeting and the PDF
    # sent after it. Deleting a contact must not silently erase that.
    contact = models.ForeignKey("crm.Contact", on_delete=models.PROTECT,
                                related_name="strategy_sessions")
    company = models.ForeignKey("crm.Company", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    # The merge fields. A null Integrator renders the graceful note (FR-4.9a).
    visionary_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="+")
    integrator_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name="+")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    # When the call actually began — stamped the first time the session enters
    # `in_call`, so the live view can show elapsed against the template's
    # budgets (FR-4.15). Scheduled is when it was meant to start; this is when
    # it did, and a call that starts late should not read as 20 minutes over.
    started_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices,
                             default=State.DRAFT, db_index=True)
    # FR-4.6 — the public form is reached by a signed token; only its hash is
    # stored, and it expires in 30 days.
    precall_token_hash = models.CharField(max_length=64, blank=True, default="")
    precall_expires_at = models.DateTimeField(null=True, blank=True)
    # The second way the questions can go out (owner, 2026-09-21): in the body
    # of an email, for a prospect who will not click a link. Set when that send
    # happens, and it is what tells the live view the answers below were typed
    # in from a reply rather than filled in by the prospect themselves.
    precall_questions_sent_at = models.DateTimeField(null=True, blank=True)
    # FR-4.19 — what Claude drafted, held apart from what a person accepted.
    proposed_mirror_goal = models.TextField(blank=True, default="")
    proposed_mirror_unlocks = models.TextField(blank=True, default="")
    mirror_goal = models.TextField(blank=True, default="")
    mirror_unlocks = models.TextField(blank=True, default="")
    pdf_file = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    pdf_include_flags = models.JSONField(default=default_pdf_include_flags, blank=True)
    # FR-4.15 — pacing, and the whole of what is kept for it: which section the
    # call is on, and when it got there. Deliberately not a per-section ledger:
    # a strategy session is not a stopwatch, and a history of every section a
    # fractional clicked through would be state nobody reads.
    current_section = models.CharField(max_length=40, blank=True, default="")
    current_section_at = models.DateTimeField(null=True, blank=True)
    # FR-4.18a — which diagnostic areas have already fired the automatic draft.
    # Kept here rather than inferred from `ai_call`, which records that a run
    # happened but not what completed it; without this the second trigger would
    # re-fire on every save once an area was full.
    drafted_areas = models.JSONField(default=list, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_session"
        indexes = [
            models.Index(fields=["tenant", "state"]),
            models.Index(fields=["tenant", "contact"]),
        ]
        constraints = [
            # A token that resolves to two sessions is a security bug, not a
            # collision to be tolerated. Empty means "no live token".
            models.UniqueConstraint(
                fields=["tenant", "precall_token_hash"],
                condition=~models.Q(precall_token_hash=""),
                name="strategy_session_unique_precall_token"),
        ]


class StrategyAnswer(TenantScopedModel):
    """One answer, resolved by key against the session's own snapshot.

    There is deliberately no foreign key to `strategy_question`. That absence
    is what makes AC-4.12 structural rather than a rule someone has to keep.
    """

    class AnsweredBy(models.TextChoices):
        PROSPECT = "prospect", "The prospect, on the pre-call form"
        FRACTIONAL = "fractional", "The fractional, in the call"

    session = models.ForeignKey(StrategySession, on_delete=models.CASCADE,
                                related_name="answers")
    question_key = models.CharField(max_length=80)
    value = models.JSONField(default=dict, blank=True)
    # Private. Never rendered to the prospect, and absent from the PDF unless
    # the `fractional_notes` flag is deliberately turned on (FR-4.24).
    fractional_note = models.TextField(blank=True, default="")
    answered_by = models.CharField(max_length=12, choices=AnsweredBy.choices,
                                   default=AnsweredBy.FRACTIONAL)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_answer"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "session", "question_key"],
                                    name="strategy_answer_unique_per_question"),
        ]


class StrategySessionPrep(TenantScopedModel):
    """What the fractional knows about a prospect before the call, and what
    Claude made of it (owner, 2026-09-21).

    **Fractional-only, in every direction.** It never reaches the prospect: not
    the pre-call form, not the questions email, not the PDF. It is the
    equivalent of the notes a fractional would have made on the train, and the
    only thing that crosses from it into the prospect's world is a reworded
    question the fractional **copies into the template themselves**.
    """

    class State(models.TextChoices):
        DRAFTING = "drafting", "Drafting"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    session = models.OneToOneField(StrategySession, on_delete=models.CASCADE,
                                   related_name="prep")
    # What it was given.
    website_url = models.URLField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    # What it made of it. `summary` is what the company does and how it sells;
    # `bottlenecks` the ordinary ones for a business of that shape.
    summary = models.TextField(blank=True, default="")
    bottlenecks = models.JSONField(default=list, blank=True)
    #: [{"key": .., "current": .., "suggested": .., "why": ..}] — a suggestion
    #: per pre-call question. **Never applied by the app**: the fractional
    #: copies one into the template editor and saves it themselves.
    rewordings = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.DRAFTING)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_session_prep"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "session"],
                                    name="one_prep_per_session"),
        ]


class StrategyPrepQuestion(TenantScopedModel):
    """One of the five extra questions prep suggests asking live.

    **Pinned, it shows in the live view as a prompt with a note field** — and
    it is not an answer. It carries no `question_key`, is never scored, and
    never enters the session's snapshot, so AC-4.12 still holds: a session
    renders from the template it froze, and this sits beside that.
    """

    prep = models.ForeignKey(StrategySessionPrep, on_delete=models.CASCADE,
                             related_name="questions")
    session = models.ForeignKey(StrategySession, on_delete=models.CASCADE,
                                related_name="prep_questions")
    text = models.TextField()
    why = models.TextField(blank=True, default="")
    position = models.PositiveSmallIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    # The fractional's own note against it, and the only thing captured here.
    note = models.TextField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_prep_question"
        ordering = ["position", "created_at"]


class StrategyPathNote(TenantScopedModel):
    """A pro or a con on one of §8's two paths (owner, 2026-09-21).

    **A table and not a pair of fields on the session**, although the owner's
    note said "fields": accept, edit and discard are per item, which is the
    shape `StrategyMapRow` already has and the shape the tray already knows how
    to draw. Two JSON blobs would have meant reimplementing the tray's verbs on
    a list index.

    Same rule as every other thing Claude writes in this module: it lands
    `proposed`, and **only an accepted note reaches the prospect's PDF**.
    """

    class Path(models.TextChoices):
        A = "a", "Path A — continue to run it yourself"
        B = "b", "Path B — work with the practice"

    class Kind(models.TextChoices):
        PRO = "pro", "A pro"
        CON = "con", "A con"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed by Claude"
        ACCEPTED = "accepted", "Accepted onto the document"
        DISCARDED = "discarded", "Discarded"

    session = models.ForeignKey(StrategySession, on_delete=models.CASCADE,
                                related_name="path_notes")
    path = models.CharField(max_length=1, choices=Path.choices)
    kind = models.CharField(max_length=3, choices=Kind.choices)
    text = models.TextField()
    position = models.PositiveSmallIntegerField(default=0)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.PROPOSED, db_index=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    from_ai = models.BooleanField(default=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_path_note"
        ordering = ["path", "kind", "position", "created_at"]
        indexes = [models.Index(fields=["tenant", "session", "state"])]


class StrategyMapRow(TenantScopedModel):
    """A row of the Strategy Map: bottleneck → root cause → fix → owner →
    horizon → measurable.

    A row is on the map only when `state = accepted` (FR-4.18). `proposed` is
    the tray Claude writes into and a person accepts, edits or discards from.
    """

    class Horizon(models.IntegerChoices):
        THIRTY = 30, "30 days"
        SIXTY = 60, "60 days"
        NINETY = 90, "90 days"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed by Claude"
        ACCEPTED = "accepted", "Accepted onto the map"
        DISCARDED = "discarded", "Discarded"

    class ConvertedTo(models.TextChoices):
        GOAL = "goal", "A goal"
        PROJECT = "project", "A project"

    session = models.ForeignKey(StrategySession, on_delete=models.CASCADE,
                                related_name="map_rows")
    position = models.PositiveSmallIntegerField(default=0)
    bottleneck = models.TextField()
    root_cause = models.TextField(blank=True, default="")
    the_fix = models.TextField(blank=True, default="")
    # Free text: the owner is often the client's Integrator, who has no login.
    owner_text = models.CharField(max_length=200, blank=True, default="")
    horizon = models.PositiveSmallIntegerField(choices=Horizon.choices,
                                               null=True, blank=True)
    measurable = models.CharField(max_length=255, blank=True, default="")
    # Excluded from the PDF by default (FR-4.24.2).
    mechanics_note = models.TextField(blank=True, default="")
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.PROPOSED, db_index=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    # FR-4.28 — the per-row choice made at conversion.
    converted_to = models.CharField(max_length=8, choices=ConvertedTo.choices,
                                    blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_map_row"
        indexes = [models.Index(fields=["tenant", "session", "position"])]
        constraints = [
            # 30/60/90 is the vocabulary of the map itself, not a UI nicety.
            models.CheckConstraint(
                condition=models.Q(horizon__isnull=True) | models.Q(horizon__in=[30, 60, 90]),
                name="strategy_map_row_horizon_is_30_60_90"),
        ]
