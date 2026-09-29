"""A cut-off parse is billed, kept as nothing, and retried a bounded number
of times (owner, 2026-09-29).

By 2026-09-29, $17.25 of the $36.95 spent reading meeting notes had gone on 72
answers that came back cut off at the 6000-token limit. One note had failed 54
times, because the poll retried every failed file every ten minutes at the same
limit. The fix follows the owner-classification fix of 2026-09-28: a higher
limit, low effort for extraction, a failure named rather than silent, a re-read
queued automatically, and a cap on automatic re-reads.

The promise under test: **a truncated response is never billed as a kept
proposal.** The call is recorded with what it cost, marked failed, and nothing
the queue shows, the backfill counts, or an estimate uses points at it.
"""

from __future__ import annotations

import pytest

from apps.meetings import backfill, ingest, parsing
from apps.meetings.models import DriveWatch, MeetingProposal, MeetingSourceFile
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, MeetingSourceFileFactory
from .test_module5_acceptance import NOTES, PARSED, FakeDrive, a_file, one_page

CUT_OFF = '{"title": "Acme operations review", "summary": "A review of Acme'


@pytest.fixture
def watch(seeded_tenant, in_tenant_a):
    return DriveWatch.objects.create(tenant=seeded_tenant, folder_id="folder-1")


def _poll(tenant):
    return ingest.poll(tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                 texts={"f1": NOTES}))


def _truncate(fake):
    fake.reply = CUT_OFF
    fake.stop_reason = "max_tokens"


@pytest.mark.django_db
def test_a_truncated_answer_is_billed_and_kept_as_nothing(seeded_tenant, watch, fake_claude):
    _truncate(fake_claude)
    report = _poll(seeded_tenant)

    source = MeetingSourceFile.objects.get()
    assert source.state == MeetingSourceFile.State.FAILED
    assert len(report["failed"]) == 1
    assert MeetingProposal.objects.count() == 0, "a cut-off answer proposes nothing"

    call = AiCall.objects.get(purpose=parsing.PARSE_PURPOSE)
    assert call.succeeded is False
    assert call.cost_usd > 0, "what it cost is recorded, not hidden"
    assert "cut off" in call.error
    # Named, with what happens next.
    assert "cut off" in source.error
    assert "read again on the next poll (1 of 3" in source.error
    assert source.auto_parse_failures == 1

    # Nothing that reports spend on kept work counts it.
    assert not MeetingProposal.objects.filter(ai_call=call).exists()
    estimate, measured = backfill.per_note_estimate(seeded_tenant)
    assert measured is False, "the per-note estimate never learns from a failed call"


@pytest.mark.django_db
def test_the_read_asks_for_room_and_low_effort(seeded_tenant, watch, fake_claude):
    fake_claude.reply = PARSED
    _poll(seeded_tenant)
    request = fake_claude.requests[-1]
    assert request["max_tokens"] == parsing.PARSE_MAX_TOKENS == 16000
    assert request["output_config"] == {"effort": "low"}


@pytest.mark.django_db
def test_the_reread_is_queued_by_the_failure_and_its_success_is_the_one_kept(
    seeded_tenant, watch, fake_claude
):
    _truncate(fake_claude)
    _poll(seeded_tenant)

    fake_claude.reply, fake_claude.stop_reason = PARSED, "end_turn"
    _poll(seeded_tenant)          # the next poll, with nobody asking

    source = MeetingSourceFile.objects.get()
    assert source.state == MeetingSourceFile.State.PARSED
    assert source.auto_parse_failures == 0
    proposal = MeetingProposal.objects.get()
    assert proposal.ai_call.succeeded is True
    failed = AiCall.objects.get(purpose=parsing.PARSE_PURPOSE, succeeded=False)
    assert proposal.ai_call_id != failed.pk


@pytest.mark.django_db
def test_after_three_billed_failures_the_poll_stops_and_names_the_file(
    seeded_tenant, watch, fake_claude
):
    _truncate(fake_claude)
    for _ in range(3):
        _poll(seeded_tenant)
    source = MeetingSourceFile.objects.get()
    assert source.auto_parse_failures == 3
    assert "not tried again until someone chooses Read again" in source.error

    calls = len(fake_claude.requests)
    for _ in range(5):            # fifty minutes of polling
        _poll(seeded_tenant)
    assert len(fake_claude.requests) == calls, "no more money spent on it"
    assert AiCall.objects.filter(purpose=parsing.PARSE_PURPOSE).count() == 3

    health = ingest.health(seeded_tenant)
    assert health["files_failed"] == 1
    assert health["files_needing_person"] == 1


@pytest.mark.django_db
def test_a_failure_that_cost_nothing_never_uses_up_the_tries(
    seeded_tenant, watch, fake_claude
):
    """A bad key, or no network: fix it and every file retries by itself."""
    import anthropic
    import httpx2

    fake_claude.raise_exc = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    for _ in range(5):
        _poll(seeded_tenant)
    source = MeetingSourceFile.objects.get()
    assert source.state == MeetingSourceFile.State.FAILED
    assert source.auto_parse_failures == 0
    assert "Queued" not in source.error and "not tried again" not in source.error

    fake_claude.raise_exc = None
    fake_claude.reply = PARSED
    _poll(seeded_tenant)
    assert MeetingProposal.objects.count() == 1


@pytest.mark.django_db
def test_an_unreadable_answer_counts_like_a_cut_off_one(seeded_tenant, watch, fake_claude):
    fake_claude.reply = "I could not find any meeting here."
    _poll(seeded_tenant)
    source = MeetingSourceFile.objects.get()
    assert source.auto_parse_failures == 1
    assert "could not read" in source.error


@pytest.mark.django_db
def test_a_person_rereading_is_not_capped(seeded_tenant, watch, fake_claude, ff, api):
    """Reparse from the queue (a person asking) neither counts nor is refused."""
    fake_claude.reply = PARSED
    _poll(seeded_tenant)
    proposal = MeetingProposal.objects.get()
    source = proposal.source_file
    source.auto_parse_failures = 3
    source.save(update_fields=["auto_parse_failures"])

    _truncate(fake_claude)
    response = api.as_(ff).post(f"/api/meeting-proposals/{proposal.pk}/reparse/")
    assert response.status_code == 502
    source.refresh_from_db()
    assert source.auto_parse_failures == 3, "a person's try is not an automatic one"


# ------------------------------------------------------------------ Read again

def _gave_up(tenant, **extra):
    return MeetingSourceFileFactory(
        tenant=tenant, state=MeetingSourceFile.State.FAILED, auto_parse_failures=3,
        error="Claude's answer was cut off or empty; nothing was kept.", **extra)


@pytest.mark.django_db
def test_the_queue_lists_failed_files_by_name(seeded_tenant, in_tenant_a, ff, api):
    row = _gave_up(seeded_tenant, name="Meeting started 2026/05/15 10:59 MDT")
    body = api.as_(ff).get("/api/drive-watch/failed/").json()
    assert [(r["id"], r["name"], r["automatic_failures"], r["retries_automatically"])
            for r in body] == [(str(row.pk), row.name, 3, False)]


@pytest.mark.django_db
def test_read_again_queues_it_for_the_next_poll_and_is_audited(
    seeded_tenant, watch, fake_claude, ff, api
):
    row = _gave_up(seeded_tenant, drive_file_id="f1", text=NOTES)
    response = api.as_(ff).post("/api/drive-watch/read-again/", {"file": str(row.pk)},
                                content_type="application/json")
    assert response.status_code == 200
    row.refresh_from_db()
    assert row.state == MeetingSourceFile.State.RECORDED
    assert row.auto_parse_failures == 0
    assert fake_claude.requests == [], "queued, not read in the request"
    assert AuditEvent.objects.filter(verb="meeting.file_read_again",
                                     target_id=row.pk).exists()

    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive())
    row.refresh_from_db()
    assert row.state == MeetingSourceFile.State.PARSED


@pytest.mark.django_db
def test_read_again_refuses_a_file_that_did_not_fail(seeded_tenant, in_tenant_a, ff, api):
    row = MeetingSourceFileFactory(tenant=seeded_tenant,
                                   state=MeetingSourceFile.State.PARSED)
    response = api.as_(ff).post("/api/drive-watch/read-again/", {"file": str(row.pk)},
                                content_type="application/json")
    assert response.status_code == 409


# ---------------------------------------------- the two mandatory families

@pytest.mark.django_db
def test_tenant_isolation_failed_files_and_read_again(tenant_a, tenant_b, api):
    from apps.tenancy.context import tenant_context

    from .factories import MembershipFactory as Member

    with tenant_context(tenant_b.pk):
        theirs = _gave_up(tenant_b)
    with tenant_context(tenant_a.pk):
        mine = Member(tenant=tenant_a, role="FF")
    client = api.as_(mine)
    assert client.get("/api/drive-watch/failed/").json() == []
    response = client.post("/api/drive-watch/read-again/", {"file": str(theirs.pk)},
                           content_type="application/json")
    assert response.status_code == 404
    with tenant_context(tenant_b.pk):
        theirs.refresh_from_db()
        assert theirs.state == MeetingSourceFile.State.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [
    ("FF", 200), ("VA", 200), ("FCC", 403), ("ECC", 403)])
def test_role_boundaries_read_again(role, expected, seeded_tenant, in_tenant_a, api):
    """Matrix 11.8 (re-parse a source file): FF and VA; no client role."""
    row = _gave_up(seeded_tenant)
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
    client = api.as_(member)
    assert client.get("/api/drive-watch/failed/").status_code == expected
    response = client.post("/api/drive-watch/read-again/", {"file": str(row.pk)},
                           content_type="application/json")
    assert response.status_code == expected


@pytest.mark.django_db
def test_role_boundaries_a_cf_reaches_only_their_own_files(seeded_tenant, in_tenant_a, api):
    """Matrix 11.8 for a CF is `proposal-scope`: a file they own, yes; the
    FF's unmatched one is a 404, exactly as its proposal would be."""
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    own = _gave_up(seeded_tenant, drive_file_owner_email=cf.user.email)
    founders = _gave_up(seeded_tenant, drive_file_owner_email="bryan@getexecutivesnow.test")
    client = api.as_(cf)
    assert [r["id"] for r in client.get("/api/drive-watch/failed/").json()] == [str(own.pk)]
    assert client.post("/api/drive-watch/read-again/", {"file": str(founders.pk)},
                       content_type="application/json").status_code == 404
    assert client.post("/api/drive-watch/read-again/", {"file": str(own.pk)},
                       content_type="application/json").status_code == 200

