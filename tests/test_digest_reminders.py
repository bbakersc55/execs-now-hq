"""Reminder emails about digests (docs/digest_schedule.md §6).

Held down here: **who** receives each (the practice owner for everything, an
associate for their own clients', nobody else, in this practice only), **what**
is in them (names and times, never a digest's text), **when** (ready at the
draft, a last call only if something still waits, not-sent at the send time),
and that none is repeated.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.crm.models import OutboxMessage, Task
from apps.tenancy.context import tenant_context
from apps.work import digest_reminders, digests as digest_service
from apps.work.models import Cadence, Digest

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    GoalFactory, MembershipFactory, ProjectFactory, TenantFactory,
)
from .test_module3_digests import (  # noqa: F401  (fixtures)
    a_task, company, goal, move, project, recipient, run_tick, stake,
)

S = Task.Status
MOUNTAIN = ZoneInfo("America/Denver")
SECRET_LINE = "Margins fell four points; do not share outside the board."


def at(*parts):
    return datetime(*parts, tzinfo=MOUNTAIN)


@pytest.fixture(autouse=True)
def reminders_on(settings):
    settings.DIGEST_REMINDERS_ENABLED = True


@pytest.fixture
def friday_to_monday(seeded_tenant):
    """Bryan's schedule: drafted Friday 3:00 PM, sent Monday 8:00 AM."""
    seeded_tenant.digest_draft_day, seeded_tenant.digest_draft_hour = 5, 15
    seeded_tenant.digest_send_day, seeded_tenant.digest_send_hour = 1, 8
    seeded_tenant.save()
    # A cycle safely in the future, so work written "now" falls before it.
    send = digest_service.next_window(
        seeded_tenant, Cadence.WEEKLY, after=digest_service.timezone.now() + timedelta(days=7))
    return digest_service.draft_before(seeded_tenant, send), send


def to(dev_outbox, address):
    return [m for m in dev_outbox if m.to == [address]]


def work_for(tenant, ff, company, recipient, project, line=SECRET_LINE):
    task = a_task(tenant, company, ff=ff, project=project)
    stake(tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, line)
    return task


# --------------------------------------------------------------- who and what

@pytest.mark.django_db
def test_the_owner_is_told_when_the_digests_are_drafted(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)

    run_tick(seeded_tenant, draft - timedelta(minutes=1))
    assert dev_outbox == [], "Nothing is drafted yet, so there is nothing to say."
    result = run_tick(seeded_tenant, draft + timedelta(minutes=1))

    assert result["digest_reminders"] == 1
    mail = to(dev_outbox, ff.user.email)
    assert len(mail) == 1 and len(dev_outbox) == 1
    assert mail[0].subject == "1 digest is ready to approve"
    body = mail[0].body
    assert "Dana Okafor" in body and "Northwind Foods" in body and "weekly digest" in body
    local = send.astimezone(MOUNTAIN)
    assert f"Monday {local.day} {local:%B}, 8:00 AM" in body
    assert "is not sent" in body and "/digests" in body
    row = OutboxMessage.all_objects.get(producer="digest_reminder")
    assert row.to_address == ff.user.email and row.state == OutboxMessage.State.SENT
    assert row.to_contact_id is None


@pytest.mark.django_db
def test_a_reminder_never_carries_a_digests_text(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    """D5: client material is read in the app, not forwarded around in mail."""
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    for moment in (draft + timedelta(minutes=1), send - timedelta(hours=1),
                   send + timedelta(minutes=1)):
        run_tick(seeded_tenant, moment)

    assert len(dev_outbox) == 3            # ready, last call, not sent
    digest = Digest.all_objects.get(contact=recipient)
    assert SECRET_LINE in digest.body_text
    for message in dev_outbox:
        whole = message.subject + message.body + "".join(
            content for content, _type in getattr(message, "alternatives", []))
        assert SECRET_LINE not in whole and "Margins" not in whole
        assert "Map the process" not in whole, "Not even the task's title."
    for row in OutboxMessage.all_objects.filter(producer="digest_reminder"):
        assert SECRET_LINE not in row.body_text + row.body_html


@pytest.mark.django_db
def test_an_associate_hears_about_their_own_clients_digests_only(
    seeded_tenant, ff, cf, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    draft, _send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    # A second client, not the associate's.
    other_co = ClientCompanyFactory(tenant=seeded_tenant, name="Southwind Freight",
                                    digest_ai_prose=False)
    other_contact = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Reyes",
                                   company=other_co)
    ContactEmailFactory(tenant=seeded_tenant, contact=other_contact,
                        address="sam@southwind.invalid", is_primary=True)
    other_goal = GoalFactory(tenant=seeded_tenant, title="Other", client_company=other_co)
    other_project = ProjectFactory(tenant=seeded_tenant, title="Other project",
                                   client_company=other_co, goal=other_goal)
    work_for(seeded_tenant, ff, other_co, other_contact, other_project, line="Theirs.")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)

    run_tick(seeded_tenant, draft + timedelta(minutes=1))

    owners = to(dev_outbox, ff.user.email)
    theirs = to(dev_outbox, cf.user.email)
    assert len(owners) == 1 and owners[0].subject == "2 digests are ready to approve"
    assert "Dana Okafor" in owners[0].body and "Sam Reyes" in owners[0].body
    assert len(theirs) == 1 and theirs[0].subject == "1 digest is ready to approve"
    assert "Dana Okafor" in theirs[0].body
    assert "Sam Reyes" not in theirs[0].body and "Southwind" not in theirs[0].body


@pytest.mark.django_db
def test_only_people_who_can_approve_are_reminded(
    seeded_tenant, ff, cf, va, company, recipient, project, dev_outbox, friday_to_monday,
    in_tenant_a
):
    """An associate with no assigned client, an assistant, a removed associate
    and both kinds of client user get nothing; the recipient of the digest
    least of all."""
    from django.utils import timezone

    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    gone = MembershipFactory(tenant=seeded_tenant, role="CF")
    ClientAssignmentFactory(tenant=seeded_tenant, user=gone.user, company=company)
    type(gone).all_objects.filter(pk=gone.pk).update(revoked_at=timezone.now())
    portal = [MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
              for role in ("FCC", "ECC")]

    for moment in (draft + timedelta(minutes=1), send - timedelta(hours=1),
                   send + timedelta(minutes=1)):
        run_tick(seeded_tenant, moment)

    assert {m.to[0] for m in dev_outbox} == {ff.user.email}
    for nobody in (cf, va, gone, *portal):
        assert to(dev_outbox, nobody.user.email) == []
    assert to(dev_outbox, "dana@northwind.invalid") == [], "Never to a client."


@pytest.mark.django_db
def test_reminders_stay_inside_the_practice(
    seeded_tenant, tenant_b, ff, company, recipient, project, dev_outbox, friday_to_monday,
    in_tenant_a
):
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    b_owner = MembershipFactory(tenant=tenant_b, role="FF")

    run_tick(seeded_tenant, draft + timedelta(minutes=1))
    with tenant_context(tenant_b.pk):
        assert digest_reminders.run(tenant_b, now=draft + timedelta(minutes=1)) == 0
        assert run_tick(tenant_b, draft + timedelta(minutes=2))["digest_reminders"] == 0

    assert to(dev_outbox, b_owner.user.email) == []
    assert not OutboxMessage.all_objects.filter(tenant=tenant_b).exists()
    assert {m.to[0] for m in dev_outbox} == {ff.user.email}


# ------------------------------------------------------------------- when

@pytest.mark.django_db
def test_each_reminder_is_sent_once(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)

    for minutes in (1, 2, 3, 30, 60):                       # Friday, after the draft
        run_tick(seeded_tenant, draft + timedelta(minutes=minutes))
    assert [m.subject for m in dev_outbox] == [
        "1 digest is ready to approve",
        "Last call: 1 digest still waiting for approval",     # Friday 4:00 PM
    ]
    for hours in (20, 40, 64):                              # the weekend
        run_tick(seeded_tenant, draft + timedelta(hours=hours))
    assert len(dev_outbox) == 2

    for minutes in (1, 2, 30):                              # Monday, after 8:00 AM
        run_tick(seeded_tenant, send + timedelta(minutes=minutes))
    assert [m.subject for m in dev_outbox][2:] == ["1 digest was not sent"]
    assert "Send now" in dev_outbox[2].body


@pytest.mark.django_db
def test_no_last_call_and_no_not_sent_when_everything_was_approved(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    run_tick(seeded_tenant, draft + timedelta(minutes=1))
    digest_service.approve(Digest.all_objects.get(contact=recipient), actor=ff.user, role="FF")

    run_tick(seeded_tenant, draft + timedelta(minutes=70))        # past Friday 4:00 PM
    run_tick(seeded_tenant, send + timedelta(minutes=1))

    reminders = to(dev_outbox, ff.user.email)
    assert [m.subject for m in reminders] == ["1 digest is ready to approve"]
    # ...and the digest itself went to the client, approved, on time.
    assert len(to(dev_outbox, "dana@northwind.invalid")) == 1


@pytest.mark.django_db
def test_nothing_is_sent_when_nothing_is_waiting(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    draft, send = friday_to_monday
    stake(seeded_tenant, recipient, project=project)             # a stakeholder, no work
    for moment in (draft + timedelta(minutes=1), send - timedelta(hours=1),
                   send + timedelta(minutes=1)):
        assert run_tick(seeded_tenant, moment)["digest_reminders"] == 0
    assert dev_outbox == []


@pytest.mark.django_db
@pytest.mark.parametrize("draft,send,expected", [
    # Bryan's: the Monday 6:00 AM that "two hours before" gives is nobody's
    # working hour, so it goes at the end of Friday.
    ((2026, 10, 9, 15), (2026, 10, 12, 8), (2026, 10, 9, 16)),
    # The default: Thursday 4:00 PM, not Friday 6:00 AM.
    ((2026, 10, 8, 8), (2026, 10, 9, 8), (2026, 10, 8, 16)),
    # A same-day window in working hours: two hours before.
    ((2026, 10, 9, 9), (2026, 10, 9, 15), (2026, 10, 9, 13)),
    # Across a weekend with a Tuesday send: Monday 4:00 PM.
    ((2026, 10, 9, 15), (2026, 10, 13, 8), (2026, 10, 12, 16)),
    # No weekday afternoon between the two: two hours before, regardless.
    ((2026, 10, 10, 8), (2026, 10, 11, 8), (2026, 10, 11, 6)),
    ((2026, 10, 9, 17), (2026, 10, 12, 8), (2026, 10, 12, 6)),
])
def test_the_last_call_arrives_when_someone_is_at_work(draft, send, expected, seeded_tenant):
    assert digest_reminders.last_call_at(seeded_tenant, at(*draft), at(*send)) == at(*expected)


@pytest.mark.django_db
def test_every_update_digests_are_announced_at_most_once_an_hour(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    from django.utils import timezone

    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.IN_PROGRESS, "First.")
    start = timezone.now() + timedelta(minutes=31)

    run_tick(seeded_tenant, start)
    run_tick(seeded_tenant, start + timedelta(minutes=5))
    assert [m.subject for m in dev_outbox] == ["1 digest is ready to approve"]
    assert "sent as soon as it is approved" in dev_outbox[0].body

    # A second person's digest twenty minutes later waits for the hour.
    other = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Reyes",
                           company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=other, address="sam@northwind.invalid",
                        is_primary=True)
    stake(seeded_tenant, other, task=task, cadence=Cadence.EVERY_UPDATE)
    move(task, ff, S.BLOCKED, "Second.")
    from apps.work.models import Stakeholder, TaskUpdate

    Stakeholder.all_objects.filter(contact=other).update(created_at=start - timedelta(hours=1))
    newest = TaskUpdate.all_objects.filter(task=task).order_by("-created_at").first()
    TaskUpdate.all_objects.filter(pk=newest.pk).update(created_at=start + timedelta(minutes=6))
    run_tick(seeded_tenant, start + timedelta(minutes=40))
    assert len(dev_outbox) == 1, "Inside the hour: held back."

    run_tick(seeded_tenant, start + timedelta(minutes=62))
    assert len(dev_outbox) == 2
    assert "Sam Reyes" in dev_outbox[1].body


# ------------------------------------------------------------- when it cannot

@pytest.mark.django_db
def test_no_mail_connection_skips_the_reminder_and_tries_again(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a,
    monkeypatch
):
    from apps.crm.services import outbox, transport

    draft, _send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)

    def broken(*args, **kwargs):
        raise transport.TransportUnavailable("No Gmail account is connected.")

    with monkeypatch.context() as patch:
        patch.setattr(outbox, "_deliver", broken)
        result = run_tick(seeded_tenant, draft + timedelta(minutes=1))
    assert result["digest_reminders"] == 0 and dev_outbox == []
    # The digest itself was still drafted; only the notice could not go.
    assert Digest.all_objects.filter(contact=recipient, state=Digest.State.PENDING).exists()
    assert not OutboxMessage.all_objects.filter(producer="digest_reminder").exists()

    assert run_tick(seeded_tenant, draft + timedelta(minutes=2))["digest_reminders"] == 1
    assert [m.subject for m in dev_outbox] == ["1 digest is ready to approve"]


@pytest.mark.django_db
def test_the_switch_stops_every_reminder(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a,
    settings
):
    settings.DIGEST_REMINDERS_ENABLED = False
    draft, send = friday_to_monday
    work_for(seeded_tenant, ff, company, recipient, project)
    for moment in (draft + timedelta(minutes=1), send + timedelta(minutes=1)):
        assert run_tick(seeded_tenant, moment)["digest_reminders"] == 0
    assert dev_outbox == []


@pytest.mark.django_db
def test_reminders_send_no_digest_and_approve_nothing(
    seeded_tenant, ff, company, recipient, project, dev_outbox, friday_to_monday, in_tenant_a
):
    """They are notices. With the hold on, a week of them leaves the client
    with nothing and the digest unapproved."""
    draft, send = friday_to_monday
    assert seeded_tenant.hold_all_digests is True
    work_for(seeded_tenant, ff, company, recipient, project)
    for moment in (draft + timedelta(minutes=1), send - timedelta(hours=1),
                   send + timedelta(minutes=1)):
        run_tick(seeded_tenant, moment)

    digest = Digest.all_objects.get(contact=recipient)
    assert digest.state == Digest.State.LATE and digest.approved_by_id is None
    assert to(dev_outbox, "dana@northwind.invalid") == []
    assert not OutboxMessage.all_objects.filter(producer="digest").exists()
