"""Module 3 — digests. AC-3.5 to AC-3.12, 3.19-3.22, 3.24-3.26, 3.32-3.36.

The rules these tests exist to hold down, in order of consequence:

1. Nothing sends while held (AC-3.6), and nothing sends unapproved, ever.
2. One update reaches every stakeholder independently, and a claim released by
   expiry is owed again (AC-3.33/3.34) — the whole reason `digest_item` exists.
3. One person gets one email per period per cadence (AC-3.35).
4. An approved digest is never rewritten (AC-3.21).
5. Silence produces silence (AC-3.9).
"""

from __future__ import annotations

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.tenancy.models import AuditEvent
from apps.work import digests as digest_service
from apps.work.models import Cadence, Digest, DigestItem, Stakeholder, TaskUpdate
from apps.work.services import add_comment, apply_task_changes, create_task

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    GoalFactory, MembershipFactory, ProjectFactory,
)

S = Task.Status
K = TaskUpdate.Kind
DENVER = ZoneInfo("America/Denver")


# --------------------------------------------------------------- fixtures

@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods",
                                digest_ai_prose=False, seat_count=3)


@pytest.fixture
def recipient(seeded_tenant, company):
    """A stakeholder with an address and no login — the common case."""
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                        address="dana@northwind.invalid", is_primary=True)
    return contact


@pytest.fixture
def goal(seeded_tenant, company):
    return GoalFactory(tenant=seeded_tenant, title="Cut order-to-cash", client_company=company)


@pytest.fixture
def project(seeded_tenant, company, goal):
    return ProjectFactory(tenant=seeded_tenant, title="Invoice automation",
                          client_company=company, goal=goal)


def a_task(tenant, company, *, ff, project=None, goal=None, title="Map the process",
           visible=True):
    return create_task(tenant=tenant, actor=ff.user, role="FF", title=title,
                       client_company=company, project=project, goal=goal,
                       is_client_visible=visible)


def stake(tenant, contact, *, cadence=Cadence.WEEKLY, task=None, project=None, goal=None):
    return Stakeholder.all_objects.create(tenant=tenant, contact=contact, cadence=cadence,
                                          task=task, project=project, goal=goal)


def move(task, ff, status, line=""):
    apply_task_changes(task, actor=ff.user, role="FF", changes={"status": status},
                       client_facing_line=line)
    task.refresh_from_db()
    return task


def generate_weekly(tenant, *, now=None):
    """Generate as the scheduler would, inside the review window."""
    now = now or timezone.now()
    window = digest_service.next_window(tenant, Cadence.WEEKLY, after=now)
    return digest_service.generate_scheduled(tenant, cadence=Cadence.WEEKLY,
                                             now=window - timedelta(hours=1))


# ------------------------------------------------------------------ AC-3.5

@pytest.mark.django_db
def test_ac_3_5_the_digest_names_both_transitions_and_quotes_the_line_verbatim(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    line = "Invoices now clear in four days instead of eleven."
    first = a_task(seeded_tenant, company, ff=ff, project=project, title="Map the process")
    second = a_task(seeded_tenant, company, ff=ff, project=project, title="Automate matching")
    stake(seeded_tenant, recipient, project=project)
    move(first, ff, S.IN_PROGRESS, line)
    move(second, ff, S.IN_PROGRESS)

    made = generate_weekly(seeded_tenant)
    assert len(made) == 1
    digest = made[0]
    assert digest.state == Digest.State.PENDING
    assert "Map the process" in digest.body_text and "Automate matching" in digest.body_text
    assert line in digest.body_text, "The line must be quoted verbatim."
    assert digest.is_ai_generated is False     # this company has AI prose off
    # The two transitions. The tasks' creation predates the attachment, so a new
    # stakeholder is not sent the history of work they were not following.
    assert digest.items.count() == 2


@pytest.mark.django_db
def test_ac_3_5_the_ai_narrative_is_given_only_transitions_and_written_lines(
    seeded_tenant, ff, company, recipient, project, fake_claude, in_tenant_a
):
    company.digest_ai_prose = True
    company.save()
    line = "We can now see where invoices stall."
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, line)

    fake_claude.reply = "Work began on mapping, and the stalls are now visible."
    digest = generate_weekly(seeded_tenant)[0]

    assert digest.is_ai_generated is True
    assert fake_claude.reply in digest.body_text
    assert line in digest.body_text
    # What Claude was given: the transitions and the line, and nothing else.
    sent = fake_claude.requests[0]
    given = sent["messages"][0]["content"]
    assert line in given and "Map the process" in given
    assert "northwind" not in given.lower() and "Dana" not in given
    assert "must not assert any fact" in sent["system"]


@pytest.mark.django_db
def test_a_claude_failure_still_produces_the_deterministic_digest(
    seeded_tenant, ff, company, recipient, project, fake_claude, in_tenant_a
):
    import anthropic
    import httpx2

    company.digest_ai_prose = True
    company.save()
    fake_claude.raise_exc = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Still true without Claude.")

    digest = generate_weekly(seeded_tenant)[0]
    assert "Still true without Claude." in digest.body_text
    assert digest.state == Digest.State.PENDING


# ------------------------------------------------------------ AC-3.6, 3.7

@pytest.mark.django_db
def test_ac_3_6_nothing_sends_while_held_and_expiry_defers_rather_than_drops(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    assert seeded_tenant.hold_all_digests is True      # the Beta default
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "First week.")
    digest = generate_weekly(seeded_tenant)[0]

    past_window = digest.send_window_at + timedelta(minutes=1)
    digest_service.expire_due(seeded_tenant, now=past_window)
    digest_service.send_due(seeded_tenant, now=past_window)

    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED
    assert dev_outbox == [], "A held digest was delivered."
    assert not OutboxMessage.all_objects.filter(producer="digest").exists()
    assert digest.items.count() == 0, "The claim must be released."

    # Deferred, not dropped: the same update is owed again next period.
    next_round = digest_service.generate(
        tenant=seeded_tenant, contact=recipient, cadence=Cadence.WEEKLY,
        period_start=past_window, period_end=past_window + timedelta(days=7),
        send_window_at=past_window + timedelta(days=7),
    )
    assert next_round is not None and "First week." in next_round.body_text


@pytest.mark.django_db
def test_ac_3_7_approval_sends_and_is_recorded(seeded_tenant, ff, company, recipient,
                                                project, dev_outbox, in_tenant_a):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    row = stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.WAITING_ON_CLIENT, "We need your AP login.")
    digest = generate_weekly(seeded_tenant)[0]

    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)

    digest.refresh_from_db()
    row.refresh_from_db()
    assert digest.state == Digest.State.SENT
    assert len(dev_outbox) == 1
    delivered = dev_outbox[0]
    assert delivered.to == ["dana@northwind.invalid"]
    assert "We need your AP login." in delivered.body
    assert "/updates/" in delivered.body, "FR-3.33 — the cadence link is in every footer."
    message = OutboxMessage.all_objects.get(producer="digest")
    assert message.state == "sent" and digest.outbox_message_id == message.pk
    assert row.last_notified_at is not None
    approved = AuditEvent.all_objects.get(verb="digest.approved")
    assert approved.actor_id == ff.user_id
    assert AuditEvent.all_objects.filter(verb="digest.sent").exists()


# ------------------------------------------------------------------ AC-3.8

@pytest.mark.django_db
@pytest.mark.parametrize("hold,ai,expected", [
    (True, True, "pending"),     # held: waits
    (True, False, "pending"),    # held: waits, deterministic or not
    (False, True, "pending"),    # unheld but AI-written: still waits
    (False, False, "approved"),  # unheld and deterministic: sends on cadence
])
def test_ac_3_8_the_four_combinations_of_hold_and_ai_prose(
    hold, ai, expected, seeded_tenant, ff, company, recipient, project, fake_claude,
    dev_outbox, in_tenant_a
):
    seeded_tenant.hold_all_digests = hold
    seeded_tenant.save()
    company.digest_ai_prose = ai
    company.save()
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "A line.")

    digest = generate_weekly(seeded_tenant)[0]
    assert digest.state == expected

    # And what actually leaves, at the window.
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)
    digest.refresh_from_db()
    if expected == "approved":
        assert digest.state == Digest.State.SENT and len(dev_outbox) == 1
    else:
        assert digest.state == Digest.State.PENDING and dev_outbox == []


# ------------------------------------------------------------------ AC-3.9

@pytest.mark.django_db
def test_ac_3_9_silence_produces_silence(seeded_tenant, ff, company, recipient, project,
                                          dev_outbox, in_tenant_a):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Something happened this week.")
    # Consume that, then let a quiet period pass.
    first = generate_weekly(seeded_tenant)[0]
    digest_service.approve(first, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=first.send_window_at)

    later = timezone.now() + timedelta(days=7)
    made = digest_service.generate_scheduled(
        seeded_tenant, cadence=Cadence.WEEKLY,
        now=digest_service.next_window(seeded_tenant, Cadence.WEEKLY, after=later)
        - timedelta(hours=1))
    assert made == [], "Nobody should receive 'nothing happened this week'."
    assert len(dev_outbox) == 1


# ----------------------------------------------------------- AC-3.10, 3.32

@pytest.mark.django_db
def test_ac_3_10_and_3_32_every_update_batches_on_the_quiet_window(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project, cadence=Cadence.EVERY_UPDATE)
    for status in (S.IN_PROGRESS, S.BLOCKED, S.IN_PROGRESS, S.DONE):
        move(task, ff, status)

    # Inside the burst: nothing yet.
    assert digest_service.close_quiet_windows(seeded_tenant) == []

    later = timezone.now() + timedelta(minutes=31)
    made = digest_service.close_quiet_windows(seeded_tenant, now=later)
    assert len(made) == 1, "Four changes in five minutes must be one email."
    digest = made[0]
    assert digest.cadence == Cadence.EVERY_UPDATE
    assert digest.state == Digest.State.PENDING       # hold is on
    assert digest.send_window_at <= later             # not 24 hours later
    assert digest.items.count() >= 4

    # A second pass creates nothing more: the draft's claim covers those updates.
    before = Digest.all_objects.count()
    digest_service.close_quiet_windows(seeded_tenant, now=later)
    assert Digest.all_objects.count() == before
    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.EVERY_UPDATE) == []


@pytest.mark.django_db
def test_ac_3_32_unheld_and_deterministic_every_update_sends_on_quiet_close(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    seeded_tenant.hold_all_digests = False
    seeded_tenant.save()
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS, "Started.")

    later = timezone.now() + timedelta(minutes=31)
    digest = digest_service.close_quiet_windows(seeded_tenant, now=later)[0]
    assert digest.state == Digest.State.APPROVED
    digest_service.send_due(seeded_tenant, now=later)
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and len(dev_outbox) == 1


# ----------------------------------------------------------------- AC-3.11

@pytest.mark.django_db
def test_ac_3_11_most_specific_attachment_wins_for_cadence(
    seeded_tenant, ff, company, recipient, goal, project, in_tenant_a
):
    covered = a_task(seeded_tenant, company, ff=ff, project=project, title="Covered by project")
    urgent = a_task(seeded_tenant, company, ff=ff, project=project, title="Urgent one")
    stake(seeded_tenant, recipient, project=project, cadence=Cadence.WEEKLY)
    stake(seeded_tenant, recipient, task=urgent, cadence=Cadence.MONTHLY)

    from apps.work import stakeholders as stakeholder_service

    assert stakeholder_service.effective_for_task(covered)[recipient.pk].cadence == "weekly"
    assert stakeholder_service.effective_for_task(urgent)[recipient.pk].cadence == "monthly"

    move(covered, ff, S.IN_PROGRESS)
    move(urgent, ff, S.IN_PROGRESS)
    weekly = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence="weekly")
    monthly = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence="monthly")
    assert {u.task_id for u, _ in weekly} == {covered.pk}
    assert {u.task_id for u, _ in monthly} == {urgent.pk}


# ---------------------------------------------------------- AC-3.33, 3.34

@pytest.mark.django_db
def test_ac_3_33_one_update_reaches_two_recipients_independently(
    seeded_tenant, ff, company, recipient, goal, project, dev_outbox, in_tenant_a
):
    other = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Reyes",
                           company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=other, address="sam@northwind.invalid",
                        is_primary=True)
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, goal=goal, cadence=Cadence.WEEKLY)
    stake(seeded_tenant, other, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS, "Shared moment.")

    later = timezone.now() + timedelta(minutes=31)
    theirs = digest_service.close_quiet_windows(seeded_tenant, now=later)[0]
    assert theirs.contact_id == other.pk
    digest_service.approve(theirs, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=later)

    # Sending to Sam must not consume Dana's copy.
    weekly = generate_weekly(seeded_tenant)
    dana = [d for d in weekly if d.contact_id == recipient.pk]
    assert len(dana) == 1 and "Shared moment." in dana[0].body_text

    digest_service.approve(dana[0], actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=dana[0].send_window_at)
    # Now consumed for both, and repeated to neither.
    for contact in (recipient, other):
        assert digest_service.owed_to(contact.pk, tenant=seeded_tenant,
                                      cadence=Cadence.WEEKLY) == []
        assert digest_service.owed_to(contact.pk, tenant=seeded_tenant,
                                      cadence=Cadence.EVERY_UPDATE) == []


@pytest.mark.django_db
def test_ac_3_34_expiry_releases_one_claim_without_touching_the_other(
    seeded_tenant, ff, company, recipient, goal, project, in_tenant_a
):
    other = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Reyes",
                           company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=other, address="sam2@northwind.invalid",
                        is_primary=True)
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, goal=goal, cadence=Cadence.WEEKLY)
    stake(seeded_tenant, other, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS, "One event, two readers.")

    later = timezone.now() + timedelta(minutes=31)
    sams = digest_service.close_quiet_windows(seeded_tenant, now=later)[0]
    digest_service.approve(sams, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=later)
    sams_body = sams.body_text
    sams_items = list(sams.items.values_list("pk", flat=True))

    danas = [d for d in generate_weekly(seeded_tenant) if d.contact_id == recipient.pk][0]
    past = danas.send_window_at + timedelta(minutes=1)
    digest_service.expire_due(seeded_tenant, now=past)

    danas.refresh_from_db()
    sams.refresh_from_db()
    assert danas.state == Digest.State.EXPIRED and danas.items.count() == 0
    # Sam is untouched and not re-sent.
    assert sams.state == Digest.State.SENT and sams.body_text == sams_body
    assert list(sams.items.values_list("pk", flat=True)) == sams_items
    assert digest_service.owed_to(other.pk, tenant=seeded_tenant,
                                  cadence=Cadence.EVERY_UPDATE) == []
    # Dana is owed it again.
    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert task.pk in {u.task_id for u, _ in owed}


# ----------------------------------------------------------------- AC-3.35

@pytest.mark.django_db
def test_ac_3_35_one_person_one_friday_email_from_two_attachments(
    seeded_tenant, ff, company, recipient, goal, project, in_tenant_a
):
    under_goal = a_task(seeded_tenant, company, ff=ff, goal=goal, title="On the goal")
    under_project = a_task(seeded_tenant, company, ff=ff, project=project, title="On the project")
    stake(seeded_tenant, recipient, goal=goal, cadence=Cadence.WEEKLY)
    stake(seeded_tenant, recipient, project=project, cadence=Cadence.WEEKLY)
    move(under_goal, ff, S.IN_PROGRESS)
    move(under_project, ff, S.DONE)

    made = generate_weekly(seeded_tenant)
    mine = [d for d in made if d.contact_id == recipient.pk]
    assert len(mine) == 1, "Two attachments must not mean two emails."
    assert "On the goal" in mine[0].body_text and "On the project" in mine[0].body_text
    assert Digest.all_objects.filter(contact=recipient, cadence=Cadence.WEEKLY).count() == 1


# ----------------------------------------------------------- AC-3.19, 3.21

@pytest.mark.django_db
def test_ac_3_19_a_hidden_task_stays_out_of_every_digest(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    hidden = a_task(seeded_tenant, company, ff=ff, project=project, title="Fee review",
                    visible=False)
    stake(seeded_tenant, recipient, project=project)
    move(hidden, ff, S.IN_PROGRESS, "Internal only.")

    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.WEEKLY) == []
    assert generate_weekly(seeded_tenant) == []
    # ...while remaining fully visible internally.
    assert TaskUpdate.all_objects.filter(task=hidden, kind=K.STATUS_CHANGED).exists()


@pytest.mark.django_db
def test_ac_3_21_an_approved_digest_is_never_rewritten(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Before approval.")
    digest = generate_weekly(seeded_tenant)[0]
    digest_service.approve(digest, actor=ff.user, role="FF")
    frozen, frozen_items = digest.body_text, digest.items.count()

    move(task, ff, S.DONE, "After approval.")

    digest.refresh_from_db()
    assert digest.body_text == frozen, "An approved digest was rewritten."
    assert digest.items.count() == frozen_items
    assert digest.is_stale is False, "An approved digest is an artefact, not a draft."

    digest_service.send_due(seeded_tenant, now=digest.send_window_at)
    assert len(dev_outbox) == 1 and "After approval." not in dev_outbox[0].body

    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert "After approval." in [u.client_facing_line for u, _ in owed]


# ----------------------------------------------------------------- AC-3.20

@pytest.mark.django_db
def test_ac_3_20_a_stale_draft_names_the_change_and_regenerates(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Mapped the flow.")
    digest = generate_weekly(seeded_tenant)[0]
    assert digest.is_stale is False

    move(task, ff, S.DONE, "Automation is live.")

    digest.refresh_from_db()
    assert digest.is_stale is True
    assert "Map the process" in digest.stale_reason
    assert "completed" in digest.stale_reason or "done" in digest.stale_reason
    assert "Automation is live." not in digest.body_text

    # It can still be approved as-is: the flag informs, it does not block.
    assert digest.state == Digest.State.PENDING

    digest_service.regenerate(digest, actor=ff.user)
    digest.refresh_from_db()
    assert digest.is_stale is False and digest.stale_reason == ""
    assert "Automation is live." in digest.body_text
    assert "Mapped the flow." in digest.body_text


# ----------------------------------------------------------------- AC-3.22

@pytest.mark.django_db
def test_ac_3_22_generation_thursday_send_friday_local_across_dst(seeded_tenant):
    """Denver, defaults unchanged: Friday 08:00 local, generated 24 h before,
    and both hold across a daylight-saving boundary."""
    assert seeded_tenant.timezone == "America/Denver"
    assert seeded_tenant.digest_send_day == 5 and seeded_tenant.digest_send_hour == 8

    from datetime import datetime

    for label, moment in [
        ("before the spring change", datetime(2027, 3, 10, 12, tzinfo=DENVER)),
        ("across the spring change", datetime(2027, 3, 13, 12, tzinfo=DENVER)),
        ("across the autumn change", datetime(2027, 10, 30, 12, tzinfo=DENVER)),
    ]:
        window = digest_service.next_window(seeded_tenant, Cadence.WEEKLY, after=moment)
        local = window.astimezone(DENVER)
        assert local.isoweekday() == 5, f"{label}: not Friday"
        assert (local.hour, local.minute) == (8, 0), f"{label}: not 08:00 local"
        generation = (window - digest_service.REVIEW_LEAD).astimezone(DENVER)
        assert generation.isoweekday() == 4 and generation.hour == 8, f"{label}: generation"


@pytest.mark.django_db
def test_the_monthly_window_is_the_first_send_day_covering_last_month(seeded_tenant):
    """Owner decision, 2026-09-11."""
    from datetime import datetime

    window = digest_service.next_window(
        seeded_tenant, Cadence.MONTHLY, after=datetime(2026, 9, 20, 12, tzinfo=DENVER))
    local = window.astimezone(DENVER)
    assert (local.year, local.month, local.day) == (2026, 10, 2)   # first Friday
    assert local.isoweekday() == 5 and local.hour == 8

    start, end = digest_service.period_for(seeded_tenant, Cadence.MONTHLY, window)
    assert start.astimezone(DENVER).strftime("%Y-%m-%d") == "2026-09-01"
    assert end.astimezone(DENVER).strftime("%Y-%m-%d") == "2026-10-01"


# ----------------------------------------------------------- AC-3.24, 3.25

@pytest.mark.django_db
def test_ac_3_24_a_stakeholder_needs_no_login_and_no_seat(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    from apps.accounts.models import User
    from apps.tenancy.models import Membership

    users_before = User.objects.count()
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "No login needed.")
    digest = generate_weekly(seeded_tenant)[0]
    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)

    assert dev_outbox[0].to == ["dana@northwind.invalid"]
    assert User.objects.count() == users_before, "A digest recipient is not a login."
    assert not Membership.all_objects.filter(contact=recipient).exists()
    assert company.seats_in_use == 0


@pytest.mark.django_db
def test_ac_3_25_the_cadence_link_works_without_a_session_and_grants_nothing_else(
    seeded_tenant, ff, company, recipient, project, dev_outbox, client, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    row = stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Read me.")
    digest = generate_weekly(seeded_tenant)[0]
    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)

    token = dev_outbox[0].body.split("/updates/")[1].split()[0].strip()

    # No session at all.
    shown = client.get(f"/api/cadence/{token}")
    assert shown.status_code == 200 and shown.json()["cadence"] == "weekly"
    changed = client.post(f"/api/cadence/{token}", json.dumps({"cadence": "monthly"}),
                          content_type="application/json")
    assert changed.status_code == 200 and changed.json()["cadence"] == "monthly"
    row.refresh_from_db()
    assert row.cadence == "monthly"
    assert AuditEvent.all_objects.filter(verb="stakeholder.cadence_changed").exists()

    # The token opens nothing else.
    for path in (f"/api/tasks/{task.pk}/", f"/api/digests/{digest.pk}/",
                 "/api/stakeholders/", f"/api/progress-report/?contact={recipient.pk}"):
        assert client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}").status_code in (401, 403)

    # Stopping mutes rather than deletes: the row is still the practice's record.
    stopped = client.post(f"/api/cadence/{token}", json.dumps({"stop": True}),
                          content_type="application/json")
    assert stopped.status_code == 200 and stopped.json()["is_muted"] is True
    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.MONTHLY) == []

    # Removing the stakeholder kills the token (FR-3.33b).
    from apps.work.services import revoke_stakeholder_tokens

    revoke_stakeholder_tokens(row)
    assert client.get(f"/api/cadence/{token}").status_code == 404


@pytest.mark.django_db
def test_ac_3_26_the_on_demand_report_needs_a_login(seeded_tenant, ff, api, company,
                                                     recipient, project, client, in_tenant_a):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Pull me.")

    assert client.get(f"/api/progress-report/?contact={recipient.pk}").status_code in (401, 403)
    signed_in = api.as_(ff).get(f"/api/progress-report/?contact={recipient.pk}&days=30")
    assert signed_in.status_code == 200
    assert "Pull me." in signed_in.json()["body_text"]


@pytest.mark.django_db
def test_the_on_demand_report_consumes_nothing(seeded_tenant, ff, api, company, recipient,
                                                project, in_tenant_a):
    """FR-3.38 — reading a report must never eat the Friday email."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Still owed.")
    api.as_(ff).get(f"/api/progress-report/?contact={recipient.pk}&days=30")

    assert DigestItem.all_objects.count() == 0
    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert "Still owed." in [u.client_facing_line for u, _ in owed]


# ----------------------------------------------------------------- AC-3.36

@pytest.mark.django_db
def test_ac_3_36_a_derived_status_reflects_a_database_change_with_no_recalculation(
    seeded_tenant, ff, company, goal, project, in_tenant_a
):
    from apps.work.status import status_of

    task = a_task(seeded_tenant, company, ff=ff, project=project)
    assert status_of(goal) == S.NOT_STARTED
    # Straight to the database, bypassing every code path.
    Task.all_objects.filter(pk=task.pk).update(status=S.BLOCKED)
    goal.refresh_from_db()
    assert status_of(goal) == S.BLOCKED


# -------------------------------------------------- the client's own update

@pytest.mark.django_db
def test_a_clients_own_action_does_not_email_them_but_does_reach_the_others(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    """`task_update.is_client_actor` — visible to everyone, never the trigger
    for an email to its own author."""
    from apps.tenancy.models import Membership

    task = a_task(seeded_tenant, company, ff=ff, project=project)
    membership = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company,
                                   contact=recipient)
    stake(seeded_tenant, recipient, project=project)
    other = ContactFactory(tenant=seeded_tenant, first_name="Sam", company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=other, address="sam3@northwind.invalid",
                        is_primary=True)
    stake(seeded_tenant, other, project=project)

    add_comment(task, author=membership.user, role="FCC", body="Any news?")

    mine = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    theirs = digest_service.owed_to(other.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert not any(u.kind == K.COMMENT_ADDED for u, _ in mine)
    assert any(u.kind == K.COMMENT_ADDED for u, _ in theirs)


@pytest.mark.django_db
def test_a_cf_only_sees_digests_for_companies_they_are_assigned(
    seeded_tenant, ff, cf, api, company, recipient, project, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Assigned or not.")
    generate_weekly(seeded_tenant)

    assert api.as_(cf).get("/api/digests/").json() == []
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert len(api.as_(cf).get("/api/digests/").json()) == 1
