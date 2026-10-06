"""Update this draft, Send now, and the late state (docs/digest_schedule.md §4–5).

What these exist to hold down, in order of consequence:

1. **No update is ever sent to a person twice, and none is lost**, however the
   draft, the update, the timer, a manual send and the fold into the next draft
   are interleaved; including a manual send racing the next draft, with two
   real database connections.
2. Nothing reaches a client without a person's approval, with
   `hold_all_digests` on or off.
3. Who may send: the practice owner, an associate for their own clients, and
   nobody else, in this practice only.
"""

from __future__ import annotations

import json
import random
import threading
from datetime import datetime, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent
from apps.work import digests as digest_service
from apps.work.models import Cadence, Digest, DigestItem, TaskUpdate

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)
from .test_module3_digests import (  # noqa: F401  (fixtures)
    DENVER, a_task, company, generate_weekly, goal, move, project, recipient, run_tick, stake,
)

S = Task.Status
LIVE = (Digest.State.PENDING, Digest.State.APPROVED, Digest.State.LATE, Digest.State.SENT)


def post(client, digest, action):
    return client.post(f"/api/digests/{digest.pk}/{action}/", "{}",
                       content_type="application/json")


def drafted(tenant, ff, company, recipient, project, line="First week."):
    task = a_task(tenant, company, ff=ff, project=project)
    stake(tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, line)
    return task, generate_weekly(tenant)[0]


def make_late(tenant, digest):
    digest_service.expire_due(tenant, now=digest.send_window_at + timedelta(minutes=1))
    digest.refresh_from_db()
    assert digest.state == Digest.State.LATE
    return digest


def bodies(dev_outbox):
    return [m.body for m in dev_outbox]


# ------------------------------------------------------------------ Send now

@pytest.mark.django_db
def test_send_now_on_a_waiting_digest_is_that_persons_approval_then_the_send(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    assert seeded_tenant.hold_all_digests is True

    response = post(api.as_(ff), digest, "send-now")

    assert response.status_code == 200, response.content
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT
    assert digest.approved_by_id == ff.user.pk and digest.approved_at is not None
    assert len(dev_outbox) == 1 and "First week." in dev_outbox[0].body
    assert dev_outbox[0].to == ["dana@northwind.invalid"]
    approved = AuditEvent.all_objects.get(verb="digest.approved", target_id=digest.pk)
    assert approved.actor_id == ff.user.pk and approved.payload["by"] == "send_now"
    by_hand = AuditEvent.all_objects.get(verb="digest.sent_by_hand", target_id=digest.pk)
    assert by_hand.actor_id == ff.user.pk and by_hand.payload["was"] == "pending"
    # ...well before its send time, and the timer does not send it again.
    assert digest.send_window_at > timezone.now()
    digest_service.send_due(seeded_tenant, now=digest.send_window_at + timedelta(minutes=1))
    assert len(dev_outbox) == 1


@pytest.mark.django_db
def test_send_now_sends_an_approved_digest_early_and_only_once(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    digest_service.approve(digest, actor=ff.user, role="FF")

    assert post(api.as_(ff), digest, "send-now").status_code == 200
    assert post(api.as_(ff), digest, "send-now").status_code == 409     # already sent

    digest_service.send_due(seeded_tenant, now=digest.send_window_at + timedelta(minutes=1))
    assert len(dev_outbox) == 1


@pytest.mark.django_db
def test_a_late_digest_can_still_be_sent_by_hand(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    make_late(seeded_tenant, digest)
    assert dev_outbox == [], "The timer never sends an unapproved digest."

    assert post(api.as_(ff), digest, "send-now").status_code == 200

    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and len(dev_outbox) == 1
    # Sent, so the next draft neither folds it away nor reports its work again.
    assert digest_service.expire_late_for(seeded_tenant, recipient.pk, Cadence.WEEKLY) == []
    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.WEEKLY) == []
    move(task, ff, S.DONE, "Second week.")
    following = generate_weekly(seeded_tenant, now=digest.send_window_at + timedelta(days=6))
    assert "First week." not in following[0].body_text
    assert "Second week." in following[0].body_text


@pytest.mark.django_db
def test_a_late_digest_folds_into_the_next_draft_and_then_cannot_be_sent(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    """Until the next draft, and not a moment longer (D12)."""
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    make_late(seeded_tenant, digest)
    move(task, ff, S.DONE, "Second week.")

    # Six days on: the next cycle's Draft on has come.
    following = generate_weekly(seeded_tenant, now=digest.send_window_at + timedelta(days=6))

    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED and digest.items.count() == 0
    assert "First week." in following[0].body_text and "Second week." in following[0].body_text
    refused = post(api.as_(ff), digest, "send-now")
    assert refused.status_code == 409
    assert "folded into the next one" in refused.json()["detail"]
    assert dev_outbox == []


@pytest.mark.django_db
def test_a_late_digest_is_not_folded_before_the_next_draft_time(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    make_late(seeded_tenant, digest)
    send = digest.send_window_at
    next_draft = digest_service.draft_before(seeded_tenant, send + timedelta(days=7))

    for moment in (send + timedelta(hours=1), next_draft - timedelta(minutes=1)):
        run_tick(seeded_tenant, moment)
        digest.refresh_from_db()
        assert digest.state == Digest.State.LATE, moment

    run_tick(seeded_tenant, next_draft + timedelta(minutes=1))
    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED
    assert Digest.all_objects.filter(contact=recipient, state=Digest.State.PENDING).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("hold", [True, False])
def test_the_timer_never_sends_what_nobody_approved(
    hold, seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    """With the hold off a plain digest is approved by rule when written, as
    before; one a person has not approved (an AI-written one, or any digest
    with the hold on) is never sent by the timer. This change adds no path."""
    seeded_tenant.hold_all_digests = hold
    seeded_tenant.save()
    company.digest_ai_prose = True          # AI prose always waits for a person
    company.save()
    task = a_task(seeded_tenant, company, ff=ff, project=project)
    stake(seeded_tenant, recipient, project=project)
    move(task, ff, S.IN_PROGRESS, "First week.")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(digest_service, "narrative_for", lambda *a, **k: "An AI paragraph.")
        digest = generate_weekly(seeded_tenant)[0]
    assert digest.state == Digest.State.PENDING

    run_tick(seeded_tenant, digest.send_window_at + timedelta(minutes=1))

    digest.refresh_from_db()
    assert digest.state == Digest.State.LATE and dev_outbox == []
    assert not OutboxMessage.all_objects.filter(producer="digest").exists()


# ------------------------------------------------------- who may send, and see

@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("VA", 403), ("FCC", 404), ("ECC", 404)])
def test_who_may_send_now(role, expected, seeded_tenant, ff, api, company, recipient,
                          project, dev_outbox, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    theirs = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = ff if role == "FF" else MembershipFactory(
        tenant=seeded_tenant, role=role, client_company=theirs)

    response = post(api.as_(member), digest, "send-now")

    assert response.status_code == expected
    digest.refresh_from_db()
    assert (digest.state == Digest.State.SENT) == (expected == 200)
    assert len(dev_outbox) == (1 if expected == 200 else 0)


@pytest.mark.django_db
def test_an_associate_sends_their_own_clients_digests_and_no_one_elses(
    seeded_tenant, ff, cf, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)

    # Not assigned to Northwind: the digest is not theirs to see, let alone send.
    assert post(api.as_(cf), digest, "send-now").status_code == 404
    assert api.as_(cf).get(f"/api/digests/{digest.pk}/send-preview/").status_code == 404
    assert dev_outbox == []

    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert post(api.as_(cf), digest, "send-now").status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and digest.approved_by_id == cf.user.pk


@pytest.mark.django_db
def test_another_practice_can_neither_see_nor_send_it(
    seeded_tenant, tenant_b, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    outsider = api.as_(MembershipFactory(tenant=tenant_b, role="FF"))

    for action in ("send-now", "regenerate"):
        assert post(outsider, digest, action).status_code == 404
    assert outsider.get(f"/api/digests/{digest.pk}/send-preview/").status_code == 404
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING and dev_outbox == []


@pytest.mark.django_db
def test_the_signed_out_send_nothing(seeded_tenant, ff, client, company, recipient, project,
                                     dev_outbox, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    assert post(client, digest, "send-now").status_code in (401, 403)
    assert client.get(f"/api/digests/{digest.pk}/send-preview/").status_code in (401, 403)
    assert dev_outbox == []


@pytest.mark.django_db
def test_the_whole_email_is_shown_before_it_is_sent(
    seeded_tenant, ff, va, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project,
                        line="The invoice run is automated.")

    shown = api.as_(ff).get(f"/api/digests/{digest.pk}/send-preview/").json()

    assert shown["to_name"] == "Dana Okafor" and shown["to_address"] == "dana@northwind.invalid"
    assert shown["subject"] and "The invoice run is automated." in shown["text"]
    assert "The invoice run is automated." in shown["html"]
    # Reading it sends nothing and changes nothing.
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING and dev_outbox == []
    # An assistant may read it (they prepare digests); a client user may not.
    assert api.as_(va).get(f"/api/digests/{digest.pk}/send-preview/").status_code == 200
    portal = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    assert api.as_(portal).get(f"/api/digests/{digest.pk}/send-preview/").status_code == 404

    post(api.as_(ff), digest, "send-now")
    assert "The invoice run is automated." in dev_outbox[0].body
    assert api.as_(ff).get(f"/api/digests/{digest.pk}/send-preview/").status_code == 409


# ------------------------------------------------------------ Update this draft

@pytest.mark.django_db
def test_updating_a_draft_brings_in_work_finished_after_it_was_written(
    seeded_tenant, ff, va, api, company, recipient, project, dev_outbox, in_tenant_a
):
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    send_time = digest.send_window_at
    move(task, ff, S.DONE, "Finished at ten to five.")
    digest.refresh_from_db()
    assert digest.is_stale, "The flag is the reason..."

    # ...and the button is the action, with or without the flag. An assistant
    # may press it: they prepare digests and never approve or send them.
    response = post(api.as_(va), digest, "regenerate")

    assert response.status_code == 200
    digest.refresh_from_db()
    assert "Finished at ten to five." in digest.body_text and "First week." in digest.body_text
    assert digest.is_stale is False and digest.state == Digest.State.PENDING
    # It still sends on the timer, at the time it always had, once approved.
    assert digest.send_window_at == send_time
    digest_service.approve(digest, actor=ff.user, role="FF")
    run_tick(seeded_tenant, send_time + timedelta(minutes=1))
    assert len(dev_outbox) == 1 and "Finished at ten to five." in dev_outbox[0].body


@pytest.mark.django_db
def test_a_draft_can_be_updated_with_no_flag_on_it(
    seeded_tenant, ff, api, company, recipient, project, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    assert digest.is_stale is False
    assert post(api.as_(ff), digest, "regenerate").status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING and "First week." in digest.body_text


@pytest.mark.django_db
def test_a_late_digest_can_be_updated_and_then_sent(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    make_late(seeded_tenant, digest)
    move(task, ff, S.DONE, "Done over the weekend.")
    digest.refresh_from_db()
    assert digest.is_stale, "Work landing after it flags a late digest too."

    assert post(api.as_(ff), digest, "regenerate").status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.LATE and "Done over the weekend." in digest.body_text

    assert post(api.as_(ff), digest, "send-now").status_code == 200
    assert len(dev_outbox) == 1
    assert "First week." in dev_outbox[0].body and "Done over the weekend." in dev_outbox[0].body
    assert digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                  cadence=Cadence.WEEKLY) == []


@pytest.mark.django_db
def test_an_approved_digest_is_final(seeded_tenant, ff, api, company, recipient, project,
                                     in_tenant_a):
    """D4: it cannot be updated; work finished after it goes in the next one."""
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    digest_service.approve(digest, actor=ff.user, role="FF")
    body = digest.body_text
    move(task, ff, S.DONE, "After approval.")

    assert post(api.as_(ff), digest, "regenerate").status_code == 409
    digest.refresh_from_db()
    assert digest.body_text == body and digest.state == Digest.State.APPROVED
    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert "After approval." in [u.client_facing_line for u, _ in owed]


@pytest.mark.django_db
def test_a_late_digest_can_be_skipped_and_its_work_comes_round_again(
    seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a
):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    make_late(seeded_tenant, digest)
    assert post(api.as_(ff), digest, "skip").status_code == 200
    owed = digest_service.owed_to(recipient.pk, tenant=seeded_tenant, cadence=Cadence.WEEKLY)
    assert "First week." in [u.client_facing_line for u, _ in owed] and dev_outbox == []


# ------------------------------------------ never twice, never lost: sequences

def _check_claims(tenant, recipients, lines):
    """The invariant, at any moment: for each person, each update is held by
    at most one live digest; and each line written so far is either held by
    one, or still owed. Never both, never neither, never two."""
    for contact in recipients:
        held = {}
        for item in DigestItem.all_objects.filter(
                tenant=tenant, digest__contact=contact, digest__state__in=LIVE):
            held.setdefault(item.task_update_id, []).append(item.digest_id)
        assert all(len(v) == 1 for v in held.values()), f"claimed twice for {contact}"
        owed = {u.pk for u, _ in digest_service.owed_to(
            contact.pk, tenant=tenant, cadence=Cadence.WEEKLY)}
        assert not (owed & set(held)), "both claimed and owed"
        wanted = set(TaskUpdate.all_objects.filter(
            tenant=tenant, client_facing_line__in=lines).values_list("pk", flat=True))
        assert wanted <= (owed | set(held)), "an update is neither claimed nor owed: lost"


@pytest.mark.django_db
@pytest.mark.parametrize("seed", range(12))
def test_no_update_is_ever_sent_twice_or_lost(
    seed, seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    """Random weeks of real ticks. Each week: work lands, the digests are
    drafted, and then, in a random order and mix, a draft is updated,
    approved, sent by hand, left to go late, sent by hand late, or left to
    fold into the next draft. Every line of work must reach each of two
    recipients in exactly one email."""
    rng = random.Random(seed)
    other = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Reyes",
                           company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=other, address="sam@northwind.invalid",
                        is_primary=True)
    recipients = [recipient, other]
    tasks = [a_task(seeded_tenant, company, ff=ff, project=project, title=f"Task {n}")
             for n in range(3)]
    for contact in recipients:
        stake(seeded_tenant, contact, project=project)
    lines = []

    def work():
        for _ in range(rng.randint(0, 2)):
            task = rng.choice(tasks)
            line = f"[work {seed}-{len(lines):03d}]"       # no label inside another
            status = S.IN_PROGRESS if task.status != S.IN_PROGRESS else S.BLOCKED
            move(task, ff, status, line)
            lines.append(line)

    def act(states):
        for digest in Digest.all_objects.filter(tenant=seeded_tenant, state__in=states):
            choice = rng.choice(["nothing", "update", "approve", "send_now", "work"])
            try:
                if choice == "update":
                    digest_service.regenerate(digest, actor=ff.user)
                elif choice == "approve":
                    digest_service.approve(digest, actor=ff.user, role="FF")
                elif choice == "send_now":
                    digest_service.send_now(digest, actor=ff.user, role="FF")
                elif choice == "work":
                    work()
            except (digest_service.DigestActionRefused, ValueError):
                pass                      # refused is a fine answer; twice is not
            _check_claims(seeded_tenant, recipients, lines)

    first_send = digest_service.next_window(
        seeded_tenant, Cadence.WEEKLY, after=timezone.now() + timedelta(days=7))
    for week in range(5):
        send = first_send + timedelta(days=7 * week)
        draft = digest_service.draft_before(seeded_tenant, send)
        work()
        run_tick(seeded_tenant, draft + timedelta(minutes=1))      # drafts; folds late ones
        _check_claims(seeded_tenant, recipients, lines)
        act([Digest.State.PENDING, Digest.State.APPROVED])
        run_tick(seeded_tenant, send + timedelta(minutes=1))       # sends approved; rest go late
        _check_claims(seeded_tenant, recipients, lines)
        act([Digest.State.LATE])

    # Wind down: one more cycle in which everything outstanding is sent.
    send = first_send + timedelta(days=35)
    run_tick(seeded_tenant, digest_service.draft_before(seeded_tenant, send) + timedelta(minutes=1))
    for digest in Digest.all_objects.filter(tenant=seeded_tenant, state=Digest.State.PENDING):
        digest_service.approve(digest, actor=ff.user, role="FF")
    run_tick(seeded_tenant, send + timedelta(minutes=1))
    _check_claims(seeded_tenant, recipients, lines)

    # Every line reached each person in exactly one email. Not zero, not two.
    assert len(dev_outbox) == Digest.all_objects.filter(
        tenant=seeded_tenant, state=Digest.State.SENT).count()
    for contact, address in ((recipient, "dana@northwind.invalid"),
                             (other, "sam@northwind.invalid")):
        received = [m.body for m in dev_outbox if m.to == [address]]
        for line in lines:
            carrying = [body for body in received if line in body]
            assert len(carrying) == 1, (
                f"seed {seed}: {line!r} reached {address} {len(carrying)} times")


# --------------------------- a manual send racing the next draft, for real

def _in_thread(tenant_id, fn, errors):
    def run():
        try:
            with tenant_context(tenant_id):
                fn()
        except Exception as exc:                       # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()
    thread = threading.Thread(target=run)
    thread.start()
    return thread


def _late_digest_with_new_work(tenant, ff, company, recipient, project):
    task, digest = drafted(tenant, ff, company, recipient, project, line="Week one.")
    make_late(tenant, digest)
    move(task, ff, S.DONE, "Week two.")
    return digest


@pytest.mark.django_db(transaction=True)
def test_send_now_wins_the_race_with_the_next_draft(
    seeded_tenant, ff, company, recipient, project, dev_outbox, monkeypatch
):
    """Two connections. Send now holds the digest's row; the tick that drafts
    the next digest has to wait for it, then finds the digest sent, leaves its
    claims alone, and drafts only the new work."""
    with tenant_context(seeded_tenant.pk):
        digest = _late_digest_with_new_work(seeded_tenant, ff, company, recipient, project)
        next_cycle = digest.send_window_at + timedelta(days=6)
    holding, release, errors = threading.Event(), threading.Event(), []
    real_send = digest_service.send

    def slow_send(*args, **kwargs):
        message = real_send(*args, **kwargs)
        holding.set()                # sent, inside the transaction, lock still held
        release.wait(timeout=10)
        return message

    monkeypatch.setattr(digest_service, "send", slow_send)
    sender = _in_thread(seeded_tenant.pk, lambda: digest_service.send_now(
        Digest.all_objects.get(pk=digest.pk), actor=ff.user, role="FF"), errors)
    assert holding.wait(timeout=10)

    drafter = _in_thread(seeded_tenant.pk, lambda: digest_service.generate_scheduled(
        seeded_tenant, cadence=Cadence.WEEKLY, now=next_cycle), errors)
    drafter.join(timeout=1.0)
    assert drafter.is_alive(), "The drafter must wait for the send to finish."

    release.set()
    sender.join(timeout=10)
    drafter.join(timeout=10)
    assert errors == []

    with tenant_context(seeded_tenant.pk):
        digest.refresh_from_db()
        assert digest.state == Digest.State.SENT and digest.items.count() >= 1
        new = Digest.all_objects.get(contact=recipient, state=Digest.State.PENDING)
        assert "Week two." in new.body_text and "Week one." not in new.body_text
        assert len(dev_outbox) == 1 and "Week one." in dev_outbox[0].body
        claimed = list(DigestItem.all_objects.filter(digest__contact=recipient)
                       .values_list("task_update_id", flat=True))
        assert len(claimed) == len(set(claimed)), "An update is claimed twice."


@pytest.mark.django_db(transaction=True)
def test_the_next_draft_wins_the_race_with_send_now(
    seeded_tenant, ff, company, recipient, project, dev_outbox, monkeypatch
):
    """The other order. The drafter holds the row while it folds the late
    digest away; Send now waits, then finds it expired, refuses, and sends
    nothing. Both weeks are in the new draft, once."""
    with tenant_context(seeded_tenant.pk):
        digest = _late_digest_with_new_work(seeded_tenant, ff, company, recipient, project)
        next_cycle = digest.send_window_at + timedelta(days=6)
    holding, release, errors, refusals = threading.Event(), threading.Event(), [], []
    real_fold = digest_service._enter_dead_state

    def slow_fold(*args, **kwargs):
        result = real_fold(*args, **kwargs)
        holding.set()                # expired, inside the transaction, lock still held
        release.wait(timeout=10)
        return result

    monkeypatch.setattr(digest_service, "_enter_dead_state", slow_fold)
    drafter = _in_thread(seeded_tenant.pk, lambda: digest_service.generate_scheduled(
        seeded_tenant, cadence=Cadence.WEEKLY, now=next_cycle), errors)
    assert holding.wait(timeout=10)

    def try_to_send():
        try:
            digest_service.send_now(Digest.all_objects.get(pk=digest.pk),
                                    actor=ff.user, role="FF")
        except digest_service.DigestActionRefused as refused:
            refusals.append(str(refused))

    sender = _in_thread(seeded_tenant.pk, try_to_send, errors)
    sender.join(timeout=1.0)
    assert sender.is_alive(), "Send now must wait for the fold to finish."

    release.set()
    drafter.join(timeout=10)
    sender.join(timeout=10)
    assert errors == []

    assert refusals == [digest_service.FOLDED]
    with tenant_context(seeded_tenant.pk):
        digest.refresh_from_db()
        assert digest.state == Digest.State.EXPIRED and digest.items.count() == 0
        assert dev_outbox == [], "A refused Send now sends nothing."
        new = Digest.all_objects.get(contact=recipient, state=Digest.State.PENDING)
        assert "Week one." in new.body_text and "Week two." in new.body_text
        claimed = list(DigestItem.all_objects.filter(digest__contact=recipient)
                       .values_list("task_update_id", flat=True))
        assert len(claimed) == len(set(claimed)), "An update is claimed twice."


@pytest.mark.django_db(transaction=True)
def test_send_now_and_the_timer_cannot_both_send_an_approved_digest(
    seeded_tenant, ff, company, recipient, project, dev_outbox, monkeypatch
):
    with tenant_context(seeded_tenant.pk):
        _, digest = drafted(seeded_tenant, ff, company, recipient, project, line="Week one.")
        digest_service.approve(digest, actor=ff.user, role="FF")
        send_time = digest.send_window_at + timedelta(minutes=1)
    holding, release, errors = threading.Event(), threading.Event(), []
    real_send = digest_service.send

    def slow_send(*args, **kwargs):
        message = real_send(*args, **kwargs)
        if not holding.is_set():
            holding.set()
            release.wait(timeout=10)
        return message

    monkeypatch.setattr(digest_service, "send", slow_send)

    def by_hand():
        try:
            digest_service.send_now(Digest.all_objects.get(pk=digest.pk),
                                    actor=ff.user, role="FF")
        except digest_service.DigestActionRefused:
            pass

    hand = _in_thread(seeded_tenant.pk, by_hand, errors)
    assert holding.wait(timeout=10)
    timer = _in_thread(seeded_tenant.pk, lambda: digest_service.send_due(
        seeded_tenant, now=send_time), errors)
    timer.join(timeout=1.0)
    assert timer.is_alive(), "The timer must wait for the manual send."
    release.set()
    hand.join(timeout=10)
    timer.join(timeout=10)

    assert errors == [] and len(dev_outbox) == 1
