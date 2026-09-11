"""Phase 2 prerequisite — `stored_file` content in GCS.

The backend swap itself is proven by the `gcs_live` tests at the bottom, which
talk to the real bucket and are opt-in (`RUN_GCS_LIVE=1`). Everything above
them runs on the local backend and pins the rules that do not depend on where
the bytes live:

- a write never replaces another row's bytes (the flyer-collision bug);
- recording audio lives under `recordings/` and nothing else does, because the
  backup excludes that prefix so audio retention actually deletes;
- "storage unreachable" is never reported as "file missing";
- `check_media` catches a wrong size, not only an absent file, and says so
  when it skips a purpose rather than skipping it silently.
"""

from __future__ import annotations

import os
import uuid
from io import StringIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from apps.crm.models import OutboxMessage
from apps.crm.services import outbox, transport
from apps.tenancy import storage
from apps.tenancy.context import tenant_context
from apps.tenancy.models import StoredFile

from . import registry_config  # noqa: F401
from .factories import OutboxAttachmentFactory, OutboxMessageFactory, StoredFileFactory

S = OutboxMessage.State
PDF_1 = b"%PDF-1.4 first flyer"
PDF_2 = b"%PDF-1.4 second flyer, different bytes"


# ------------------------------------------------------ no write overwrites

@pytest.mark.django_db
def test_object_keys_are_unique_and_keep_the_filename():
    a = storage.object_key("flyers/acme", "Flyer.pdf")
    b = storage.object_key("flyers/acme", "Flyer.pdf")
    assert a != b
    assert a.startswith("flyers/acme/") and a.endswith("/Flyer.pdf")


@pytest.mark.django_db
def test_a_write_to_an_existing_key_is_refused(seeded_tenant):
    storage.save(tenant=seeded_tenant, content=PDF_1, object_key="k/x.pdf", purpose="p")
    with pytest.raises(storage.ObjectExists):
        storage.save(tenant=seeded_tenant, content=PDF_2, object_key="k/x.pdf", purpose="p")
    # And the refused write left no row behind: bytes first, row second.
    assert StoredFile.all_objects.filter(object_key="k/x.pdf").count() == 1


@pytest.mark.django_db
def test_re_uploading_a_flyer_with_the_same_name_keeps_both_files(
    seeded_tenant, ff, api
):
    """The owner's database had two flyer rows on ONE object: the second upload
    rewrote the bytes behind the first. With retention deleting objects, that
    is one row's delete destroying another row's file."""
    client = api.as_(ff)
    for body in (PDF_1, PDF_2):
        upload = SimpleUploadedFile("Flyer.pdf", body, content_type="application/pdf")
        assert client.post("/api/referral-settings/flyer/", {"flyer": upload}).status_code == 200

    first, second = StoredFile.all_objects.filter(purpose="marketing_flyer").order_by("created_at")
    assert first.object_key != second.object_key
    assert storage.read(first) == PDF_1
    assert storage.read(second) == PDF_2


# ------------------------------------------------- the recordings prefix rule

@pytest.mark.django_db
def test_recording_audio_must_live_under_the_recordings_prefix(seeded_tenant):
    with pytest.raises(ValueError, match="recordings/"):
        storage.save(tenant=seeded_tenant, content=b"audio", object_key="notes/a.webm",
                     purpose="recording_audio")


@pytest.mark.django_db
def test_nothing_but_recording_audio_may_use_the_recordings_prefix(seeded_tenant):
    """Anything else there would silently fall out of the backup."""
    with pytest.raises(ValueError, match="recordings/"):
        storage.save(tenant=seeded_tenant, content=PDF_1, object_key="recordings/flyer.pdf",
                     purpose="marketing_flyer")


@pytest.mark.django_db
def test_a_recording_under_the_prefix_is_stored(seeded_tenant):
    key = storage.object_key("recordings/acme", "call.webm")
    stored = storage.save(tenant=seeded_tenant, content=b"audio", object_key=key,
                          purpose="recording_audio")
    assert storage.read(stored) == b"audio"


# ------------------------------------------- unreachable is not the same as gone

@pytest.fixture
def gcs_without_a_key(settings):
    """The GCS backend with no usable key — offline laptop, revoked key, or a
    missing file all land here. Never reaches the network."""
    settings.STORAGE_BACKEND = "gcs"
    settings.GOOGLE_APPLICATION_CREDENTIALS = "/nonexistent/sa-app.json"


@pytest.mark.django_db
def test_no_key_raises_unavailable_and_never_falls_back_to_adc(seeded_tenant, gcs_without_a_key):
    row = StoredFile.all_objects.create(
        tenant=seeded_tenant, bucket="execs-now-hq-media", object_key="flyers/x.pdf",
        byte_size=10, purpose="marketing_flyer",
    )
    with pytest.raises(storage.StorageUnavailable, match="No service-account key"):
        storage.read(row)
    with pytest.raises(storage.StorageUnavailable):
        storage.save(tenant=seeded_tenant, content=PDF_1, object_key="flyers/y.pdf",
                     purpose="marketing_flyer")
    assert not StoredFile.all_objects.filter(object_key="flyers/y.pdf").exists(), (
        "A failed upload left a row describing a file that was never written."
    )


@pytest.mark.django_db
def test_unreachable_storage_shows_unknown_not_missing(seeded_tenant, gcs_without_a_key):
    row = StoredFile.all_objects.create(
        tenant=seeded_tenant, bucket="execs-now-hq-media", object_key="flyers/x.pdf",
        byte_size=10, purpose="marketing_flyer",
    )
    assert storage.present_or_unknown(row) is None


@pytest.mark.django_db
def test_a_send_with_unreachable_storage_fails_and_says_so(
    seeded_tenant, ff, dev_outbox, gcs_without_a_key
):
    row = StoredFile.all_objects.create(
        tenant=seeded_tenant, bucket="execs-now-hq-media", object_key="flyers/x.pdf",
        byte_size=10, purpose="marketing_flyer", content_type="application/pdf",
    )
    message = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    OutboxAttachmentFactory(tenant=seeded_tenant, outbox_message=message,
                            stored_file=row, filename="Flyer.pdf")

    with tenant_context(seeded_tenant.pk), pytest.raises(transport.TransportUnavailable) as exc:
        outbox.approve(message, actor=ff.user, role="FF")

    assert "No service-account key" in str(exc.value)
    assert "Re-upload" not in str(exc.value), "An outage was reported as a lost file."
    assert dev_outbox == []
    message.refresh_from_db()
    assert message.state != S.SENT


# ------------------------------------------------------------- check_media

def _check(*args):
    out = StringIO()
    try:
        call_command("check_media", *args, stdout=out)
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, out.getvalue()


@pytest.mark.django_db
def test_check_media_passes_when_every_row_has_its_bytes(seeded_tenant):
    StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer", object_key="f/a.pdf")
    code, out = _check("--strict")
    assert code == 0
    assert "Every stored_file row has its content." in out


@pytest.mark.django_db
def test_check_media_fails_strict_on_a_missing_file(seeded_tenant):
    StoredFile.all_objects.create(tenant=seeded_tenant, bucket="execs-now-hq-media",
                                  object_key="f/gone.pdf", byte_size=9, purpose="marketing_flyer")
    code, out = _check("--strict")
    assert code == 1
    assert "missing  marketing_flyer" in out and "f/gone.pdf" in out


@pytest.mark.django_db
def test_check_media_fails_strict_on_a_truncated_file(seeded_tenant):
    """Present is not the same as whole. The old check said this file was fine."""
    row = StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer",
                            object_key="f/short.pdf", content=b"%PDF-1.4 whole")
    row.byte_size = 404710
    row.save(update_fields=["byte_size"])
    code, out = _check("--strict")
    assert code == 1
    assert "recorded 404710, stored 14" in out


@pytest.mark.django_db
def test_check_media_reports_skipped_rows_rather_than_hiding_them(seeded_tenant):
    """The restore drill skips recordings (not in the backup by design). It must
    say how many it skipped, or 'every row has its content' would be a claim
    about a subset reported as the total."""
    StoredFile.all_objects.create(tenant=seeded_tenant, bucket="execs-now-hq-media",
                                  object_key="recordings/t/1/a.webm", byte_size=9,
                                  purpose="recording_audio")
    StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer", object_key="f/a.pdf")

    code, out = _check("--strict", "--exclude-purpose", "recording_audio")
    assert code == 0
    assert "skipped        : 1 (recording_audio)" in out


@pytest.mark.django_db
def test_check_media_does_not_fail_on_orphan_objects(seeded_tenant, settings):
    """An object with no row is the harmless direction — reported, not failed."""
    storage.LocalBackend(Path(settings.MEDIA_ROOT)).write(
        "execs-now-hq-media", "stray/x.pdf", b"x", "application/pdf")
    StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer", object_key="f/a.pdf")
    code, out = _check("--strict")
    assert code == 0
    assert "objects, no row  : 1" in out


@pytest.mark.django_db
def test_check_media_that_cannot_reach_storage_does_not_pass(seeded_tenant, gcs_without_a_key):
    StoredFile.all_objects.create(tenant=seeded_tenant, bucket="execs-now-hq-media",
                                  object_key="f/a.pdf", byte_size=9, purpose="marketing_flyer")
    code, out = _check()
    assert code == 2
    assert "Could not check" in out


# ------------------------------------------------- the real bucket (opt-in)

live = pytest.mark.skipif(
    os.environ.get("RUN_GCS_LIVE") != "1",
    reason="Talks to gs://execs-now-hq-media. Set RUN_GCS_LIVE=1 to run.",
)


@pytest.fixture
def real_gcs(settings):
    settings.STORAGE_BACKEND = "gcs"
    prefix = f"_selftest/{uuid.uuid4()}"
    yield prefix
    client = storage._client()
    for blob in client.list_blobs(settings.GCS_BUCKET_MEDIA, prefix=prefix):
        blob.delete()


@pytest.mark.gcs_live
@live
def test_live_round_trip_is_byte_exact_and_refuses_overwrite(real_gcs, settings):
    backend = storage.GcsBackend()
    bucket = settings.GCS_BUCKET_MEDIA
    key = f"{real_gcs}/Flyer.pdf"
    body = os.urandom(300_000)

    assert backend.write(bucket, key, body, "application/pdf") == len(body)
    assert backend.read(bucket, key) == body
    assert backend.size(bucket, key) == len(body)
    assert backend.list_sizes(bucket)[key] == len(body)

    with pytest.raises(storage.ObjectExists):
        backend.write(bucket, key, b"different", "application/pdf")
    assert backend.read(bucket, key) == body, "A refused overwrite changed the bytes."

    assert backend.read(bucket, f"{real_gcs}/absent.pdf") is None
    assert backend.size(bucket, f"{real_gcs}/absent.pdf") is None


@pytest.mark.gcs_live
@live
def test_live_key_cannot_touch_the_backup_bucket(real_gcs):
    """The app's key has objectAdmin on the MEDIA bucket only. If it could list
    the backups, a leaked key could delete them."""
    with pytest.raises(storage.StorageUnavailable, match="403|Forbidden|permission"):
        storage.GcsBackend().list_sizes("execs-now-hq-db-backups")
