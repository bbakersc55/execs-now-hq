"""Pipeline part 3: a stage's follow-up (S3's "Enroll in X?").

Two or three steps: the first drafted the moment it starts, each after it a
library template N days after the previous one was sent; offered when
someone moves into the stage (default No), started without asking by a stage
rule; each step drafted into the Outbox once for approval; stopped by any email from the contact, a move, an
unsubscribe, a step expiring or refused unsent, or Stop, with a waiting draft
withdrawn. Isolation and roles.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import (
    FollowUp, FollowUpRun, FollowUpRunStep, FollowUpStep, OutboxMessage, StageAutomation,
)
from apps.crm.services import follow_ups, outbox, pipeline
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, EmailMessageFactory, EmailTemplateFactory,
    EmailThreadFactory, MembershipFactory, StageAutomationFactory, TenantFactory,
)

pytestmark = pytest.mark.django_db
Run = FollowUpRun
S = OutboxMessage.State


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


@pytest.fixture
def setup(seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    one = EmailTemplateFactory(tenant=t, name="Proposal 1", subject="Hi {FirstName}",
                               body="About the proposal, {FirstName}.")
    two = EmailTemplateFactory(tenant=t, name="Proposal 2", subject="Again", body="Second.")
    three = EmailTemplateFactory(tenant=t, name="Proposal 3", subject="Last", body="Third.")
    stage = stages["proposal_given"]
    found = follow_ups.save(stage, [{"template": str(one.pk), "days_after": 3},
                                    {"template": str(two.pk), "days_after": 7},
                                    {"template": str(three.pk), "days_after": 10}], actor=ff.user)
    return {"t": t, "stage": stage, "follow_up": found, "templates": (one, two, three)}


def person(t, ff, name="Ada"):
    c = ContactFactory(tenant=t, first_name=name, owner=ff.user)
    ContactEmailFactory(tenant=t, contact=c, is_primary=True, address=f"{name.lower()}@x.invalid")
    return c


def moved_in(setup, ff, name="Ada"):
    c = person(setup["t"], ff, name)
    pipeline.change_stage(c, setup["stage"], actor=ff.user)
    return c


def drafts(contact):
    return list(OutboxMessage.all_objects.filter(to_contact=contact,
                                                 producer="follow_up").order_by("created_at"))


def send(message):
    OutboxMessage.all_objects.filter(pk=message.pk).update(state=S.SENT, sent_at=timezone.now())


def day(n, tenant=None):
    """n days from today where the practice is (the follow-up's own clock)."""
    from apps.tenancy.models import Tenant

    tenant = tenant or Tenant.objects.order_by("created_at").first()
    return follow_ups._today(tenant) + timedelta(days=n)


# ---------------------------------------------------------------- the offer

def test_moving_in_offers_the_follow_up_and_starts_nothing_until_asked(setup, ff, api):
    c = person(setup["t"], ff)
    response = post(api.as_(ff), f"/api/contacts/{c.pk}/change-stage/",
                    {"stage": str(setup["stage"].pk)})
    offer = response.json()["follow_up_offer"]
    assert offer["question"] == "Start the Proposal Given follow-up?" and offer["steps"] == 3
    assert not Run.all_objects.filter(contact=c).exists()        # the default is No
    started = post(api.as_(ff), f"/api/contacts/{c.pk}/follow-up/",
                   {"stage": str(setup["stage"].pk)})
    assert started.status_code == 200 and started.json()["running"] == 1
    line = next(p for p in started.json()["contact"]["pipeline_positions"]
                if p["follow_up"])["follow_up"]
    assert line["step"] == 1 and line["of"] == 3
    # Step 1 is drafted at once, not by the next day's job.
    assert line["text"] == "Follow-up: step 1 of 3, waiting for approval in the Outbox"
    [first] = drafts(c)
    assert first.state == S.PENDING_APPROVAL and first.subject == "Hi Ada"
    # Asked again, nothing doubles.
    post(api.as_(ff), f"/api/contacts/{c.pk}/follow-up/", {"stage": str(setup["stage"].pk)})
    assert Run.all_objects.filter(contact=c).count() == 1
    again = post(api.as_(ff), f"/api/contacts/{c.pk}/change-stage/",
                 {"stage": str(setup["stage"].pk)})
    assert again.json()["follow_up_offer"] is None


def test_a_stage_rule_starts_it_without_asking(setup, sales, ff):
    StageAutomationFactory(tenant=setup["t"], pipeline=sales, to_stage=setup["stage"],
                           action_type=StageAutomation.Action.START_FOLLOW_UP)
    c = moved_in(setup, ff)
    run = Run.all_objects.get(contact=c)
    assert run.started_via == "rule" and run.next_on is None
    assert [d.subject for d in drafts(c)] == ["Hi Ada"]
    assert follow_ups.offer(c, setup["stage"]) is None


def test_a_rule_to_start_a_follow_up_needs_the_stage_to_have_one(setup, sales, stages, ff, api):
    url = "/api/stage-automations/"
    body = {"pipeline": str(sales.pk), "to_stage": str(stages["qualified"].pk),
            "action_type": "start_follow_up"}
    assert "no follow-up yet" in str(post(api.as_(ff), url, body).json())
    body["to_stage"] = str(setup["stage"].pk)
    made = post(api.as_(ff), url, body)
    assert made.status_code == 201
    assert made.json()["summary"].endswith("start the stage's follow-up without asking.")


# ---------------------------------------------------------------- the steps

def test_each_step_is_drafted_once_on_its_day_and_waits_for_the_one_before_to_send(setup, ff):
    t = setup["t"]
    c = moved_in(setup, ff)
    follow_ups.start(c, setup["stage"], actor=ff.user)
    assert len(drafts(c)) == 1                                        # step 1, at the start
    assert follow_ups.advance(t, day(0))["drafted"] == 0              # once, however often
    assert follow_ups.advance(t, day(30))["drafted"] == 0             # waits for its send
    [first] = drafts(c)
    assert first.state == S.PENDING_APPROVAL and first.subject == "Hi Ada"
    assert first.send_by is not None
    # The once-only guard holds even if the run's day were set back by hand.
    run = Run.all_objects.get(contact=c)
    assert not follow_ups.draft_step(run, FollowUpStep.all_objects.get(
        follow_up=setup["follow_up"], position=1))
    assert FollowUpRunStep.all_objects.filter(run=run).count() == 1
    send(first)
    follow_ups.advance(t, day(0))
    run.refresh_from_db()
    assert run.next_on == day(7)                                     # counted from the send
    assert follow_ups.advance(t, day(6))["drafted"] == 0
    assert follow_ups.advance(t, run.next_on)["drafted"] == 1
    send(drafts(c)[1])
    follow_ups.advance(t, day(0))
    run.refresh_from_db()
    assert run.next_on == day(10)
    assert follow_ups.advance(t, run.next_on)["drafted"] == 1
    send(drafts(c)[2])
    assert follow_ups.advance(t, day(60))["finished"] == 1
    run.refresh_from_db()
    assert run.status == Run.Status.FINISHED and len(drafts(c)) == 3


# ---------------------------------------------------------------- stopping

def started_with_a_waiting_draft(setup, ff, name="Ada"):
    c = moved_in(setup, ff, name)
    follow_ups.start(c, setup["stage"], actor=ff.user)
    [draft] = drafts(c)
    assert draft.state == S.PENDING_APPROVAL
    return c, draft


def stopped(c):
    run = Run.all_objects.get(contact=c)
    return run.status == Run.Status.STOPPED, run.stop_reason


def test_any_email_from_the_contact_stops_it_and_withdraws_the_draft(setup, ff):
    c, draft = started_with_a_waiting_draft(setup, ff)
    EmailMessageFactory(tenant=setup["t"], direction="inbound",
                        thread=EmailThreadFactory(tenant=setup["t"], contact=c))
    assert stopped(c) == (True, "replied")
    draft.refresh_from_db()
    assert draft.state == S.REJECTED and "they sent an email" in draft.warning


def test_an_email_to_them_does_not_stop_it(setup, ff):
    c, _ = started_with_a_waiting_draft(setup, ff)
    EmailMessageFactory(tenant=setup["t"], direction="outbound",
                        thread=EmailThreadFactory(tenant=setup["t"], contact=c))
    assert stopped(c) == (False, "")


def test_moving_to_another_stage_stops_it(setup, stages, ff):
    c, draft = started_with_a_waiting_draft(setup, ff)
    pipeline.change_stage(c, stages["negotiation"], actor=ff.user)
    assert stopped(c) == (True, "moved")
    draft.refresh_from_db()
    assert draft.state == S.REJECTED


def test_unsubscribing_stops_it(setup, ff):
    from apps.crm.services import unsubscribe

    c, draft = started_with_a_waiting_draft(setup, ff)
    unsubscribe.unsubscribe({"t": str(setup["t"].pk), "c": str(c.pk)},
                            category=unsubscribe.MARKETING)
    assert stopped(c) == (True, "unsubscribed")
    draft.refresh_from_db()
    assert draft.state in (S.SUPPRESSED, S.REJECTED)


def test_a_step_expiring_unsent_stops_it(setup, ff):
    c, draft = started_with_a_waiting_draft(setup, ff)
    outbox.expire_due(setup["t"], now=timezone.now() + timedelta(days=8))
    draft.refresh_from_db()
    assert draft.state == S.EXPIRED
    assert follow_ups.advance(setup["t"], day(9))["stopped"] == 1
    assert stopped(c) == (True, "expired")


def test_a_step_refused_in_the_outbox_stops_it(setup, ff):
    c, draft = started_with_a_waiting_draft(setup, ff)
    outbox.reject(draft, actor=ff.user)
    follow_ups.advance(setup["t"], day(4))
    assert stopped(c) == (True, "refused")


def test_stop_on_the_contacts_page_withdraws_the_waiting_draft(setup, ff, api):
    c, draft = started_with_a_waiting_draft(setup, ff)
    run = Run.all_objects.get(contact=c)
    response = post(api.as_(ff), f"/api/contacts/{c.pk}/follow-up/", {"stop": str(run.pk)})
    assert response.status_code == 200 and response.json()["running"] == 0
    assert stopped(c) == (True, "stopped")
    draft.refresh_from_db()
    assert draft.state == S.REJECTED
    assert follow_ups.advance(setup["t"], day(60))["drafted"] == 0


def test_started_from_the_board_its_draft_is_there_for_stop_to_withdraw(setup, ff, api):
    """The owner's check (2026-10-24): start from the board, see step 1 in the
    Outbox at once, press Stop, see it withdrawn, all without the daily job."""
    c = person(setup["t"], ff)
    client = api.as_(ff)
    post(client, f"/api/contacts/{c.pk}/change-stage/", {"stage": str(setup["stage"].pk)})
    post(client, f"/api/contacts/{c.pk}/follow-up/", {"stage": str(setup["stage"].pk)})
    outbox_ids = {m["id"] for m in client.get("/api/outbox/").json()}
    [draft] = drafts(c)
    assert str(draft.pk) in outbox_ids
    run = Run.all_objects.get(contact=c)
    post(client, f"/api/contacts/{c.pk}/follow-up/", {"stop": str(run.pk)})
    draft.refresh_from_db()
    assert draft.state == S.REJECTED and "it was stopped" in draft.warning


def test_an_unsubscribed_contact_is_not_started(setup, ff):
    from apps.crm.services import unsubscribe

    c = moved_in(setup, ff)
    unsubscribe.unsubscribe({"t": str(setup["t"].pk), "c": str(c.pk)},
                            category=unsubscribe.MARKETING)
    with pytest.raises(follow_ups.FollowUpRefused, match="unsubscribed"):
        follow_ups.start(c, setup["stage"], actor=ff.user)
    assert drafts(c) == [] and not Run.all_objects.filter(contact=c).exists()


# ---------------------------------------------------------------- setting it up

def test_the_follow_up_card_saves_two_or_three_steps(setup, stages, ff, api):
    url = f"/api/pipeline-stages/{stages['qualified'].pk}/follow-up/"
    one, two, _ = setup["templates"]
    client = api.as_(ff)
    assert client.get(url).json() == {"follow_up": None}
    one_step = client.put(url, json.dumps({"steps": [{"template": str(one.pk), "days_after": 2}]}),
                          content_type="application/json")
    assert one_step.status_code == 400 and "two or three" in str(one_step.json())
    saved = client.put(url, json.dumps({"steps": [{"template": str(one.pk), "days_after": 2},
                                                  {"template": str(two.pk), "days_after": 5}]}),
                       content_type="application/json")
    assert saved.status_code == 200
    assert [(s["template_name"], s["days_after"]) for s in saved.json()["follow_up"]["steps"]] == [
        ("Proposal 1", 0), ("Proposal 2", 5)]                       # step 1: at the start
    assert client.delete(url).status_code == 200
    assert client.get(url).json() == {"follow_up": None}
    for role in ("CF", "VA"):
        m = MembershipFactory(tenant=setup["t"], role=role)
        assert api.as_(m).put(url, json.dumps({"steps": []}),
                              content_type="application/json").status_code == 403


def test_the_two_starters_are_one_click_examples(seeded_tenant, sales, referrals, ff, api):
    client = api.as_(ff)
    offered = client.get(f"/api/stage-automations/examples/?pipeline={sales.pk}").json()
    proposal = next(e for e in offered if e["key"] == "proposal_follow_up_sequence")
    assert proposal["kind"] == "follow_up" and "drafted when it starts" in proposal["summary"]
    assert "7 days after that one is sent" in proposal["summary"]
    made = post(client, "/api/stage-automations/examples/",
                {"pipeline": str(sales.pk), "key": "proposal_follow_up_sequence"})
    assert made.status_code == 201
    assert [s["days_after"] for s in made.json()["steps"]] == [0, 7]
    partner = post(client, "/api/stage-automations/examples/",
                   {"pipeline": str(referrals.pk), "key": "new_partner_follow_up_sequence"})
    assert [s["days_after"] for s in partner.json()["steps"]] == [0, 20]
    names = {s["template_name"] for s in partner.json()["steps"]}
    assert names == {"New partner follow-up 1", "New partner follow-up 2"}
    # On the wrong pipeline it isn't offered.
    assert post(client, "/api/stage-automations/examples/",
                {"pipeline": str(sales.pk), "key": "new_partner_follow_up_sequence"}
                ).status_code == 400


# ---------------------------------------------------------------- isolation

def test_another_practices_follow_ups_are_out_of_reach(setup, ff, api):
    from apps.crm.seed import seed_tenant

    c, draft = started_with_a_waiting_draft(setup, ff)
    other = TenantFactory()
    seed_tenant(other)
    b = api.as_(MembershipFactory(tenant=other, role="FF"))
    run = Run.all_objects.get(contact=c)
    assert post(b, f"/api/contacts/{c.pk}/follow-up/", {"stop": str(run.pk)}).status_code == 404
    assert b.get(f"/api/pipeline-stages/{setup['stage'].pk}/follow-up/").status_code == 404
    # The daily pass for B drafts nothing of A's.
    assert follow_ups.advance(other, day(60)) == {"drafted": 0, "stopped": 0, "finished": 0}
    assert stopped(c) == (False, "")
    with tenant_context(other.pk):
        assert not FollowUp.objects.exists()
