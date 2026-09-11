"""Module 2 API — notes. Source of truth: `03_access_matrix.md` §6.

Status codes follow the matrix §1 rule: out of scope is 404 (a 403 would
confirm the note exists); in scope but refused is 403. A locked note that has
not been unlocked is readable only as its stub, and every action that would
read or change its content first requires the unlock.
"""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.notes import access, pins, recording, summary
from apps.notes.models import SEARCH_CONFIG, Note
from apps.notes.serializers import NoteWriteSerializer, represent, represent_many
from apps.tenancy import storage
from apps.tenancy.models import AuditEvent, Role

CONSENT_SESSION_KEY = "notes_consent_reminder_dismissed"
LIST_LIMIT = 200


def search_notes(request, term, *, limit=50):
    """FR-2.7 — against the generated index, so a locked note can only ever
    match on a typed title (see models.search_vector)."""
    query = SearchQuery(term, config=SEARCH_CONFIG, search_type="websearch")
    qs = access.note_queryset_for(
        request, Note.objects.filter(deleted_at__isnull=True, search_vector=query)
    ).select_related("contact", "company", "task", "created_by", "audio_file", "tenant")
    return list(qs.annotate(rank=SearchRank("search_vector", query))
                .order_by("-rank", "-created_at")[:limit])


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _recording_title(tenant) -> str:
    from zoneinfo import ZoneInfo

    local = timezone.now().astimezone(ZoneInfo(tenant.timezone))
    return f"Recording, {local:%b} {local.day}, {local:%-I:%M %p}"


class NoteViewSet(viewsets.GenericViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def get_queryset(self):
        return access.note_queryset_for(
            self.request,
            Note.objects.filter(deleted_at__isnull=True).select_related(
                "contact", "company", "task", "created_by", "audio_file", "tenant"
            ),
        )

    def _one(self, request):
        return represent(self.note, request=request,
                         unlocked=access.unlocked_note_ids(request, [self.note]))

    def _load(self, pk):
        from django.http import Http404

        if not _is_uuid(pk):
            raise Http404
        note = self.get_queryset().filter(pk=pk).first()
        if note is None:
            raise Http404
        self.note = note
        return note

    def _require_readable(self, request):
        if not access.can_read(request, self.note):
            return Response(
                {"detail": "This note is locked. Enter its PIN to continue.", "locked": True},
                status=403,
            )
        return None

    # ---------------------------------------------------------------- CRUD

    def list(self, request):
        term = (request.query_params.get("q") or "").strip()
        if term:
            notes = search_notes(request, term, limit=LIST_LIMIT)
        else:
            qs = self.get_queryset()
            for link in ("contact", "company", "task"):
                value = request.query_params.get(link)
                if value:
                    if not _is_uuid(value):
                        return Response({"detail": f"{link} must be an id."}, status=400)
                    qs = qs.filter(**{f"{link}_id": value})
            notes = list(qs.order_by("-created_at")[:LIST_LIMIT])
        return Response(represent_many(notes, request=request))

    def retrieve(self, request, pk=None):
        self._load(pk)
        return Response(self._one(request))

    def create(self, request):
        """FR-2.1 — body only. Title, links and category are all optional."""
        serializer = NoteWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = data.get("source") or Note.Source.MANUAL
        body = data.get("body", "")
        title = (data.get("title") or "").strip()
        title_is_auto = not title
        if title_is_auto:
            title = access.derive_title(body) or (
                _recording_title(request.tenant) if source == Note.Source.RECORDING else ""
            )
        note = Note.objects.create(
            tenant=request.tenant, created_by=request.user, source=source,
            title=title, title_is_auto=title_is_auto, body=body,
            contact=data.get("contact"), company=data.get("company"), task=data.get("task"),
            transcription_state=(Note.TranscriptionState.UPLOADING
                                 if source == Note.Source.RECORDING
                                 else Note.TranscriptionState.NONE),
        )
        self._load(note.pk)
        return Response(self._one(request), status=201)

    def partial_update(self, request, pk=None):
        """FR-2.4 — links can be added or changed after creation."""
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        note = self.note
        serializer = NoteWriteSerializer(instance=note, data=request.data, partial=True,
                                         context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fields = []
        for link in ("contact", "company", "task"):
            if link in data:
                setattr(note, link, data[link])
                fields.append(link)
        if "body" in data:
            note.body = data["body"]
            fields.append("body")
        if "title" in data:
            typed = data["title"].strip()
            note.title, note.title_is_auto = (typed, False) if typed else ("", True)
            fields += ["title", "title_is_auto"]
        if note.title_is_auto and ("body" in data or "title" in data):
            note.title = access.derive_title(note.body) or note.title or (
                _recording_title(note.tenant) if note.source == Note.Source.RECORDING else ""
            )
            fields.append("title")
        if fields:
            note.save(update_fields=sorted(set(fields)) + ["updated_at"])
        self._load(pk)
        return Response(self._one(request))

    def destroy(self, request, pk=None):
        """FR-2.5 — soft delete, audited."""
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        self.note.deleted_at = timezone.now()
        self.note.save(update_fields=["deleted_at", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=self.note.tenant, actor=request.user, verb="note.deleted",
            target_type="note", target_id=self.note.pk, payload={},
        )
        return Response(status=204)

    # ----------------------------------------------------------------- PINs

    @action(detail=True, methods=["post", "delete"])
    def pin(self, request, pk=None):
        self._load(pk)
        unlocked = access.can_read(request, self.note)
        try:
            if request.method == "DELETE":
                pins.remove_pin(self.note, request=request, unlocked=unlocked)
            else:
                pins.set_pin(self.note, str(request.data.get("pin") or ""),
                             request=request, unlocked=unlocked)
        except pins.PinError as exc:
            return Response({"detail": str(exc), **exc.extra}, status=exc.status)
        self._load(pk)
        return Response(self._one(request))

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        self._load(pk)
        try:
            pins.unlock(self.note, str(request.data.get("pin") or ""), request=request)
        except pins.PinError as exc:
            return Response({"detail": str(exc), **exc.extra}, status=exc.status)
        self._load(pk)
        return Response(self._one(request))

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        self._load(pk)
        pins.lock_now(self.note, request=request)
        self._load(pk)
        return Response(self._one(request))

    @action(detail=True, methods=["post"], url_path="pin-reset",
            permission_classes=[crm_perms.IsTenantStaff, crm_perms.IsFF])
    def pin_reset(self, request, pk=None):
        """Matrix 6.6 — FF only. Emails a link; changes nothing by itself."""
        self._load(pk)
        try:
            pins.request_reset(self.note, request=request)
        except pins.PinError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({"detail": f"A reset link was sent to {request.user.email}. "
                                   f"It clears the PIN; it does not reveal it."})

    @action(detail=False, methods=["get", "post"], url_path=r"pin-reset/confirm",
            permission_classes=[crm_perms.IsTenantStaff, crm_perms.IsFF])
    def pin_reset_confirm(self, request):
        """GET describes what the token would do; only POST clears (as with
        magic links, a mail scanner following the link changes nothing)."""
        token = request.data.get("token") if request.method == "POST" else request.query_params.get("token")
        try:
            if request.method == "GET":
                note = pins.reset_target(token or "", user=request.user)
                return Response({"note": str(note.pk), "title": access.display_title(note)})
            note = pins.confirm_reset(token or "", request=request)
        except pins.PinError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._load(note.pk)
        return Response(self._one(request))

    # ------------------------------------------------------------ recording

    @action(detail=False, methods=["get", "post"], url_path="consent-reminder")
    def consent_reminder(self, request):
        """FR-2.15 — dismissible per sign-in session, not per recording."""
        if request.method == "POST":
            request.session[CONSENT_SESSION_KEY] = True
        return Response({"dismissed": bool(request.session.get(CONSENT_SESSION_KEY))})

    @action(detail=True, methods=["post"])
    def recording(self, request, pk=None):
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        upload = request.FILES.get("audio")
        if upload is None:
            return Response({"detail": "No audio supplied."}, status=400)
        try:
            recording.store_recording(
                self.note, content=upload.read(), content_type=upload.content_type,
                duration_seconds=request.data.get("duration_seconds"), actor=request.user,
            )
        except recording.RecordingError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        except storage.StorageUnavailable:
            # AC-2.8(b): nothing was recorded server-side; the browser keeps the
            # audio and retries. Never a 500 that reads like a lost recording.
            return Response({"detail": "Storage is unreachable right now. The recording "
                                       "is still in this browser and will upload when "
                                       "it can."}, status=503)
        self._load(pk)
        return Response(self._one(request), status=201)

    @action(detail=True, methods=["post"], url_path="retry-transcription")
    def retry_transcription(self, request, pk=None):
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        try:
            recording.retry_transcription(self.note, actor=request.user)
        except recording.RecordingError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._load(pk)
        return Response(self._one(request))

    @action(detail=True, methods=["post"], url_path="discard-audio")
    def discard_audio(self, request, pk=None):
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        recording.discard_audio(self.note, actor=request.user)
        self._load(pk)
        return Response(self._one(request))

    # -------------------------------------------------------- summary (R3)

    def _summary_action(self, request, pk, fn, **kwargs):
        self._load(pk)
        if (refused := self._require_readable(request)) is not None:
            return refused
        if not summary.can_review(self.note, request.membership):
            return Response({"detail": "The note's author reviews its summary."}, status=403)
        try:
            fn(self.note, actor=request.user, **kwargs)
        except summary.SummaryError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._load(pk)
        return Response(self._one(request))

    @action(detail=True, methods=["post"], url_path="summary/accept")
    def accept_summary(self, request, pk=None):
        text = request.data.get("text")
        return self._summary_action(request, pk, summary.accept,
                                    text=text if isinstance(text, str) else None)

    @action(detail=True, methods=["post"], url_path="summary/discard")
    def discard_summary(self, request, pk=None):
        return self._summary_action(request, pk, summary.discard)

    @action(detail=True, methods=["post"], url_path="summary/redraft")
    def redraft_summary(self, request, pk=None):
        return self._summary_action(request, pk, summary.request_redraft)

    # -------------------------------------------------------------- settings

    # Not named `settings`: APIView.settings is DRF's own configuration, and
    # shadowing it breaks exception handling for every action on this view.
    @action(detail=False, methods=["get", "patch"], url_path="settings")
    def recording_settings(self, request):
        """FR-2.19 — audio retention. Matrix 3.1: FF and CF read settings, a
        VA does not. Matrix 3.11: only the FF changes it."""
        tenant = request.tenant
        if request.membership.role == Role.VA:
            return Response({"detail": "Settings are not available to a VA."}, status=403)
        if request.method == "PATCH":
            if request.membership.role != Role.FF:
                return Response({"detail": "Only the founder fractional changes "
                                           "recording settings."}, status=403)
            try:
                days = int(request.data.get("audio_retention_days"))
            except (TypeError, ValueError):
                return Response({"detail": "Retention is a whole number of days."}, status=400)
            if days < 0 or days > 3650:
                return Response({"detail": "Retention is 0 to 3650 days."}, status=400)
            old = tenant.audio_retention_days
            tenant.audio_retention_days = days
            tenant.save(update_fields=["audio_retention_days"])
            AuditEvent.all_objects.create(
                tenant=tenant, actor=request.user, verb="notes.retention_changed",
                target_type="tenant", target_id=tenant.pk,
                payload={"from": old, "to": days},
            )
        return Response({
            "audio_retention_days": tenant.audio_retention_days,
            "max_recording_seconds": recording.MAX_SECONDS,
            "warn_at_seconds": recording.WARN_AT_SECONDS,
        })
