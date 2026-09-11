"""Recording → GCS → Speech-to-Text → transcript (FR-2.14–2.19).

Speech-to-Text is plumbing, not "the AI" (CLAUDE.md): it produces the
transcript, and Claude does all summarising. It runs as a long-running
operation read straight from the bucket, and its name is stored on the note so
a worker restart resumes polling instead of paying to transcribe twice.

**Retention (FR-2.19, owner decision 2026-09-11).** Audio is deleted only once
its transcription has succeeded and the recording is older than the tenant's
`audio_retention_days` (at 0, immediately on success). Audio that never
transcribed is kept — it is the only record of the call — and the note is
flagged until someone retries or discards it.
"""

from __future__ import annotations

import functools

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.tenancy import storage
from apps.tenancy.models import AuditEvent

MAX_SECONDS = 120 * 60        # FR-2.14 — soft cap
WARN_AT_SECONDS = 110 * 60
# The browser stops at 120:00; a few seconds of container overhead is not a
# reason to refuse a two-hour strategy session.
DURATION_TOLERANCE = 30
MAX_BYTES = 250 * 1024 * 1024
ENCODINGS = {"audio/webm": "WEBM_OPUS", "audio/ogg": "OGG_OPUS"}
OPUS_SAMPLE_RATE = 48000      # what every browser's MediaRecorder emits for Opus
STT_MODEL = "latest_long"


class RecordingError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _base_type(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _audit(note, actor, verb, **payload):
    AuditEvent.all_objects.create(
        tenant=note.tenant, actor=actor, verb=verb,
        target_type="note", target_id=note.pk, payload=payload,
    )


def store_recording(note, *, content: bytes, content_type: str, duration_seconds,
                    actor):
    """Save the audio, then start transcription.

    The audio is durable in GCS before anything else is attempted, so a
    Speech-to-Text failure leaves a note with its audio and a Retry control —
    AC-2.8(a) — rather than losing the call.
    """
    from apps.notes.models import Note

    kind = _base_type(content_type)
    if kind not in ENCODINGS:
        raise RecordingError(f"Recordings must be WebM or Ogg Opus audio, not {kind or 'unknown'}.")
    if not content:
        raise RecordingError("The recording is empty.")
    if len(content) > MAX_BYTES:
        raise RecordingError("That recording is larger than the 250 MB limit.")
    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError):
        raise RecordingError("The recording's duration is missing.")
    if duration < 1 or duration > MAX_SECONDS + DURATION_TOLERANCE:
        raise RecordingError("Recordings are capped at 120 minutes.")
    if note.audio_file_id:
        raise RecordingError("This note already has a recording.", status=409)

    extension = "ogg" if kind == "audio/ogg" else "webm"
    stored = storage.save(
        tenant=note.tenant, content=content, content_type=kind,
        object_key=storage.object_key(
            f"{storage.RECORDINGS_PREFIX}{note.tenant.slug}/{note.pk}", f"recording.{extension}"
        ),
        purpose=storage.RECORDING_PURPOSE,
    )
    note.audio_file = stored
    note.audio_duration_seconds = duration
    note.source = Note.Source.RECORDING if not note.body.strip() else note.source
    note.transcription_state = Note.TranscriptionState.TRANSCRIBING
    note.transcription_error = ""
    note.transcription_operation = ""
    note.save(update_fields=["audio_file", "audio_duration_seconds", "source",
                             "transcription_state", "transcription_error",
                             "transcription_operation", "updated_at"])
    _audit(note, actor, "note.recording_stored", byte_size=stored.byte_size,
           duration_seconds=duration)
    start_transcription(note)
    return note


# --------------------------------------------------------- Speech-to-Text

@functools.cache
def _speech_client_for(credentials_path: str):
    from google.cloud import speech_v1
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return speech_v1.SpeechClient(credentials=credentials)


def _speech_client():
    from pathlib import Path

    path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not path or not Path(path).is_file():
        raise RecordingError(
            f"No service-account key at GOOGLE_APPLICATION_CREDENTIALS={path!r}."
        )
    return _speech_client_for(path)


def _fail(note, message):
    from apps.notes.models import Note

    note.transcription_state = Note.TranscriptionState.FAILED
    note.transcription_error = message[:2000]
    note.transcription_operation = ""
    note.save(update_fields=["transcription_state", "transcription_error",
                             "transcription_operation", "updated_at"])


def start_transcription(note):
    """Start (or restart) the long-running recognition. Never raises: a failure
    becomes the note's failed state, with the audio untouched."""
    from google.api_core.exceptions import GoogleAPIError
    from google.auth.exceptions import GoogleAuthError
    from google.cloud import speech_v1

    from apps.notes.models import Note

    stored = note.audio_file
    if stored is None:
        _fail(note, "There is no audio to transcribe.")
        return note
    try:
        encoding = getattr(speech_v1.RecognitionConfig.AudioEncoding,
                           ENCODINGS[_base_type(stored.content_type)])
        operation = _speech_client().long_running_recognize(
            config=speech_v1.RecognitionConfig(
                encoding=encoding,
                sample_rate_hertz=OPUS_SAMPLE_RATE,
                language_code=settings.GOOGLE_STT_LANGUAGE,
                enable_automatic_punctuation=True,
                model=STT_MODEL,
            ),
            audio=speech_v1.RecognitionAudio(uri=f"gs://{stored.bucket}/{stored.object_key}"),
        )
    except (RecordingError, GoogleAPIError, GoogleAuthError, OSError, KeyError) as exc:
        _fail(note, f"Speech-to-Text could not start: {exc}")
        return note

    note.transcription_state = Note.TranscriptionState.TRANSCRIBING
    note.transcription_operation = operation.operation.name
    note.transcription_error = ""
    note.save(update_fields=["transcription_state", "transcription_operation",
                             "transcription_error", "updated_at"])
    return note


def _fetch_operation(name):
    return _speech_client().transport.operations_client.get_operation(name)


def transcript_from(operation) -> str:
    from google.cloud import speech_v1

    response = speech_v1.LongRunningRecognizeResponse.deserialize(operation.response.value)
    parts = [
        result.alternatives[0].transcript.strip()
        for result in response.results if result.alternatives
    ]
    return "\n\n".join(p for p in parts if p)


def poll(note, *, now=None) -> bool:
    """Check one in-flight transcription. True when it finished (either way)."""
    from google.api_core.exceptions import GoogleAPIError
    from google.auth.exceptions import GoogleAuthError

    from apps.notes.models import Note

    if note.transcription_state != Note.TranscriptionState.TRANSCRIBING:
        return False
    if not note.transcription_operation:
        start_transcription(note)
        return False
    try:
        operation = _fetch_operation(note.transcription_operation)
    except (RecordingError, GoogleAPIError, GoogleAuthError, OSError):
        # Transient: the operation lives on at Google. Ask again next minute.
        return False
    if not operation.done:
        return False
    if operation.HasField("error") and operation.error.code:
        _fail(note, f"Speech-to-Text failed: {operation.error.message}")
        return True

    text = transcript_from(operation)
    if not text:
        _fail(note, "Speech-to-Text returned no words. Check the recording has "
                    "audible speech, then retry.")
        return True
    note.transcript = text
    note.transcription_state = Note.TranscriptionState.DONE
    note.transcription_error = ""
    note.summary_state = Note.SummaryState.DRAFTING
    note.save(update_fields=["transcript", "transcription_state",
                             "transcription_error", "summary_state", "updated_at"])
    if note.tenant.audio_retention_days == 0:
        _delete_audio(note, actor=None, reason="retention_zero")
    return True


@transaction.atomic
def retry_transcription(note, *, actor):
    from apps.notes.models import Note

    if note.audio_file_id is None:
        raise RecordingError("The audio for this note has been deleted; it cannot "
                             "be transcribed again.", status=409)
    if note.transcription_state == Note.TranscriptionState.TRANSCRIBING:
        raise RecordingError("Transcription is already running.", status=409)
    _audit(note, actor, "note.transcription_retried")
    return start_transcription(note)


# ---------------------------------------------------------------- retention

def _delete_audio(note, *, actor, reason):
    stored = note.audio_file
    if stored is None:
        return
    key, size = stored.object_key, stored.byte_size
    storage.delete(stored)          # object first, then row; note.audio_file -> NULL
    note.audio_file = None
    _audit(note, actor, "note.audio_deleted", reason=reason, object_key=key, byte_size=size)


def discard_audio(note, *, actor):
    """The way out of the retention flag when the audio is not worth keeping."""
    from apps.notes.models import Note

    if note.audio_file_id is None:
        return note
    _delete_audio(note, actor=actor, reason="discarded")
    if note.transcription_state != Note.TranscriptionState.DONE:
        note.transcription_state = Note.TranscriptionState.FAILED
        note.transcription_error = "Audio discarded before a transcript was made."
        note.transcription_operation = ""
        note.save(update_fields=["transcription_state", "transcription_error",
                                 "transcription_operation", "updated_at"])
    return note


def retention_overdue(note, *, now=None) -> bool:
    """The flag: audio past retention that is being kept only because it never
    transcribed."""
    from apps.notes.models import Note

    if note.audio_file_id is None or note.transcription_state == Note.TranscriptionState.DONE:
        return False
    now = now or timezone.now()
    days = note.tenant.audio_retention_days
    return note.audio_file.created_at + timezone.timedelta(days=days) <= now


def purge_expired_audio(tenant, *, now=None) -> dict:
    from apps.notes.models import Note

    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=tenant.audio_retention_days)
    due = Note.all_objects.filter(
        tenant=tenant, audio_file__isnull=False, audio_file__created_at__lte=cutoff,
    ).select_related("audio_file", "tenant")
    deleted = kept = 0
    for note in due:
        if note.transcription_state == Note.TranscriptionState.DONE:
            _delete_audio(note, actor=None, reason="retention")
            deleted += 1
        else:
            kept += 1
    if deleted or kept:
        AuditEvent.all_objects.create(
            tenant=tenant, verb="notes.retention_run",
            payload={"deleted": deleted, "kept_untranscribed": kept,
                     "retention_days": tenant.audio_retention_days,
                     "ran_at": now.isoformat()},
        )
    return {"deleted": deleted, "kept_untranscribed": kept}
