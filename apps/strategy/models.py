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

    class Format(models.TextChoices):
        CLASSIC = "classic", "Classic"
        #: "Operations — focused" (owner, 2026-09-29): Claude proposes the
        #: diagnostic from the pre-call form, map rows carry a header and a
        #: focus statement, the map is capped at five, and the PDF lays out
        #: 3–5 cards. Frozen into each session's snapshot, so a session keeps
        #: the format it was started with.
        FOCUSED = "focused", "Focused"
        #: Made in the template builder (P3, 2026-10-03): the practice's own
        #: questions, rated items and templated text. Each section carries a
        #: `kind`, and the template its `settings`. Like the other two, frozen
        #: into each session's snapshot.
        V3 = "v3", "Built in the template builder"

    format = models.CharField(max_length=10, choices=Format.choices,
                              default=Format.CLASSIC, db_default=Format.CLASSIC)
    #: A v3 template's own text and limits (`builder.SETTINGS`). Empty on every
    #: classic and focused template, and never read for them.
    settings = models.JSONField(default=dict, blank=True, db_default={})
    #: Retired from the picker, never deleted: a session's `template` link and
    #: its snapshot's provenance both still name it. The default cannot be
    #: archived — another has to take its place first.
    archived_at = models.DateTimeField(null=True, blank=True)

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
    #: What the section does in a v3 template (`builder.KINDS`). Empty on
    #: classic and focused templates, whose behavior is keyed on `code`.
    kind = models.CharField(max_length=16, blank=True, default="", db_default="")
    #: The practice's talk track for the section, for staff in the live view.
    #: Never on the pre-call form, an email or the PDF.
    intro = models.TextField(blank=True, default="", db_default="")
    #: A custom section's answers print on page two of the PDF.
    show_in_pdf = models.BooleanField(default=False, db_default=False)
    #: A removed section (v3 only). Kept, so its code and its questions' keys
    #: stay spent.
    deleted_at = models.DateTimeField(null=True, blank=True)

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
    #: Asked only if the call has time (owner, 2026-09-26) — the 60-minute
    #: template's unstarred diagnostic questions. A muted "if time" tag in the
    #: live view, and left out of the pre-call email.
    ask_if_time = models.BooleanField(default=False)
    #: One of the focused template's five fixed diagnostic questions, asked
    #: only when no proposed question has been accepted for the session
    #: (owner, 2026-09-29) — the pre-call form was not completed, or nothing
    #: Claude proposed was kept.
    is_diagnostic_fallback = models.BooleanField(default=False, db_default=False)
    #: A short name (v3): the chart label of a rated item, the chip label of a
    #: pre-call question.
    label = models.CharField(max_length=60, blank=True, default="", db_default="")
    #: A pre-call question whose answer shows in the PDF header (v3; three at
    #: most per template).
    pdf_chip = models.BooleanField(default=False, db_default=False)
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
    #: The fractional's own note about this session — what happened, what to do
    #: on the call. **Fractional-only**: it reaches no prospect surface, on the
    #: same standard as the prep brief.
    fractional_note = models.TextField(blank=True, default="")
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
    #: Out of the list, in any state, and restorable. Permanent delete is
    #: only from here, by the FF, and never for a converted session.
    archived_at = models.DateTimeField(null=True, blank=True)

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
        FRACTIONAL = "fractional", "The practice, in the call"

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
    #: Keys whose suggestion was refused because it would have changed the
    #: question's shape — a rating turned into an essay (incident, 2026-09-22).
    #: Kept rather than dropped silently: the fractional should be told that
    #: prep tried, and why it did not get its way.
    dropped_rewordings = models.JSONField(default=list, blank=True)
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
    #: What Claude drafted, before anyone edited it (owner, 2026-09-29).
    proposed_text = models.TextField(blank=True, default="", db_default="")

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
    #: The focused format (owner, 2026-09-29): a short bold header (3–6
    #: words) and one focus statement — all the PDF card shows. Drafted by
    #: Claude, editable. `proposed_*` keep what Claude drafted, so an edit
    #: before acceptance can teach the next draft this practice's style.
    header = models.CharField(max_length=120, blank=True, default="", db_default="")
    statement = models.TextField(blank=True, default="", db_default="")
    proposed_header = models.CharField(max_length=120, blank=True, default="",
                                       db_default="")
    proposed_statement = models.TextField(blank=True, default="", db_default="")
    # Excluded from the PDF by default (FR-4.24.2).
    mechanics_note = models.TextField(blank=True, default="")
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.PROPOSED, db_index=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    # FR-4.28 — the per-row choice made at conversion.
    converted_to = models.CharField(max_length=8, choices=ConvertedTo.choices,
                                    blank=True, default="")
    #: A consolidated row (dry run 2, 2026-09-26): the ids of the rows it
    #: merges, as Claude cited them. Empty on an ordinary row. Accepting it
    #: changes nothing about the originals — pruning them is a person's act.
    merged_from = models.JSONField(default=list, blank=True)
    #: Who wrote the row by hand, on the map (owner, 2026-10-08). Empty on a
    #: row Claude drafted and on one written before this existed.
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    #: A drafted row that rests on the call notes, and the passage it rests
    #: on, word for word from those notes. The practice's own, like the notes:
    #: never on the PDF, never to the prospect, never to an assistant.
    from_call_notes = models.BooleanField(default=False, db_default=False)
    source_passage = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_map_row"
        indexes = [models.Index(fields=["tenant", "session", "position"])]
        constraints = [
            # 30/60/90 is the vocabulary of the map itself, not a UI nicety.
            models.CheckConstraint(
                condition=models.Q(horizon__isnull=True) | models.Q(horizon__in=[30, 60, 90]),
                name="strategy_map_row_horizon_is_30_60_90"),
        ]



class StrategyDiagnosticProposal(TenantScopedModel):
    """A diagnostic question Claude proposes from the pre-call form, for the
    focused template (owner, 2026-09-29).

    The same rule as everything Claude writes here: it lands `proposed`, a
    person accepts, edits or discards it, and **only an accepted one is asked**.
    Accepting appends it to the session's own snapshot under a new key, so the
    answers resolve exactly as any other question's do.
    """

    class Rule(models.TextChoices):
        LOWEST_RATING = "lowest_rating", "One of the two lowest ratings"
        GROWTH = "growth", "They mentioned growth or expansion"
        SNAPSHOT_GAP = "snapshot_gap", "An evident gap in the Snapshot"
        #: v3 (P3): the same judgement, on a template with its own pre-call
        #: questions, and a question a person typed in during the call.
        PRECALL_GAP = "precall_gap", "An evident gap in the pre-call answers"
        MANUAL = "manual", "Added by hand during the session"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed by Claude"
        ACCEPTED = "accepted", "Accepted into the diagnostic"
        DISCARDED = "discarded", "Discarded"

    session = models.ForeignKey(StrategySession, on_delete=models.CASCADE,
                                related_name="diagnostic_proposals")
    rule = models.CharField(max_length=16, choices=Rule.choices)
    #: What in the pre-call answers it rests on, quoted, so the fractional can
    #: check the question against its reason.
    basis = models.TextField(blank=True, default="")
    prompt = models.TextField()
    proposed_prompt = models.TextField(blank=True, default="")
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.PROPOSED, db_index=True)
    position = models.PositiveSmallIntegerField(default=0)
    #: The snapshot key it was given on acceptance.
    question_key = models.CharField(max_length=80, blank=True, default="")
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_diagnostic_proposal"
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["tenant", "session", "state"])]


class StrategyStyleExample(TenantScopedModel):
    """What Claude drafted, and what the practice kept after editing it
    (owner, 2026-09-29). The most recent twelve go into the drafting prompts
    as examples of this practice's style. One row per drafted item and kind,
    updated when it is edited again.
    """

    class Kind(models.TextChoices):
        MAP_HEADER = "map_header", "Map row header"
        MAP_STATEMENT = "map_statement", "Map row focus statement"
        PRO = "pro", "A pro"
        CON = "con", "A con"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    proposed = models.TextField()
    accepted = models.TextField()
    source_type = models.CharField(max_length=40)
    source_id = models.UUIDField()

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_style_example"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "kind", "source_type", "source_id"],
                                    name="strategy_style_example_one_per_item"),
        ]
        indexes = [models.Index(fields=["tenant", "-updated_at"])]


class StrategyCallNotes(TenantScopedModel):
    """The notes of the call itself, attached to its session as context for
    Claude's drafts (owner, 2026-10-08).

    **The practice's own.** They are read by the practice owner and by an
    associate on their own prospect, and by Claude when it drafts rows,
    consolidates, or drafts the pros and cons. They never reach the pre-call
    form, an email, the PDF, the prospect or an assistant.

    A table of its own, not columns on the session, so nothing that reads or
    serializes a session carries them by accident.
    """

    class Source(models.TextChoices):
        MEETING_FILE = "meeting_file", "From the meeting queue"
        DRIVE = "drive", "A Drive document"
        PASTED = "pasted", "Pasted in"

    session = models.OneToOneField(StrategySession, on_delete=models.CASCADE,
                                   related_name="call_notes")
    text = models.TextField()
    source = models.CharField(max_length=14, choices=Source.choices)
    title = models.CharField(max_length=255, blank=True, default="", db_default="")
    source_file = models.ForeignKey("meetings.MeetingSourceFile", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    drive_file_id = models.CharField(max_length=128, blank=True, default="", db_default="")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "strategy_call_notes"
