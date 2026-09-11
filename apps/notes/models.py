"""Notes — Module 2.

`note` was created in Phase 1 with only the columns FR-1.1a's CSV import
needed (owner ruling, data model §note). Phase 2 adds PIN gating, recording,
transcription, the proposed-summary review queue (R3), and search.

The two things this schema makes structural rather than leaving to view code:

1. **A locked note's body is never in the search index** (FR-2.11). The index
   is a Postgres generated column, so no code path — a view, a bulk update, an
   import, a data migration — can write a locked note with its body indexed.
   An auto-derived title is withheld too, since it IS the body's first line.
2. **No summary without acceptance** (FR-2.17, R3). A check constraint refuses
   a non-null `summary` unless `summary_state` is `accepted`; Claude's draft
   lives in `proposed_summary` until a person copies it across.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.db.models import Case, Q, Value, When
from django.db.models.functions import Cast
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel

# A generated column needs an explicit text-search config: the one-argument
# to_tsvector depends on a session setting, so Postgres will not index it.
SEARCH_CONFIG = "english"


def _vector(field, weight):
    return SearchVector(field, weight=weight, config=SEARCH_CONFIG)


class Note(TenantScopedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "Written in the app"
        IMPORT = "import", "Created by a CSV import"
        RECORDING = "recording", "Transcribed from a recording"

    class TranscriptionState(models.TextChoices):
        NONE = "none", "No recording"
        UPLOADING = "uploading", "Uploading"
        TRANSCRIBING = "transcribing", "Transcribing"
        DONE = "done", "Transcribed"
        FAILED = "failed", "Transcription failed"

    class SummaryState(models.TextChoices):
        NONE = "none", "No summary"
        DRAFTING = "drafting", "Claude is drafting"
        PROPOSED = "proposed", "Proposed — awaiting review"
        ACCEPTED = "accepted", "Accepted"
        DISCARDED = "discarded", "Discarded"
        FAILED = "failed", "Drafting failed"

    title = models.CharField(max_length=255, blank=True, default="")
    # FR-2.11a/2.11b — gates PIN-setting and stub rendering.
    title_is_auto = models.BooleanField(default=False)
    body = models.TextField(blank=True, default="")
    # CF scope (matrix 6.2: "owned") and R3 ("the note's author reviews").
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    # FR-2.3 — at most one of contact/company, and independently one task.
    contact = models.ForeignKey(
        "crm.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    company = models.ForeignKey(
        "crm.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    task = models.ForeignKey(
        "crm.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    # FR-1.31 — an import rollback removes the notes it created.
    import_batch = models.ForeignKey(
        "crm.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )

    # --- PIN (FR-2.8–2.13). A screen, not a vault: the body is NOT encrypted.
    pin_hash = models.CharField(max_length=128, null=True, blank=True)
    # Also the unlock epoch: an unlock older than this is void, so changing or
    # resetting a PIN revokes every open unlock without touching those rows.
    pin_set_at = models.DateTimeField(null=True, blank=True)
    failed_pin_attempts = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)

    # --- Recording (FR-2.14–2.19)
    # Recording audio lives under recordings/ (storage.py), which the backup
    # excludes; the retention job deletes the object and this goes null.
    audio_file = models.ForeignKey(
        "tenancy.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    audio_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    transcription_state = models.CharField(
        max_length=16, choices=TranscriptionState.choices, default=TranscriptionState.NONE
    )
    # Speech-to-Text long-running operation, so a restarted worker resumes
    # polling instead of paying to transcribe the same audio twice.
    transcription_operation = models.CharField(max_length=255, blank=True, default="")
    transcription_error = models.TextField(blank=True, default="")
    transcript = models.TextField(null=True, blank=True)

    # --- Summary — REVIEW QUEUE R3 (FR-2.17)
    proposed_summary = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    summary_state = models.CharField(
        max_length=16, choices=SummaryState.choices, default=SummaryState.NONE
    )

    # FR-2.7 / 2.11 — title, body and accepted summary when unlocked; the typed
    # title alone when locked; nothing when locked with an auto-derived title.
    # Transcript is not indexed (FR-2.7 names title, body, summary only).
    search_vector = models.GeneratedField(
        expression=Case(
            When(pin_hash__isnull=True,
                 then=_vector("title", "A") + _vector("body", "B") + _vector("summary", "B")),
            When(title_is_auto=False, then=_vector("title", "A")),
            default=Cast(Value(""), SearchVectorField()),
            output_field=SearchVectorField(),
        ),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "note"
        constraints = [
            # FR-2.3a — a contact already implies its company.
            models.CheckConstraint(
                condition=~(models.Q(contact__isnull=False) & models.Q(company__isnull=False)),
                name="note_not_both_contact_and_company",
            ),
            # A PIN without a set-time would make every unlock look current.
            models.CheckConstraint(
                condition=Q(pin_hash__isnull=True, pin_set_at__isnull=True)
                | Q(pin_hash__isnull=False, pin_set_at__isnull=False),
                name="note_pin_hash_and_set_at_together",
            ),
            # R3 — Claude's draft can reach `summary` only through acceptance.
            models.CheckConstraint(
                condition=Q(summary__isnull=True) | Q(summary_state="accepted"),
                name="note_summary_only_when_accepted",
            ),
        ]
        indexes = [
            GinIndex(fields=["search_vector"], name="note_search_gin"),
        ]

    @property
    def is_locked(self) -> bool:
        return self.pin_hash is not None


class NotePinUnlock(TenantScopedModel):
    """FR-2.9 — one note, one user, one browser session, at most 30 minutes.

    Valid only while `expires_at` is in the future AND `unlocked_at` is not
    older than the note's `pin_set_at`.
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="pin_unlocks")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    session_key = models.CharField(max_length=40)
    unlocked_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta(TenantScopedModel.Meta):
        db_table = "note_pin_unlock"
        indexes = [
            models.Index(fields=["note", "user", "session_key"], name="note_unlock_lookup"),
        ]
