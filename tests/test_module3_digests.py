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
    assert digest.generated_at <= later               # generated now, not 24 hours later
    # FR-3.28d — held, it waits a review lead before it can expire. This line
    # used to assert the window was "now", which is exactly the Check 4 bug:
    # the same tick then expired it.
    assert digest.send_window_at == later + digest_service.REVIEW_LEAD
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


# ------------------------------------------------ "Generate now" (dev only)

@pytest.mark.django_db
def test_generate_now_runs_the_real_path_for_a_chosen_stakeholder(
    seeded_tenant, ff, api, company, recipient, project, in_tenant_a
):
    """The manual checks should not have to wait until Thursday."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Generated on demand.")

    response = api.as_(ff).post(
        "/api/digests/generate-now/",
        json.dumps({"contact": str(recipient.pk), "cadence": "weekly", "days": 7}),
        content_type="application/json")
    assert response.status_code == 201
    body = response.json()
    assert "Generated a pending digest" in body["detail"]
    assert "Generated on demand." in body["digest"]["body_text"]
    # Held, exactly as the Thursday run would be.
    assert body["digest"]["state"] == "pending"
    assert Digest.all_objects.count() == 1
    assert AuditEvent.all_objects.filter(verb="digest.generated_on_demand").exists()

    # It claims what it covered, so the scheduled run will not repeat it.
    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.WEEKLY) == []


@pytest.mark.django_db
def test_generate_now_says_plainly_when_nothing_is_owed(seeded_tenant, ff, api, company,
                                                        recipient, project, in_tenant_a):
    stake(seeded_tenant, recipient, project=project)
    response = api.as_(ff).post(
        "/api/digests/generate-now/", json.dumps({"contact": str(recipient.pk)}),
        content_type="application/json")
    assert response.status_code == 200
    assert response.json()["digest"] is None
    assert "Nothing is owed" in response.json()["detail"]
    assert Digest.all_objects.count() == 0


@pytest.mark.django_db
def test_generate_now_can_put_the_send_window_in_a_moment(seeded_tenant, ff, api, company,
                                                          recipient, project, dev_outbox,
                                                          in_tenant_a):
    """So Check 3 can watch an unapproved digest expire without waiting a week."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Will expire.")
    created = api.as_(ff).post(
        "/api/digests/generate-now/",
        json.dumps({"contact": str(recipient.pk), "days": 7, "send_in_minutes": 2}),
        content_type="application/json").json()["digest"]

    later = timezone.now() + timedelta(minutes=3)
    digest_service.expire_due(seeded_tenant, now=later)
    digest_service.send_due(seeded_tenant, now=later)
    digest = Digest.all_objects.get(pk=created["id"])
    assert digest.state == Digest.State.EXPIRED and dev_outbox == []
    # ...and the content comes back round.
    assert "Will expire." in [u.client_facing_line for u, _ in digest_service.owed_to(
        recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)]


@pytest.mark.django_db
def test_generate_now_does_not_exist_off_localhost(seeded_tenant, ff, api, settings,
                                                   recipient, in_tenant_a):
    settings.IS_LOCAL = False
    response = api.as_(ff).post(
        "/api/digests/generate-now/", json.dumps({"contact": str(recipient.pk)}),
        content_type="application/json")
    assert response.status_code == 404, "A development control reached a real build."


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 404), ("VA", 201),
                                           ("FCC", 403), ("ECC", 403)])
def test_generate_now_follows_the_same_scope_rules(role, expected, seeded_tenant, ff, api,
                                                    company, recipient, project, in_tenant_a):
    """A VA prepares digests (matrix 8.2), so generating one is theirs to do;
    a CF sees only assigned companies, and a client user none of it."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Scope check.")
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    response = api.as_(member).post(
        "/api/digests/generate-now/", json.dumps({"contact": str(recipient.pk)}),
        content_type="application/json")
    assert response.status_code == expected


# ================================ Phase 3 manual checks 3 and 4: through the tick

def run_tick(tenant, now):
    from apps.work.tasks import tick

    return tick(str(tenant.pk), now=now)


@pytest.mark.django_db
def test_check_3_the_tick_expires_an_unapproved_digest_past_its_window_and_releases_claims(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    """Check 3: a digest with a 2-minute window, left unapproved. The server did
    expire it (the database shows it 4 s after its window); the approval screen
    never refreshed. This holds the server half down through the real tick."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Left unapproved.")
    created = api.as_(ff).post(
        "/api/digests/generate-now/",
        json.dumps({"contact": str(recipient.pk), "days": 7, "send_in_minutes": 2}),
        content_type="application/json").json()["digest"]
    digest = Digest.all_objects.get(pk=created["id"])
    assert digest.state == Digest.State.PENDING and digest.items.count() >= 1
    claimed = list(digest.items.values_list("task_update_id", flat=True))

    # Before the window: the tick leaves it alone.
    run_tick(seeded_tenant, digest.send_window_at - timedelta(seconds=30))
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING

    result = run_tick(seeded_tenant, digest.send_window_at + timedelta(seconds=30))
    digest.refresh_from_db()
    assert result["expired"] == 1
    assert digest.state == Digest.State.EXPIRED
    assert digest.items.count() == 0
    assert not DigestItem.all_objects.filter(task_update_id__in=claimed).exists(), (
        "Its claims must be released.")
    assert AuditEvent.all_objects.filter(verb="digest.expired", target_id=digest.pk).exists()
    assert dev_outbox == []
    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert "Left unapproved." in [u.client_facing_line for u, _ in owed], (
        "Deferred, not dropped.")


@pytest.mark.django_db
def test_check_4_a_held_every_update_digest_survives_the_tick_that_made_it(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    """Check 4: the tick generated it with a window of "now" and its own expiry
    step removed it four seconds later, so it never reached the approval list."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    for status in (S.IN_PROGRESS, S.WAITING_ON_CLIENT):
        move(task, ff, status)

    closes = timezone.now() + timedelta(minutes=31)
    assert run_tick(seeded_tenant, closes)["every_update_generated"] == 1
    digest = Digest.all_objects.get(cadence=Cadence.EVERY_UPDATE)
    assert digest.state == Digest.State.PENDING, "It expired in the tick that made it."
    assert digest.send_window_at == closes + digest_service.REVIEW_LEAD

    # Later ticks neither expire it nor pretend to generate it again.
    later = run_tick(seeded_tenant, closes + timedelta(minutes=5))
    assert later["every_update_generated"] == 0 and later["expired"] == 0
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING

    # Approval sends it on the next tick, not a day later.
    digest_service.approve(digest, actor=ff.user, role="FF")
    run_tick(seeded_tenant, closes + timedelta(minutes=6))
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and len(dev_outbox) == 1


@pytest.mark.django_db
def test_check_4_an_unapproved_every_update_digest_expires_after_its_review_lead(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    closes = timezone.now() + timedelta(minutes=31)
    run_tick(seeded_tenant, closes)
    digest = Digest.all_objects.get(cadence=Cadence.EVERY_UPDATE)

    run_tick(seeded_tenant, closes + digest_service.REVIEW_LEAD + timedelta(minutes=1))
    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED and digest.items.count() == 0
    assert dev_outbox == []


@pytest.mark.django_db
def test_check_4_an_expired_digest_does_not_block_its_content_forever(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    """The second half of Check 4: once expired, the same updates were owed
    again under the same period start, matched the dead row, and every tick
    reported "generated 1" while generating nothing."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    closes = timezone.now() + timedelta(minutes=31)
    run_tick(seeded_tenant, closes)
    first = Digest.all_objects.get(cadence=Cadence.EVERY_UPDATE)
    after_expiry = closes + digest_service.REVIEW_LEAD + timedelta(minutes=1)
    run_tick(seeded_tenant, after_expiry)
    first.refresh_from_db()
    assert first.state == Digest.State.EXPIRED

    result = run_tick(seeded_tenant, after_expiry + timedelta(minutes=1))
    assert result["every_update_generated"] == 1
    live = Digest.all_objects.exclude(pk=first.pk).get(cadence=Cadence.EVERY_UPDATE)
    assert live.state == Digest.State.PENDING and live.items.count() == 1
    assert live.period_start == first.period_start, "Same content, same period start."
    first.refresh_from_db()
    assert first.state == Digest.State.EXPIRED, "History is not rewritten."


# ------------------------------------------------------- is the tick running

def a_tick_result(tenant, *, stopped, success=True, result=None):
    import uuid

    from django_q.models import Task as QueuedTask

    return QueuedTask.objects.create(
        id=uuid.uuid4().hex, name=f"tick-{uuid.uuid4().hex[:6]}",
        func="apps.work.tasks.tick", args=(str(tenant.pk),), kwargs={},
        started=stopped - timedelta(seconds=1), stopped=stopped, success=success,
        result=result,
    )


@pytest.mark.django_db
def test_tick_health_says_stale_when_nothing_has_run(seeded_tenant, tenant_b, in_tenant_a):
    from apps.work.tasks import tick_health

    assert tick_health(seeded_tenant)["stale"] is True
    # Another tenant's tick is not this tenant's.
    a_tick_result(tenant_b, stopped=timezone.now())
    assert tick_health(seeded_tenant)["stale"] is True


@pytest.mark.django_db
def test_tick_health_is_fresh_within_five_minutes_and_names_a_failure(seeded_tenant,
                                                                     in_tenant_a):
    from apps.work.tasks import tick_health

    now = timezone.now()
    a_tick_result(seeded_tenant, stopped=now - timedelta(minutes=4))
    health = tick_health(seeded_tenant, now=now)
    assert health["stale"] is False and health["last_failure"] == ""

    a_tick_result(seeded_tenant, stopped=now - timedelta(minutes=1), success=False,
                  result="ProgrammingError: column tenant.x does not exist")
    health = tick_health(seeded_tenant, now=now + timedelta(minutes=2))
    assert health["stale"] is True, "Six minutes since the last success."
    assert "column tenant.x does not exist" in health["last_failure"]


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 200),
                                           ("FCC", 403), ("ECC", 403)])
def test_tick_status_is_for_the_practice(role, expected, seeded_tenant, api, company):
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=company if role in ("FCC", "ECC") else None)
    response = api.as_(member).get("/api/digests/tick-status/")
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["stale_after_minutes"] == 5


@pytest.mark.django_db
def test_a_digest_past_its_window_cannot_be_approved_before_the_tick_expires_it(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    """FR-3.30 — unapproved at its window means it never sends. Between the window
    and the next tick it was still `pending`, and approving it then would have
    let the following tick send it."""
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "Too late.")
    digest = generate_weekly(seeded_tenant)[0]
    Digest.all_objects.filter(pk=digest.pk).update(
        send_window_at=timezone.now() - timedelta(seconds=10))

    refused = api.as_(ff).post(f"/api/digests/{digest.pk}/approve/")
    assert refused.status_code == 409
    assert "window has passed" in refused.json()["detail"]
    run_tick(seeded_tenant, timezone.now())
    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED and dev_outbox == []


@pytest.mark.django_db
def test_retest_every_update_after_an_expired_and_a_sent_digest_for_the_same_contact(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    """The FR-3.28d retest, reproduced from the dev database (2026-09-15).

    The history there: one every_update digest expired, the same content was
    regenerated under the same period start and sent. Then the task was set to
    Done, and a few minutes later changed again. Nothing appeared "after several
    minutes" — and nothing should have: the quiet window closes 30 minutes after
    the LAST change (FR-3.22), and each later change restarted it. This holds
    down that the earlier expired and sent rows never block the next digest,
    and that it appears once the window has closed.
    """
    from apps.work.tasks import tick

    tenant_id = str(seeded_tenant.pk)
    base = timezone.now() - timedelta(hours=26)
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    row = stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.WAITING_ON_CLIENT)
    Stakeholder.all_objects.filter(pk=row.pk).update(created_at=base - timedelta(minutes=5))
    TaskUpdate.all_objects.filter(task=task).update(created_at=base)

    # The history: expired, then regenerated with the same period start, and sent.
    tick(tenant_id, now=base + timedelta(minutes=31))
    first = Digest.all_objects.get(cadence=Cadence.EVERY_UPDATE)
    tick(tenant_id, now=first.send_window_at + timedelta(minutes=1))
    first.refresh_from_db()
    assert first.state == Digest.State.EXPIRED
    regenerated_at = first.send_window_at + timedelta(minutes=2)
    tick(tenant_id, now=regenerated_at)
    second = Digest.all_objects.exclude(pk=first.pk).get(cadence=Cadence.EVERY_UPDATE)
    assert second.state == Digest.State.PENDING
    assert second.period_start == first.period_start
    digest_service.approve(second, actor=ff.user, role="FF")
    tick(tenant_id, now=regenerated_at + timedelta(minutes=1))
    second.refresh_from_db()
    assert second.state == Digest.State.SENT and len(dev_outbox) == 1

    # The retest: Done, then another change nine minutes later.
    done_at = timezone.now()
    move(task, ff, S.DONE)
    move(task, ff, S.IN_PROGRESS)
    last_change = done_at + timedelta(minutes=9)
    newest = (TaskUpdate.all_objects.filter(task=task, kind=K.STATUS_CHANGED,
                                            to_value=S.IN_PROGRESS)
              .order_by("-created_at").first())
    TaskUpdate.all_objects.filter(pk=newest.pk).update(created_at=last_change)

    # "Several minutes" later — and even 38 minutes after Done — the window is
    # still open, because the later change restarted it.
    for minutes in (1, 5, 20, 38):
        assert tick(tenant_id, now=done_at + timedelta(minutes=minutes))[
            "every_update_generated"] == 0, minutes
    assert Digest.all_objects.filter(cadence=Cadence.EVERY_UPDATE).count() == 2

    result = tick(tenant_id, now=last_change + digest_service.QUIET_WINDOW + timedelta(seconds=30))
    assert result["every_update_generated"] == 1
    third = Digest.all_objects.exclude(pk__in=[first.pk, second.pk]).get(
        cadence=Cadence.EVERY_UPDATE)
    assert third.state == Digest.State.PENDING and third.contact_id == recipient.pk
    claimed = set(third.items.values_list("task_update__to_value", flat=True))
    assert {S.DONE, S.IN_PROGRESS} <= claimed, "The Done change is in it."
    assert third.period_start > second.period_start
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.state == Digest.State.EXPIRED and second.state == Digest.State.SENT
    assert len(dev_outbox) == 1, "Held: nothing more is sent until it is approved."


# ================================ FR-3.29a: coming up, inside the quiet window

@pytest.mark.django_db
def test_coming_up_names_who_waits_on_a_quiet_window_and_agrees_with_the_tick(
    seeded_tenant, ff, api, company, recipient, project, in_tenant_a
):
    from apps.work.tasks import tick

    task = a_task(seeded_tenant, company, ff=ff, project=project, title="Replace the gate")
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    move(task, ff, S.DONE)
    latest = TaskUpdate.all_objects.filter(task=task).order_by("-created_at").first().created_at
    digests_before = Digest.all_objects.count()
    audit_before = AuditEvent.all_objects.count()

    rows = api.as_(ff).get("/api/digests/upcoming/").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["contact"]["name"] == "Dana Okafor" and row["cadence"] == "every_update"
    assert row["tasks"] == ["Replace the gate"] and row["update_count"] >= 2
    assert row["generates_at"] == (latest + digest_service.QUIET_WINDOW).isoformat()
    assert row["due"] is False
    assert Digest.all_objects.count() == digests_before, "Read-only: nothing generated."
    assert AuditEvent.all_objects.count() == audit_before, "Read-only: nothing recorded."

    # The time it states is the time the tick acts on.
    tenant_id = str(seeded_tenant.pk)
    assert tick(tenant_id, now=latest + timedelta(minutes=29))["every_update_generated"] == 0
    assert tick(tenant_id, now=latest + digest_service.QUIET_WINDOW + timedelta(seconds=1))[
        "every_update_generated"] == 1
    assert api.as_(ff).get("/api/digests/upcoming/").json() == [], (
        "Once generated it is in the approval list, not coming up.")
    assert api.as_(ff).post("/api/digests/upcoming/").status_code == 405


@pytest.mark.django_db
def test_coming_up_says_due_when_the_window_closed_before_the_tick_reached_it(
    seeded_tenant, ff, api, company, recipient, project, in_tenant_a
):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    row = stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    long_ago = timezone.now() - timedelta(minutes=31)
    Stakeholder.all_objects.filter(pk=row.pk).update(created_at=long_ago - timedelta(minutes=5))
    TaskUpdate.all_objects.filter(task=task).update(created_at=long_ago)
    assert api.as_(ff).get("/api/digests/upcoming/").json()[0]["due"] is True


@pytest.mark.django_db
def test_coming_up_leaves_out_weekly_muted_and_already_claimed_content(
    seeded_tenant, ff, api, company, recipient, project, in_tenant_a
):
    weekly_task = a_task(seeded_tenant, company, ff=ff, project=project, title="Weekly one")
    stake(seeded_tenant, recipient, task=weekly_task, cadence=Cadence.WEEKLY)
    move(weekly_task, ff, S.IN_PROGRESS)

    muted_contact = ContactFactory(tenant=seeded_tenant, first_name="Mo", last_name="Muted",
                                   company=company)
    muted_task = a_task(seeded_tenant, company, ff=ff, project=project, title="Muted one")
    Stakeholder.all_objects.create(tenant=seeded_tenant, contact=muted_contact, task=muted_task,
                                   cadence=Cadence.EVERY_UPDATE, is_muted=True)
    move(muted_task, ff, S.IN_PROGRESS)
    assert api.as_(ff).get("/api/digests/upcoming/").json() == []

    claimed_task = a_task(seeded_tenant, company, ff=ff, project=project, title="Claimed one")
    stake(seeded_tenant, recipient, task=claimed_task, cadence=Cadence.EVERY_UPDATE)
    move(claimed_task, ff, S.IN_PROGRESS)
    digest_service.close_quiet_windows(seeded_tenant, now=timezone.now() + timedelta(minutes=31))
    assert api.as_(ff).get("/api/digests/upcoming/").json() == []


@pytest.mark.django_db
@pytest.mark.parametrize("role,assigned,expected,count", [
    ("FF", False, 200, 1), ("VA", False, 200, 1), ("CF", True, 200, 1), ("CF", False, 200, 0),
    ("FCC", False, 403, None), ("ECC", False, 403, None),
])
def test_coming_up_is_scoped_like_the_digest_list(role, assigned, expected, count,
                                                  seeded_tenant, ff, api, company, recipient,
                                                  project, in_tenant_a):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=company if role in ("FCC", "ECC") else None)
    if assigned:
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    response = api.as_(member).get("/api/digests/upcoming/")
    assert response.status_code == expected
    if count is not None:
        assert len(response.json()) == count


@pytest.mark.django_db
def test_coming_up_never_crosses_a_tenant(seeded_tenant, tenant_b, ff, api, company, recipient,
                                          project, in_tenant_a):
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS)
    theirs = MembershipFactory(tenant=tenant_b, role="FF")
    assert api.as_(theirs).get("/api/digests/upcoming/").json() == []
