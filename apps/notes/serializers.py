"""Note representations. A locked note the requester has not unlocked is a
STUB — title (or "Locked note") and linked records, nothing else (FR-2.11).

The stub is built by listing what it may contain, never by removing fields
from a full representation: a field added later is absent from stubs until
someone decides it belongs there.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.crm import permissions as crm_perms
from apps.notes import access, recording, summary
from apps.notes.models import Note
from apps.tenancy.models import Role


def _links(note) -> dict:
    return {
        "contact": str(note.contact_id) if note.contact_id else None,
        "contact_name": (f"{note.contact.first_name} {note.contact.last_name}".strip()
                         if note.contact_id else ""),
        "company": str(note.company_id) if note.company_id else None,
        "company_name": note.company.name if note.company_id else "",
        "task": str(note.task_id) if note.task_id else None,
        "task_title": note.task.title if note.task_id else "",
    }


def represent(note, *, request, unlocked: set) -> dict:
    membership = request.membership
    readable = not note.is_locked or note.pk in unlocked
    data = {
        "id": str(note.pk),
        "title": access.display_title(note),
        "is_locked": note.is_locked,
        "unlocked": note.is_locked and readable,
        "stub": not readable,
        "created_at": note.created_at.isoformat(),
        # The reset exists precisely for a note its FF cannot open.
        "can_reset_pin": note.is_locked and membership.role == Role.FF,
        **_links(note),
    }
    if not readable:
        return data

    data.update({
        "title_is_auto": note.title_is_auto,
        "body": note.body,
        "source": note.source,
        "created_by": str(note.created_by_id) if note.created_by_id else None,
        "created_by_name": (note.created_by.full_name or note.created_by.email)
        if note.created_by_id else "",
        "updated_at": note.updated_at.isoformat(),
        "has_audio": note.audio_file_id is not None,
        "audio_duration_seconds": note.audio_duration_seconds,
        "transcription_state": note.transcription_state,
        "transcription_error": note.transcription_error,
        "no_speech": recording.is_speech_problem(note.transcription_error),
        "transcript": note.transcript,
        "summary_state": note.summary_state,
        "proposed_summary": note.proposed_summary,
        "summary": note.summary,
        "can_review_summary": summary.can_review(note, membership),
        "retention_overdue": recording.retention_overdue(note),
    })
    return data


def represent_many(notes, *, request) -> list:
    unlocked = access.unlocked_note_ids(request, notes)
    return [represent(n, request=request, unlocked=unlocked) for n in notes]


class NoteWriteSerializer(serializers.Serializer):
    """Validates input only. Links are checked against the requester's scope,
    so a CF cannot attach a note to a record they cannot see."""

    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    body = serializers.CharField(required=False, allow_blank=True)
    contact = serializers.UUIDField(required=False, allow_null=True)
    company = serializers.UUIDField(required=False, allow_null=True)
    task = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.ChoiceField(
        choices=[Note.Source.MANUAL, Note.Source.RECORDING], required=False
    )

    def _scoped(self, model, pk, scoper=None):
        if pk is None:
            return None
        request = self.context["request"]
        qs = model.objects.filter(pk=pk, deleted_at__isnull=True)
        if scoper is not None:
            qs = scoper(request, qs)
        found = qs.first()
        if found is None:
            raise serializers.ValidationError("Not found.")
        return found

    def validate_contact(self, value):
        from apps.crm.models import Contact

        return self._scoped(Contact, value, crm_perms.contact_queryset_for)

    def validate_company(self, value):
        from apps.crm.models import Company

        return self._scoped(Company, value, crm_perms.company_queryset_for)

    def validate_task(self, value):
        from apps.crm.models import Task

        return self._scoped(Task, value)

    def validate(self, attrs):
        instance = self.instance
        contact = attrs["contact"] if "contact" in attrs else getattr(instance, "contact", None)
        company = attrs["company"] if "company" in attrs else getattr(instance, "company", None)
        if contact is not None and company is not None:
            # FR-2.3a — a contact already implies its company.
            raise serializers.ValidationError(
                "Link a note to a contact or a company, not both — a contact "
                "already implies its company."
            )
        source = attrs.get("source") or getattr(instance, "source", Note.Source.MANUAL)
        body = attrs.get("body", getattr(instance, "body", ""))
        if source != Note.Source.RECORDING and not (body or "").strip():
            raise serializers.ValidationError({"body": "Write something first."})
        return attrs
