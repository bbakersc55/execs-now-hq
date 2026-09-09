"""Note — Module 2's table, created early for one Module 1 requirement.

FR-1.1a says a CSV notes column becomes a real `note` row, not a blob on the
contact (§12.2). That makes Module 1's import depend on this table, so it is
created here with ONLY the columns Module 1 needs.

Phase 2 adds the rest: pin_hash, pin_set_at, failed_pin_attempts,
pin_locked_until, transcript, summary, proposed_summary, summary_state,
audio_file, transcription_state, search_vector, and the task FK (Module 3).

Flagged for approval: the alternative is to defer the notes-column mapping to
Phase 2 and have Phase 1 skip that column with a warning. That would keep the
module boundary clean but leaves FR-1.1a untestable in Phase 1.
"""

from __future__ import annotations

from django.db import models

from apps.tenancy.models import TenantScopedModel


class Note(TenantScopedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "Written in the app"
        IMPORT = "import", "Created by a CSV import"
        RECORDING = "recording", "Transcribed from a recording"

    title = models.CharField(max_length=255, blank=True, default="")
    # FR-2.11a/2.11b — gates PIN-setting and stub rendering in Phase 2. The
    # column exists now so an imported note is correctly marked as having a
    # human-supplied (or absent) title rather than a derived one.
    title_is_auto = models.BooleanField(default=False)
    body = models.TextField(blank=True, default="")

    contact = models.ForeignKey(
        "crm.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    company = models.ForeignKey(
        "crm.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    # FR-1.31 — an import rollback removes the notes it created.
    import_batch = models.ForeignKey(
        "crm.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "note"
        constraints = [
            # FR-2.3a — a contact already implies its company.
            models.CheckConstraint(
                condition=~(models.Q(contact__isnull=False) & models.Q(company__isnull=False)),
                name="note_not_both_contact_and_company",
            )
        ]
