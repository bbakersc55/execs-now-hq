"""Live Speech-to-Text, opt-in (`RUN_STT_LIVE=1`). Costs a few cents per run.

Everything else in the suite fakes Google at the client boundary. This runs
the app's own code path against the real services — the bucket, the
long-running operation, the polling, and the parsing — so a wrong encoding,
sample rate, model or permission fails here rather than on a client call.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from . import registry_config  # noqa: F401
from .factories import NoteFactory

pytestmark = [
    pytest.mark.gcs_live,
    pytest.mark.skipif(os.environ.get("RUN_STT_LIVE") != "1",
                       reason="Calls Google Speech-to-Text. Set RUN_STT_LIVE=1 to run."),
]

PROBE = Path(__file__).parent / "fixtures" / "speech_probe.webm"


@pytest.mark.django_db
def test_live_recording_is_transcribed_from_the_bucket(seeded_tenant, settings):
    from apps.notes import recording
    from apps.notes.models import Note
    from apps.tenancy import storage

    settings.STORAGE_BACKEND = "gcs"
    note = NoteFactory(tenant=seeded_tenant, body="", source=Note.Source.RECORDING)
    stored = storage.save(
        tenant=seeded_tenant, content=PROBE.read_bytes(), content_type="audio/webm",
        object_key=storage.object_key("recordings/_selftest", "probe.webm"),
        purpose=storage.RECORDING_PURPOSE,
    )
    try:
        note.audio_file = stored
        note.audio_duration_seconds = 12
        note.save()
        recording.start_transcription(note)
        assert note.transcription_state == "transcribing", note.transcription_error

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not recording.poll(note):
            time.sleep(5)
        note.refresh_from_db()
        assert note.transcription_state == "done", note.transcription_error
        words = note.transcript.lower()
        for expected in ("warehouse", "denver", "march", "lease", "friday"):
            assert expected in words, f"{expected!r} missing from {note.transcript!r}"
        print(f"\nLIVE TRANSCRIPT: {note.transcript}")
    finally:
        storage.delete(stored)
