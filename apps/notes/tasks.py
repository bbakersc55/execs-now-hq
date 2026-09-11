"""Scheduled work for Module 2.

Plain module-level functions taking primitives (assumption A1), each opening
an explicit tenant_context because a background job has no request.
Registered by `manage.py ensure_schedules`.
"""

from __future__ import annotations

from django.db import transaction

from apps.tenancy.context import tenant_context


def process_notes(tenant_id: str) -> dict:
    """Every minute: advance transcriptions, then draft queued summaries.

    Each note is claimed with SKIP LOCKED, so a run that overlaps the previous
    one (a long Claude call) never processes the same note twice.
    """
    from apps.notes import recording, summary
    from apps.notes.models import Note

    finished = drafted = 0
    with tenant_context(tenant_id):
        in_flight = list(Note.objects.filter(
            transcription_state=Note.TranscriptionState.TRANSCRIBING,
            deleted_at__isnull=True,
        ).values_list("pk", flat=True))
        for pk in in_flight:
            with transaction.atomic():
                note = (Note.objects.select_for_update(skip_locked=True, of=("self",))
                        .select_related("tenant", "audio_file").filter(pk=pk).first())
                if note is not None and recording.poll(note):
                    finished += 1

        queued = list(Note.objects.filter(
            summary_state=Note.SummaryState.DRAFTING, deleted_at__isnull=True,
        ).values_list("pk", flat=True))
        for pk in queued:
            with transaction.atomic():
                note = (Note.objects.select_for_update(skip_locked=True, of=("self",))
                        .select_related("tenant").filter(
                            pk=pk, summary_state=Note.SummaryState.DRAFTING).first())
                if note is not None:
                    summary.draft(note)
                    drafted += 1
    return {"transcriptions_finished": finished, "summaries_drafted": drafted}


def purge_expired_audio(tenant_id: str) -> dict:
    """Daily: FR-2.19 retention, under the owner's rule (see recording.py)."""
    from apps.notes import recording
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        return recording.purge_expired_audio(Tenant.objects.get(pk=tenant_id))
