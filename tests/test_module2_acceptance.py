"""Module 2 — Notes. AC-2.1 through AC-2.10 (01_prd.md §4).

Leak assertions are made against RAW response bytes (`response.content`),
never against parsed fields: a secret in a field nobody thought to check is
still a leak. The UI half of AC-2.3 lives in frontend/src/screens/Notes.test.tsx.

Google Speech-to-Text and Claude are faked at their client boundaries
(conftest). What is proven live against the real services is reported
separately, with the count, per the build plan.
"""

from __future__ import annotations

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.notes.models import Note, NotePinUnlock
from apps.tenancy import storage
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactFactory, MembershipFactory,
    TaskFactory,
)

SECRET = "CONFIDENTIAL SEVERANCE DISCUSSION"
BODY_WORD = "severance"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def create_note(client, **data):
    response = post(client, "/api/notes/", data)
    assert response.status_code == 201, response.content
    return response.json()


def set_pin(client, note_id, pin="4821"):
    response = post(client, f"/api/notes/{note_id}/pin/", {"pin": pin})
    assert response.status_code == 200, response.content
    return response.json()


def everything_a_user_can_fetch(client, note_id, contact_id=None):
    """Every read path a note can appear on, as raw bytes."""
    paths = [
        f"/api/notes/{note_id}/", "/api/notes/", f"/api/notes/?q={BODY_WORD}",
        "/api/notes/?q=HR", f"/api/contacts/search/?q={BODY_WORD}",
        "/api/contacts/search/?q=confidential",
    ]
    if contact_id:
        paths += [f"/api/contacts/{contact_id}/timeline/", f"/api/notes/?contact={contact_id}"]
    blobs = {}
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        blobs[path] = response.content.decode()
    return blobs


def assert_nowhere(secret, blobs):
    for path, blob in blobs.items():
        assert secret.lower() not in blob.lower(), f"{secret!r} leaked via {path}"


# ----------------------------------------------------------------- AC-2.1

@pytest.mark.django_db
def test_ac_2_1_capture_needs_only_a_sentence(seeded_tenant, ff, api):
    client = api.as_(ff)
    note = create_note(client, body="Warehouse lease renews in March; push for 18 months.")
    assert note["title"] == "Warehouse lease renews in March; push for 18 months."
    assert note["title_is_auto"] is True
    assert note["contact"] is None and note["company"] is None and note["task"] is None

    found = client.get("/api/notes/?q=warehouse").json()
    assert [n["id"] for n in found] == [note["id"]]
    assert note["id"] in [n["id"] for n in client.get("/api/contacts/search/?q=lease").json()["notes"]]


@pytest.mark.django_db
def test_ac_2_1_a_note_with_no_body_is_refused(seeded_tenant, ff, api):
    assert post(api.as_(ff), "/api/notes/", {"body": "   "}).status_code == 400


# ----------------------------------------------------------------- AC-2.2

@pytest.mark.django_db
def test_ac_2_2_linking_is_optional_mutable_and_dual(seeded_tenant, ff, api):
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant)
    task = TaskFactory(tenant=seeded_tenant, contact=contact)
    note = create_note(client, body="Unlinked thought")

    assert patch(client, f"/api/notes/{note['id']}/", {"contact": str(contact.pk)}).status_code == 200
    timeline = client.get(f"/api/contacts/{contact.pk}/timeline/").json()
    assert any(e.get("note_id") == note["id"] for e in timeline)

    assert patch(client, f"/api/notes/{note['id']}/", {"task": str(task.pk)}).status_code == 200
    on_contact = client.get(f"/api/notes/?contact={contact.pk}").json()
    on_task = client.get(f"/api/notes/?task={task.pk}").json()
    assert [n["id"] for n in on_contact] == [n["id"] for n in on_task] == [note["id"]], (
        "One note, visible from both records — not two notes."
    )
    assert Note.all_objects.filter(tenant=seeded_tenant).count() == 1


@pytest.mark.django_db
def test_ac_2_2_contact_and_company_together_is_refused(seeded_tenant, ff, api):
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant)
    company = ClientCompanyFactory(tenant=seeded_tenant)
    response = post(client, "/api/notes/", {"body": "x", "contact": str(contact.pk),
                                            "company": str(company.pk)})
    assert response.status_code == 400
    assert "contact already implies its company" in response.content.decode()


# ----------------------------------------------------------------- AC-2.3

@pytest.mark.django_db
def test_ac_2_3_a_locked_note_is_a_stub_on_the_timeline_and_in_search(
    seeded_tenant, ff, va, api
):
    contact = ContactFactory(tenant=seeded_tenant)
    note = create_note(api.as_(ff), title="HR matter", body=SECRET + "\nDetails follow.",
                       contact=str(contact.pk))
    set_pin(api.as_(ff), note["id"])

    viewer = api.as_(va)
    timeline = viewer.get(f"/api/contacts/{contact.pk}/timeline/").json()
    entry = next(e for e in timeline if e.get("note_id") == note["id"])
    assert entry["locked"] is True and "HR matter" in entry["text"]

    stub = viewer.get(f"/api/notes/{note['id']}/").json()
    assert stub["stub"] is True and stub["title"] == "HR matter"
    for field in ("body", "transcript", "summary", "proposed_summary"):
        assert field not in stub

    assert viewer.get(f"/api/notes/?q={BODY_WORD}").json() == []
    assert viewer.get(f"/api/contacts/search/?q={BODY_WORD}").json()["notes"] == []
    assert_nowhere(SECRET, everything_a_user_can_fetch(viewer, note["id"], contact.pk))


@pytest.mark.django_db
def test_ac_2_3_the_title_leak_through_the_workflow(seeded_tenant, ff, va, api):
    """No title typed, so the title is derived from the body's first line.
    The dialog (frontend test) demands a real title first; this is what the
    API sees when the user supplies 'HR matter' and then sets the PIN."""
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant)
    note = create_note(client, body=SECRET + "\nSeverance terms for the ops lead.",
                       contact=str(contact.pk))
    assert note["title"] == SECRET and note["title_is_auto"] is True

    assert patch(client, f"/api/notes/{note['id']}/", {"title": "HR matter"}).status_code == 200
    set_pin(client, note["id"])

    viewer = api.as_(va)
    assert viewer.get(f"/api/notes/{note['id']}/").json()["title"] == "HR matter"
    assert_nowhere(SECRET, everything_a_user_can_fetch(viewer, note["id"], contact.pk))


@pytest.mark.django_db
def test_ac_2_3_the_title_leak_through_the_api_bypass(seeded_tenant, ff, va, api):
    """FR-2.11b — PIN an auto-titled note straight through the API. The stub
    must say 'Locked note', and the derived title must be unfindable."""
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant)
    note = create_note(client, body=SECRET + "\nmore", contact=str(contact.pk))
    set_pin(client, note["id"])  # no title typed — the dialog was bypassed

    viewer = api.as_(va)
    stub = viewer.get(f"/api/notes/{note['id']}/").json()
    assert stub["title"] == "Locked note"
    timeline = viewer.get(f"/api/contacts/{contact.pk}/timeline/").json()
    assert any(e["text"] == "Note (locked): Locked note" for e in timeline)
    assert_nowhere(SECRET, everything_a_user_can_fetch(viewer, note["id"], contact.pk))
    assert viewer.get("/api/notes/?q=confidential").json() == []


@pytest.mark.django_db
def test_ac_2_3_a_title_auto_derived_after_locking_is_still_hidden(seeded_tenant, ff, va, api):
    """The other FR-2.11b path: clear the typed title of a locked note."""
    client = api.as_(ff)
    note = create_note(client, title="HR matter", body=SECRET)
    set_pin(client, note["id"])  # setter stays unlocked in their session
    assert patch(client, f"/api/notes/{note['id']}/", {"title": ""}).status_code == 200
    stub = api.as_(va).get(f"/api/notes/{note['id']}/").json()
    assert stub["title"] == "Locked note"


# ----------------------------------------------------------------- AC-2.4

@pytest.mark.django_db
def test_ac_2_4_five_wrong_pins_lock_the_note_and_are_recorded(seeded_tenant, ff, va, api):
    note = create_note(api.as_(ff), title="HR matter", body=SECRET)
    set_pin(api.as_(ff), note["id"], "4821")
    viewer = api.as_(va)

    for attempt in range(1, 5):
        response = post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "0000"})
        assert response.status_code == 400
        assert response.json()["attempts_left"] == 5 - attempt
    fifth = post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "0000"})
    assert fifth.status_code == 423
    assert "15 minutes" in fifth.json()["detail"]

    # Even the right PIN is refused during the lockout.
    assert post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "4821"}).status_code == 423

    failed = AuditEvent.all_objects.filter(verb="note.pin_failed", target_id=note["id"])
    assert failed.count() == 5 and set(failed.values_list("actor_id", flat=True)) == {va.user_id}
    lockout = AuditEvent.all_objects.get(verb="note.pin_lockout", target_id=note["id"])
    assert lockout.actor_id == va.user_id and lockout.payload["attempts"] == 5


@pytest.mark.django_db
def test_ac_2_4_the_lockout_ends_after_fifteen_minutes(seeded_tenant, ff, va, api):
    note = create_note(api.as_(ff), title="HR matter", body=SECRET)
    set_pin(api.as_(ff), note["id"], "4821")
    viewer = api.as_(va)
    for _ in range(5):
        post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "0000"})
    Note.all_objects.filter(pk=note["id"]).update(
        pin_locked_until=timezone.now() - timezone.timedelta(seconds=1)
    )
    unlocked = post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "4821"})
    assert unlocked.status_code == 200 and unlocked.json()["body"] == SECRET


@pytest.mark.django_db
def test_ac_2_4_an_unlock_lasts_thirty_minutes_and_one_session(seeded_tenant, ff, va, api):
    note = create_note(api.as_(ff), title="HR matter", body=SECRET)
    set_pin(api.as_(ff), note["id"], "4821")
    viewer = api.as_(va)
    assert post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "4821"}).status_code == 200
    assert viewer.get(f"/api/notes/{note['id']}/").json()["body"] == SECRET

    unlock = NotePinUnlock.all_objects.get(note_id=note["id"], user=va.user)
    assert unlock.expires_at - unlock.unlocked_at == timezone.timedelta(minutes=30)
    NotePinUnlock.all_objects.filter(pk=unlock.pk).update(
        expires_at=timezone.now() - timezone.timedelta(seconds=1)
    )
    assert viewer.get(f"/api/notes/{note['id']}/").json()["stub"] is True


@pytest.mark.django_db
def test_ac_2_4_changing_the_pin_revokes_other_unlocks(seeded_tenant, ff, va, api):
    note = create_note(api.as_(ff), title="HR matter", body=SECRET)
    set_pin(api.as_(ff), note["id"], "4821")
    viewer = api.as_(va)
    post(viewer, f"/api/notes/{note['id']}/unlock/", {"pin": "4821"})
    set_pin(api.as_(ff), note["id"], "7777")  # the FF is unlocked (they set it)
    assert viewer.get(f"/api/notes/{note['id']}/").json()["stub"] is True


@pytest.mark.django_db
def test_ac_2_4_a_stub_viewer_cannot_repin_or_unpin(seeded_tenant, ff, va, api):
    note = create_note(api.as_(ff), title="HR matter", body=SECRET)
    set_pin(api.as_(ff), note["id"], "4821")
    viewer = api.as_(va)
    assert post(viewer, f"/api/notes/{note['id']}/pin/", {"pin": "1111"}).status_code == 403
    assert viewer.delete(f"/api/notes/{note['id']}/pin/").status_code == 403
    assert patch(viewer, f"/api/notes/{note['id']}/", {"body": "overwritten"}).status_code == 403
    assert viewer.delete(f"/api/notes/{note['id']}/").status_code == 403


# ----------------------------------------------------------------- AC-2.5

@pytest.mark.django_db
def test_ac_2_5_reset_clears_does_not_reveal_and_is_ff_only(seeded_tenant, ff, cf, va, api,
                                                             dev_outbox):
    # On a company the CF is assigned to, so the CF is in scope and the only
    # thing refusing them is the reset rule itself.
    assigned = ClientCompanyFactory(tenant=seeded_tenant)
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=assigned)
    note = create_note(api.as_(ff), title="HR matter", body=SECRET, company=str(assigned.pk))
    set_pin(api.as_(ff), note["id"], "4821")

    for member in (cf, va):
        assert post(api.as_(member), f"/api/notes/{note['id']}/pin-reset/").status_code == 403
        stub = api.as_(member).get(f"/api/notes/{note['id']}/").json()
        assert stub["can_reset_pin"] is False
    assert dev_outbox == []

    # The FF, without the PIN, sees only the stub — and the reset control.
    fresh_ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    ff_client = api.as_(fresh_ff)
    assert ff_client.get(f"/api/notes/{note['id']}/").json()["can_reset_pin"] is True
    assert post(ff_client, f"/api/notes/{note['id']}/pin-reset/").status_code == 200

    assert len(dev_outbox) == 1
    email = dev_outbox[0]
    assert email.to == [fresh_ff.user.email]
    assert "4821" not in email.body and "CLEARS the PIN" in email.body
    assert SECRET.lower() not in email.body.lower()
    token = email.body.split("/notes/pin-reset/")[1].split()[0]

    # Following the link (GET) describes; it changes nothing.
    described = ff_client.get(f"/api/notes/pin-reset/confirm/?token={token}")
    assert described.status_code == 200 and described.json()["title"] == "HR matter"
    assert Note.all_objects.get(pk=note["id"]).is_locked

    # Another FF cannot use a link issued to someone else.
    assert post(api.as_(ff), "/api/notes/pin-reset/confirm/", {"token": token}).status_code == 403

    cleared = post(ff_client, "/api/notes/pin-reset/confirm/", {"token": token})
    assert cleared.status_code == 200 and cleared.json()["body"] == SECRET
    assert "4821" not in cleared.content.decode()
    assert api.as_(va).get(f"/api/notes/{note['id']}/").json()["body"] == SECRET
    assert AuditEvent.all_objects.filter(verb="note.pin_reset", target_id=note["id"],
                                         actor=fresh_ff.user).exists()

    # Spent: the same link does nothing a second time.
    assert post(ff_client, "/api/notes/pin-reset/confirm/", {"token": token}).status_code == 400

    # Stored as a hash, never the raw token (assumption C3).
    from apps.accounts.models import MagicLinkToken
    stored = MagicLinkToken.all_objects.get(purpose="pin_reset")
    assert token not in stored.token_hash and stored.used_at is not None


@pytest.mark.django_db
def test_ac_2_5_a_link_is_void_once_the_pin_has_changed(seeded_tenant, api, dev_outbox):
    ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    client = api.as_(ff)
    note = create_note(client, title="HR matter", body=SECRET)
    set_pin(client, note["id"], "4821")
    post(client, f"/api/notes/{note['id']}/pin-reset/")
    token = dev_outbox[0].body.split("/notes/pin-reset/")[1].split()[0]
    Note.all_objects.filter(pk=note["id"]).update(
        pin_set_at=timezone.now() + timezone.timedelta(seconds=5)
    )
    refused = post(client, "/api/notes/pin-reset/confirm/", {"token": token})
    assert refused.status_code == 400 and "changed since" in refused.json()["detail"]
    assert Note.all_objects.get(pk=note["id"]).is_locked


@pytest.mark.django_db
def test_ac_2_5_reset_on_an_auto_titled_note_does_not_email_the_title(seeded_tenant, ff, api,
                                                                     dev_outbox):
    note = create_note(api.as_(ff), body=SECRET)
    set_pin(api.as_(ff), note["id"])
    post(api.as_(ff), f"/api/notes/{note['id']}/pin-reset/")
    assert "Locked note" in dev_outbox[0].body
    assert SECRET.lower() not in dev_outbox[0].body.lower()


# ----------------------------------------------------- recording helpers

def upload(client, note_id, seconds=60, content=b"\x1aE\xdf\xa3 webm opus bytes",
           content_type="audio/webm;codecs=opus"):
    audio = SimpleUploadedFile("recording.webm", content, content_type=content_type)
    return client.post(f"/api/notes/{note_id}/recording/",
                       {"audio": audio, "duration_seconds": str(seconds)})


def recorded_note(client, **extra):
    note = create_note(client, source="recording", **extra)
    assert note["transcription_state"] == "uploading"
    return note


def run_jobs(tenant):
    from apps.notes.tasks import process_notes

    return process_notes(str(tenant.pk))


# ---------------------------------------------------------------- AC-2.5a

@pytest.mark.django_db
def test_ac_2_5a_a_full_two_hour_recording_is_accepted(seeded_tenant, ff, api, fake_stt):
    client = api.as_(ff)
    note = recorded_note(client)
    assert upload(client, note["id"], seconds=120 * 60).status_code == 201


@pytest.mark.django_db
def test_ac_2_5a_the_server_refuses_past_the_cap(seeded_tenant, ff, api, fake_stt):
    client = api.as_(ff)
    note = recorded_note(client)
    response = upload(client, note["id"], seconds=121 * 60)
    assert response.status_code == 400 and "120 minutes" in response.json()["detail"]


# ----------------------------------------------------------------- AC-2.6

@pytest.mark.django_db
def test_ac_2_6_consent_reminder_is_per_sign_in_session(seeded_tenant, ff, api):
    from django.test import Client

    client = api.as_(ff)
    assert client.get("/api/notes/consent-reminder/").json() == {"dismissed": False}
    assert post(client, "/api/notes/consent-reminder/").json() == {"dismissed": True}
    assert client.get("/api/notes/consent-reminder/").json() == {"dismissed": True}

    again = Client()
    again.force_login(ff.user)  # signing out and back in is a new session
    assert again.get("/api/notes/consent-reminder/").json() == {"dismissed": False}


# ----------------------------------------------------------------- AC-2.7

@pytest.mark.django_db
def test_ac_2_7_the_summary_is_proposed_not_applied(seeded_tenant, ff, api, fake_stt,
                                                    fake_claude):
    client = api.as_(ff)
    note = recorded_note(client)
    response = upload(client, note["id"])
    assert response.status_code == 201
    assert response.json()["transcription_state"] == "transcribing"

    started = fake_stt.started[0]
    stored = Note.all_objects.get(pk=note["id"]).audio_file
    assert started["audio"].uri == f"gs://{stored.bucket}/{stored.object_key}"
    assert stored.object_key.startswith("recordings/")
    assert started["config"].sample_rate_hertz == 48000

    fake_stt.finish(started["name"], "We agreed to move the warehouse in March.",
                    "Dana owns the lease review.")
    assert run_jobs(seeded_tenant) == {"transcriptions_finished": 1, "summaries_drafted": 1}

    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcript"] == ("We agreed to move the warehouse in March.\n\n"
                                   "Dana owns the lease review.")
    assert shown["summary_state"] == "proposed"
    assert shown["proposed_summary"] == fake_claude.reply
    assert shown["summary"] is None, "The summary was attached without review."
    assert "warehouse" in fake_claude.requests[0]["messages"][0]["content"]
    assert fake_claude.requests[0]["fallbacks"] == "default"

    discarded = post(client, f"/api/notes/{note['id']}/summary/discard/").json()
    assert discarded["summary"] is None and discarded["summary_state"] == "discarded"
    assert discarded["transcript"].startswith("We agreed")

    post(client, f"/api/notes/{note['id']}/summary/redraft/")
    run_jobs(seeded_tenant)
    accepted = post(client, f"/api/notes/{note['id']}/summary/accept/",
                    {"text": "Warehouse moves in March; Dana owns the lease."}).json()
    assert accepted["summary"] == "Warehouse moves in March; Dana owns the lease."
    assert accepted["summary_state"] == "accepted"
    assert AuditEvent.all_objects.get(verb="note.summary_accepted").payload["edited"] is True


@pytest.mark.django_db
def test_ac_2_7_every_claude_call_is_costed(seeded_tenant, ff, api, fake_stt, fake_claude):
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"], "A short call about the lease renewal and the March move.")
    run_jobs(seeded_tenant)
    call = AiCall.all_objects.get(purpose="note_summary")
    assert call.succeeded and call.model == "claude-opus-5"
    assert call.input_tokens == 12000 and call.output_tokens == 800
    assert str(call.cost_usd) == "0.080000"  # 12k x $5/M + 800 x $25/M


@pytest.mark.django_db
def test_ac_2_7_a_claude_failure_keeps_the_transcript(seeded_tenant, ff, api, fake_stt,
                                                      fake_claude):
    import anthropic
    import httpx2

    fake_claude.raise_exc = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"], "The transcript survives even when Claude cannot be reached.")
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcript"] == "The transcript survives even when Claude cannot be reached."
    assert shown["summary_state"] == "failed" and shown["summary"] is None
    assert AiCall.all_objects.get(purpose="note_summary").succeeded is False


@pytest.mark.django_db
def test_ac_2_7_only_the_author_or_ff_reviews(seeded_tenant, ff, va, api, fake_stt,
                                              fake_claude):
    author = api.as_(va)
    note = recorded_note(author)
    upload(author, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"], "Enough words here to count as a real conversation.")
    run_jobs(seeded_tenant)
    other_va = MembershipFactory(tenant=seeded_tenant, role="VA")
    assert post(api.as_(other_va), f"/api/notes/{note['id']}/summary/accept/").status_code == 403
    assert post(api.as_(ff), f"/api/notes/{note['id']}/summary/accept/").status_code == 200


# ----------------------------------------------------------------- AC-2.8

@pytest.mark.django_db
def test_ac_2_8a_speech_to_text_failure_keeps_the_audio_and_offers_retry(
    seeded_tenant, ff, api, fake_stt
):
    """AC-2.8(a), as re-worded 2026-09-11: storage works, Speech-to-Text fails."""
    from google.api_core.exceptions import PermissionDenied

    fake_stt.fail_start = PermissionDenied("Speech-to-Text API has not been used")
    client = api.as_(ff)
    note = recorded_note(client)
    shown = upload(client, note["id"]).json()
    assert shown["transcription_state"] == "failed"
    assert "Speech-to-Text could not start" in shown["transcription_error"]
    assert shown["has_audio"] is True
    stored = Note.all_objects.get(pk=note["id"]).audio_file
    assert storage.exists(stored), "The audio was lost when transcription failed."

    fake_stt.fail_start = None
    retried = post(client, f"/api/notes/{note['id']}/retry-transcription/").json()
    assert retried["transcription_state"] == "transcribing"


@pytest.mark.django_db
def test_ac_2_8a_a_failed_operation_is_reported_and_retryable(seeded_tenant, ff, api,
                                                               fake_stt):
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.fail(fake_stt.started[0]["name"], "Invalid audio encoding")
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcription_state"] == "failed" and shown["has_audio"] is True
    assert "Invalid audio encoding" in shown["transcription_error"]


@pytest.mark.django_db
def test_ac_2_8b_storage_unreachable_refuses_the_upload_and_keeps_the_note(
    seeded_tenant, ff, api, settings
):
    """AC-2.8(b), server side: with storage down the upload is refused, nothing
    half-written is recorded, and the note still says 'uploading' so the
    browser's retry has somewhere to land. The browser half is in
    frontend/src/lib/pendingUploads.test.ts."""
    client = api.as_(ff)
    note = recorded_note(client)
    settings.STORAGE_BACKEND = "gcs"
    settings.GOOGLE_APPLICATION_CREDENTIALS = "/nonexistent/key.json"
    response = upload(client, note["id"])
    assert response.status_code == 503
    shown = Note.all_objects.get(pk=note["id"])
    assert shown.audio_file_id is None
    assert shown.transcription_state == "uploading"


# ----------------------------------------------------------------- AC-2.9

@pytest.mark.django_db
def test_ac_2_9_retention_deletes_transcribed_audio_and_keeps_the_rest(
    seeded_tenant, ff, api, fake_stt, fake_claude
):
    from apps.notes.recording import purge_expired_audio

    seeded_tenant.audio_retention_days = 1
    seeded_tenant.save()
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"], "Keep this transcript after the audio is deleted.")
    run_jobs(seeded_tenant)
    post(client, f"/api/notes/{note['id']}/summary/accept/")
    stored = Note.all_objects.get(pk=note["id"]).audio_file
    key = stored.object_key

    assert purge_expired_audio(seeded_tenant) == {"deleted": 0, "kept_untranscribed": 0}
    result = purge_expired_audio(seeded_tenant,
                                 now=timezone.now() + timezone.timedelta(days=2))
    assert result == {"deleted": 1, "kept_untranscribed": 0}

    assert key not in storage.sizes(stored.bucket), "The audio object is still stored."
    kept = Note.all_objects.get(pk=note["id"])
    assert kept.audio_file_id is None
    assert kept.transcript == "Keep this transcript after the audio is deleted."
    assert kept.summary == fake_claude.reply


@pytest.mark.django_db
def test_ac_2_9_untranscribed_audio_is_kept_and_flagged(seeded_tenant, ff, api, fake_stt):
    """Owner decision 2026-09-11: never delete the only record of a call."""
    from apps.notes.recording import purge_expired_audio

    seeded_tenant.audio_retention_days = 1
    seeded_tenant.save()
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.fail(fake_stt.started[0]["name"], "no speech")
    run_jobs(seeded_tenant)

    later = timezone.now() + timezone.timedelta(days=2)
    assert purge_expired_audio(seeded_tenant, now=later) == {"deleted": 0, "kept_untranscribed": 1}
    stored = Note.all_objects.get(pk=note["id"]).audio_file
    assert storage.exists(stored)

    from apps.notes.recording import retention_overdue
    assert retention_overdue(Note.all_objects.get(pk=note["id"]), now=later)

    discarded = post(client, f"/api/notes/{note['id']}/discard-audio/").json()
    assert discarded["has_audio"] is False and discarded["retention_overdue"] is False


@pytest.mark.django_db
def test_ac_2_9_retention_zero_deletes_on_successful_transcription(seeded_tenant, ff, api,
                                                                    fake_stt, fake_claude):
    seeded_tenant.audio_retention_days = 0
    seeded_tenant.save()
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"], "Done with the call, send the follow-up tomorrow.")
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["has_audio"] is False and shown["transcript"].startswith("Done with the call")
    retry = post(client, f"/api/notes/{note['id']}/retry-transcription/")
    assert retry.status_code == 409 and "deleted" in retry.json()["detail"]


@pytest.mark.django_db
def test_ac_2_9_the_retention_job_is_scheduled(seeded_tenant):
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))  # idempotent
    purge = Schedule.objects.get(name=f"notes.purge_expired_audio:{seeded_tenant.slug}")
    assert purge.func == "apps.notes.tasks.purge_expired_audio"
    assert purge.schedule_type == Schedule.DAILY and purge.repeats == -1
    assert Schedule.objects.filter(name=f"notes.process:{seeded_tenant.slug}",
                                   minutes=1).exists()
    assert Schedule.objects.count() == 6   # 3 Module 1, work.tick, and Module 2's two


@pytest.mark.django_db
def test_module1_jobs_are_scheduled_and_rerunning_never_moves_them(seeded_tenant):
    """The Phase 1 gap: these jobs existed and never ran. Re-running the
    command must not push a daily job's next run, or it would re-fire."""
    from zoneinfo import ZoneInfo

    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    touches = Schedule.objects.get(name=f"crm.draft_referral_touches:{seeded_tenant.slug}")
    assert touches.func == "apps.crm.tasks.draft_referral_touches"
    assert touches.schedule_type == Schedule.DAILY
    assert touches.next_run.astimezone(ZoneInfo(seeded_tenant.timezone)).hour == 6
    for name in ("crm.expire_outbox", "crm.reindex_search"):
        assert Schedule.objects.get(name=f"{name}:{seeded_tenant.slug}").schedule_type == Schedule.HOURLY

    first = touches.next_run
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    touches.refresh_from_db()
    assert touches.next_run == first


# ---------------------------------------------------------------- AC-2.10

@pytest.mark.django_db
def test_ac_2_10_a_note_in_tenant_b_is_invisible_to_tenant_a(tenant_a, tenant_b, api):
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_a)
    seed_tenant(tenant_b)
    a_ff = MembershipFactory(tenant=tenant_a, role="FF")
    b_ff = MembershipFactory(tenant=tenant_b, role="FF")
    b_contact = ContactFactory(tenant=tenant_b)
    b_note = create_note(api.as_(b_ff), title="Bravo quarterly review",
                         body="Bravo margins are thin", contact=str(b_contact.pk))
    set_pin(api.as_(b_ff), b_note["id"])  # and unlocked, in tenant B's session

    a = api.as_(a_ff)
    assert a.get(f"/api/notes/{b_note['id']}/").status_code == 404
    assert a.get("/api/notes/?q=bravo").json() == []
    assert a.get("/api/notes/").json() == []
    assert a.get("/api/contacts/search/?q=bravo").json()["notes"] == []
    assert a.get(f"/api/contacts/{b_contact.pk}/timeline/").status_code == 404
    for path in ("unlock", "pin", "lock", "recording", "summary/accept"):
        assert post(a, f"/api/notes/{b_note['id']}/{path}/", {"pin": "4821"}).status_code == 404


# ------------------------------------------------ search, raw API response

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_search_returns_no_body_text_for_a_locked_note_in_the_raw_response(
    role, seeded_tenant, api
):
    author = MembershipFactory(tenant=seeded_tenant, role="FF")
    note = create_note(api.as_(author), title="HR matter", body=f"{SECRET} alpha bravo")
    set_pin(api.as_(author), note["id"])
    searcher = MembershipFactory(tenant=seeded_tenant, role=role)
    for term in ("HR", "matter", BODY_WORD, "alpha"):
        for path in (f"/api/notes/?q={term}", f"/api/contacts/search/?q={term}"):
            raw = api.as_(searcher).get(path).content.decode()
            assert SECRET.lower() not in raw.lower() and "alpha bravo" not in raw


# ------------------------------------------------- CF scope (matrix 6.2)

@pytest.mark.django_db
def test_cf_sees_notes_on_assigned_records_and_their_own_only(seeded_tenant, ff, cf, api):
    assigned = ClientCompanyFactory(tenant=seeded_tenant)
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=assigned)
    on_assigned = ContactFactory(tenant=seeded_tenant, company=assigned)
    elsewhere = ContactFactory(tenant=seeded_tenant)

    visible = create_note(api.as_(ff), body="On assigned", contact=str(on_assigned.pk))
    on_company = create_note(api.as_(ff), body="On the company", company=str(assigned.pk))
    hidden = create_note(api.as_(ff), body="Not theirs", contact=str(elsewhere.pk))
    unlinked_ff = create_note(api.as_(ff), body="FF's own thought")
    own = create_note(api.as_(cf), body="CF's own thought")

    seen = {n["id"] for n in api.as_(cf).get("/api/notes/").json()}
    assert seen == {visible["id"], on_company["id"], own["id"]}
    for other in (hidden, unlinked_ff):
        assert api.as_(cf).get(f"/api/notes/{other['id']}/").status_code == 404
    # ...and cannot attach a note to a record outside their scope.
    assert post(api.as_(cf), "/api/notes/", {"body": "x", "contact": str(elsewhere.pk)}
                ).status_code == 400


@pytest.mark.django_db
def test_a_malformed_id_is_a_404_or_400_never_a_500(seeded_tenant, ff, api):
    client = api.as_(ff)
    assert client.get("/api/notes/not-a-uuid/").status_code == 404
    assert post(client, "/api/notes/not-a-uuid/unlock/", {"pin": "1234"}).status_code == 404
    assert client.get("/api/notes/?contact=not-a-uuid").status_code == 400


@pytest.mark.django_db
def test_no_speech_is_its_own_outcome_and_keeps_the_audio(seeded_tenant, ff, api, fake_stt):
    """Manual check 1: a video call recorded through the browser came back
    empty. The recorder hears this device's microphone only."""
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.finish(fake_stt.started[0]["name"])  # finished, heard nothing
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcription_state"] == "failed"
    assert shown["no_speech"] is True and shown["transcription_error"] == "No speech detected."
    assert shown["has_audio"] is True
    assert storage.exists(Note.all_objects.get(pk=note["id"]).audio_file)
    assert post(client, f"/api/notes/{note['id']}/retry-transcription/").status_code == 200


@pytest.mark.django_db
def test_almost_no_speech_is_treated_the_same_and_costs_no_claude_call(
    seeded_tenant, ff, api, fake_stt, fake_claude
):
    """The actual check-1 case: a 383-second video call transcribed as 'Good.'"""
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"], seconds=383)
    fake_stt.finish(fake_stt.started[0]["name"], "Good.")
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcription_state"] == "failed" and shown["no_speech"] is True
    assert shown["transcription_error"] == "Almost no speech detected: 1 word in 6 minutes."
    assert shown["transcript"] == "Good." and shown["has_audio"] is True
    assert shown["summary_state"] == "none" and fake_claude.requests == []


@pytest.mark.django_db
def test_a_short_dictation_is_not_mistaken_for_silence(seeded_tenant, ff, api, fake_stt,
                                                       fake_claude):
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"], seconds=8)
    fake_stt.finish(fake_stt.started[0]["name"], "Remind me to call Dana Friday.")
    run_jobs(seeded_tenant)
    shown = client.get(f"/api/notes/{note['id']}/").json()
    assert shown["transcription_state"] == "done" and shown["no_speech"] is False


@pytest.mark.django_db
def test_other_failures_are_not_reported_as_no_speech(seeded_tenant, ff, api, fake_stt):
    client = api.as_(ff)
    note = recorded_note(client)
    upload(client, note["id"])
    fake_stt.fail(fake_stt.started[0]["name"], "Invalid audio encoding")
    run_jobs(seeded_tenant)
    assert client.get(f"/api/notes/{note['id']}/").json()["no_speech"] is False
