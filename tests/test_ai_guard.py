"""The daily cap on unattended AI spend, and "twice on the same input"
(owner, 2026-09-29).

The fake answers every call with 12,000 tokens in and 800 out on
claude-opus-5: $0.06 + $0.02 = $0.08 a call.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.meetings import backfill, ingest
from apps.meetings.models import DriveBackfill, DriveWatch, MeetingProposal, MeetingSourceFile
from apps.notes.models import Note
from apps.tenancy import ai_guard, claude
from apps.tenancy.models import AiCall, AuditEvent, Tenant

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, NoteFactory
from .test_module5_acceptance import NOTES, PARSED, FakeDrive, a_file, one_page

CALL = Decimal("0.08")


def ask(tenant, text="What was agreed?", target=None, purpose="note_summary"):
    return claude.complete_with_call(tenant=tenant, purpose=purpose, system="s",
                                     user_text=text, target_type="note" if target else "",
                                     target_id=target)


def cap(tenant, amount):
    Tenant.objects.filter(pk=tenant.pk).update(ai_unattended_daily_cap_usd=Decimal(amount))
    tenant.refresh_from_db()


# ================================================================== who counts

@pytest.mark.django_db
def test_only_the_workers_calls_are_unattended(seeded_tenant, in_tenant_a, fake_claude):
    _, attended = ask(seeded_tenant)
    with claude.unattended("notes.process_notes"):
        _, worker = ask(seeded_tenant)
    assert (attended.unattended, attended.input_hash) == (False, "")
    assert worker.unattended is True and len(worker.input_hash) == 64
    assert ai_guard.spent_today(seeded_tenant) == CALL, "only the worker's call counts"


# ================================================================== the cap

@pytest.mark.django_db
def test_at_the_cap_the_worker_stops_and_a_person_does_not(seeded_tenant, in_tenant_a,
                                                          fake_claude):
    cap(seeded_tenant, "0.10")
    with claude.unattended("work.tick"):
        ask(seeded_tenant, "one")
        ask(seeded_tenant, "two")          # $0.08 spent, under $0.10: made
        requests = len(fake_claude.requests)
        for _ in range(5):                 # the worker comes back every minute
            with pytest.raises(claude.ClaudeSkipped) as exc:
                ask(seeded_tenant, "three", target="00000000-0000-0000-0000-000000000001")
        assert exc.value.reason == ai_guard.DAILY_CAP
    assert len(fake_claude.requests) == requests, "nothing sent, nothing billed"
    assert AiCall.objects.count() == 2
    skips = AuditEvent.objects.filter(verb=ai_guard.SKIPPED_VERB)
    assert skips.count() == 1, "recorded once, not once a minute"
    assert skips.get().payload == {"reason": "daily_cap", "purpose": "note_summary",
                                   "job": "work.tick", "day": timezone.localdate(
                                       timezone=__import__("zoneinfo").ZoneInfo(
                                           seeded_tenant.timezone)).isoformat()}

    ask(seeded_tenant, "the FF presses a button")     # a person: never stopped
    assert len(fake_claude.requests) == requests + 1


@pytest.mark.django_db
def test_it_resumes_the_next_day(seeded_tenant, in_tenant_a, fake_claude):
    cap(seeded_tenant, "0.05")
    with claude.unattended("work.tick"):
        ask(seeded_tenant, "one")
        with pytest.raises(claude.ClaudeSkipped):
            ask(seeded_tenant, "two")
    AiCall.objects.update(created_at=timezone.now() - timedelta(days=1))
    with claude.unattended("work.tick"):
        ask(seeded_tenant, "two")          # a new day: made


@pytest.mark.django_db
def test_a_zero_cap_stops_all_unattended_calls(seeded_tenant, in_tenant_a, fake_claude):
    cap(seeded_tenant, "0")
    with claude.unattended("work.tick"), pytest.raises(claude.ClaudeSkipped):
        ask(seeded_tenant)
    assert fake_claude.requests == []


# =================================================== twice on the same input

def _truncate(fake):
    fake.stop_reason = "max_tokens"


TARGET = "00000000-0000-0000-0000-00000000000a"


@pytest.mark.django_db
def test_two_billed_failures_on_the_same_input_stop_it(seeded_tenant, in_tenant_a, fake_claude):
    _truncate(fake_claude)
    with claude.unattended("notes.process_notes"):
        for _ in range(2):
            with pytest.raises(claude.ClaudeUnavailable):
                ask(seeded_tenant, "the transcript", target=TARGET)
        requests = len(fake_claude.requests)
        with pytest.raises(claude.ClaudeSkipped) as exc:
            ask(seeded_tenant, "the transcript", target=TARGET)
        assert exc.value.reason == ai_guard.FAILED_TWICE
        assert len(fake_claude.requests) == requests

        # A different input for the same target is a different job: this
        # week's digest is not last week's.
        fake_claude.stop_reason = "end_turn"
        ask(seeded_tenant, "a different transcript", target=TARGET)


@pytest.mark.django_db
def test_a_person_running_it_again_lets_the_worker_retry(seeded_tenant, in_tenant_a,
                                                         fake_claude):
    _truncate(fake_claude)
    with claude.unattended("notes.process_notes"):
        for _ in range(2):
            with pytest.raises(claude.ClaudeUnavailable):
                ask(seeded_tenant, "the transcript", target=TARGET)
    ai_guard.allow_again(seeded_tenant, purpose="note_summary", target_type="note",
                         target_id=TARGET)
    fake_claude.stop_reason = "end_turn"
    with claude.unattended("notes.process_notes"):
        ask(seeded_tenant, "the transcript", target=TARGET)


@pytest.mark.django_db
def test_failures_that_cost_nothing_never_stop_it(seeded_tenant, in_tenant_a, fake_claude):
    import anthropic
    import httpx2

    fake_claude.raise_exc = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    with claude.unattended("notes.process_notes"):
        for _ in range(4):
            with pytest.raises(claude.ClaudeUnavailable) as exc:
                ask(seeded_tenant, "the transcript", target=TARGET)
            assert not isinstance(exc.value, claude.ClaudeSkipped)


# ============================================================ the jobs

@pytest.mark.django_db
def test_a_capped_note_summary_waits_for_tomorrow_rather_than_failing(
    seeded_tenant, in_tenant_a, fake_claude
):
    from apps.notes import tasks

    note = NoteFactory(tenant=seeded_tenant, transcript="We agreed the dispatch fix.",
                       summary_state=Note.SummaryState.DRAFTING)
    cap(seeded_tenant, "0")
    tasks.process_notes(str(seeded_tenant.pk))
    note.refresh_from_db()
    assert note.summary_state == Note.SummaryState.DRAFTING
    assert fake_claude.requests == []

    cap(seeded_tenant, "5")
    tasks.process_notes(str(seeded_tenant.pk))
    note.refresh_from_db()
    assert note.summary_state == Note.SummaryState.PROPOSED


@pytest.mark.django_db
def test_a_redraft_a_person_asks_for_clears_two_failures(seeded_tenant, in_tenant_a,
                                                         fake_claude, ff):
    from apps.notes import summary, tasks

    note = NoteFactory(tenant=seeded_tenant, transcript="A long call.",
                       summary_state=Note.SummaryState.DRAFTING)
    _truncate(fake_claude)
    for _ in range(2):
        Note.objects.filter(pk=note.pk).update(summary_state=Note.SummaryState.DRAFTING)
        tasks.process_notes(str(seeded_tenant.pk))
    note.refresh_from_db()
    assert note.summary_state == Note.SummaryState.FAILED

    fake_claude.stop_reason = "end_turn"
    summary.request_redraft(note, actor=ff.user)
    tasks.process_notes(str(seeded_tenant.pk))
    note.refresh_from_db()
    assert note.summary_state == Note.SummaryState.PROPOSED


@pytest.fixture
def watch(seeded_tenant, in_tenant_a):
    return DriveWatch.objects.create(tenant=seeded_tenant, folder_id="folder-1")


@pytest.mark.django_db
def test_a_capped_poll_records_new_notes_and_reads_them_tomorrow(seeded_tenant, watch,
                                                                 fake_claude):
    fake_claude.reply = PARSED
    cap(seeded_tenant, "0")
    client = FakeDrive(pages=one_page([a_file("f1")]), texts={"f1": NOTES})
    with claude.unattended("meetings.poll_drive"):
        ingest.poll(seeded_tenant, client=client)
    source = MeetingSourceFile.objects.get()
    assert source.state == MeetingSourceFile.State.RECORDED, "recorded, not lost"
    assert fake_claude.requests == []

    cap(seeded_tenant, "5")
    with claude.unattended("meetings.poll_drive"):
        ingest.poll(seeded_tenant, client=FakeDrive(texts={"f1": NOTES}))
    assert MeetingProposal.objects.count() == 1


@pytest.mark.django_db
def test_sync_now_is_a_person_asking(seeded_tenant, watch, fake_claude, ff, api):
    fake_claude.reply = PARSED
    cap(seeded_tenant, "0")
    from unittest import mock

    with mock.patch.object(ingest, "client_for",
                           return_value=FakeDrive(pages=one_page([a_file("f1")]),
                                                  texts={"f1": NOTES})):
        assert api.as_(ff).post("/api/drive-watch/sync/").status_code == 200
    assert MeetingProposal.objects.count() == 1


@pytest.mark.django_db
def test_a_capped_import_pauses_where_it_is(seeded_tenant, watch, fake_claude):
    run = DriveBackfill.objects.create(tenant=seeded_tenant, watch=watch,
                                       state=DriveBackfill.State.RUNNING, planned=10)
    cap(seeded_tenant, "0")
    with claude.unattended("meetings.run_backfill"):
        result = backfill.step(seeded_tenant, client=FakeDrive())
    assert result == {"running": True, "paused": "daily_cap"}
    run.refresh_from_db()
    assert run.state == DriveBackfill.State.RUNNING and "Paused for today" in run.last_error
    assert fake_claude.requests == []


@pytest.mark.django_db
def test_capped_digest_prose_is_left_out_not_invented(seeded_tenant, in_tenant_a, fake_claude):
    from apps.work import digests

    from .factories import ContactFactory

    cap(seeded_tenant, "0")
    with claude.unattended("work.tick"):
        assert digests.narrative_for(seeded_tenant, [], contact=ContactFactory(
            tenant=seeded_tenant)) == ""


def test_every_scheduled_job_is_marked_unattended():
    """A new schedule whose function is not the worker's own would spend
    uncapped."""
    import importlib

    from apps.tenancy.management.commands.ensure_schedules import SCHEDULES

    for _name, func, *_ in SCHEDULES:
        module, attr = func.rsplit(".", 1)
        fn = getattr(importlib.import_module(module), attr)
        assert hasattr(fn, "__wrapped__"), f"{func} is not @unattended_job"


# ============================================ the endpoint and the banner

@pytest.mark.django_db
def test_the_ff_sets_the_cap_and_it_is_audited(seeded_tenant, in_tenant_a, ff, api):
    client = api.as_(ff)
    assert client.get("/api/ai-guard/").json()["cap_usd"] == "5.00", "the default"
    response = client.post("/api/ai-guard/", {"daily_cap_usd": "2.5"},
                           content_type="application/json")
    assert response.status_code == 200 and response.json()["cap_usd"] == "2.50"
    assert AuditEvent.objects.filter(verb="ai.daily_cap_changed",
                                     payload__after="2.50").exists()
    assert client.post("/api/ai-guard/", {"daily_cap_usd": "-1"},
                       content_type="application/json").status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_role_boundaries_only_the_ff_sees_or_sets_the_cap(role, seeded_tenant, in_tenant_a,
                                                          api):
    """FR-0.9: AI spend is the FF's."""
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    client = api.as_(MembershipFactory(tenant=seeded_tenant, role=role, client_company=company))
    assert client.get("/api/ai-guard/").status_code == 403
    assert client.post("/api/ai-guard/", {"daily_cap_usd": "100"},
                       content_type="application/json").status_code == 403
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.ai_unattended_daily_cap_usd == Decimal("5.00")


@pytest.mark.django_db
def test_the_pause_reaches_every_staff_role_and_the_amounts_only_the_ff(
    seeded_tenant, in_tenant_a, ff, va, api
):
    assert api.as_(ff).get("/api/dashboard/").json()["ai_paused"] is None
    cap(seeded_tenant, "0")
    as_ff = api.as_(ff).get("/api/dashboard/").json()["ai_paused"]
    as_va = api.as_(va).get("/api/dashboard/").json()["ai_paused"]
    assert as_ff["paused"] and as_ff["cap_usd"] == "0.00"
    assert as_va["paused"] and "cap_usd" not in as_va and "spent_today_usd" not in as_va


@pytest.mark.django_db
def test_tenant_isolation_another_practices_spend_is_not_ours(tenant_a, tenant_b, fake_claude):
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant_b.pk):
        AiCall.all_objects.create(tenant=tenant_b, purpose="meeting_parse", model="m",
                                  cost_usd=Decimal("50"), unattended=True)
    with tenant_context(tenant_a.pk):
        assert ai_guard.spent_today(tenant_a) == 0
        assert not ai_guard.cap_reached(tenant_a)
        with claude.unattended("work.tick"):
            ask(tenant_a)
