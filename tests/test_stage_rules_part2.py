"""Stage rules, part 2 (owner, 2026-10-24): every trigger, every action, the
loop guard, the stay and activity times, the starter examples, the stage
cards' edits, notices, and who may do what.

Triggers: enters (from any stage, or a named one); has sat N days with no
activity (daily job, once per stay); won; lost. Actions: a task with merge
fields, due in N days, for the contact's owner, the practice owner or a named
member; a draft email into the Outbox; a stage move; referral touches at a
cadence; a notice on Home and in one daily email.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import (
    ContactPipelinePosition, Enrollment, OutboxMessage, PipelineNotice, PipelineStage, StageChange,
    StageAutomation, StageRuleFiring, Task,
)
from apps.crm.services import pipeline, stage_rules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, ContactTypeLinkFactory, EmailMessageFactory,
    EmailTemplateFactory, EmailThreadFactory, MeetingParticipantFactory, MembershipFactory,
    NoteFactory, StageAutomationFactory, TaskFactory, TenantFactory,
)

R = StageAutomation
pytestmark = pytest.mark.django_db


def rule(tenant, pipe, **fields):
    fields.setdefault("action_type", R.Action.CREATE_TASK)
    fields.setdefault("task_title_template", "Follow up")
    return StageAutomationFactory(tenant=tenant, pipeline=pipe, **fields)


def person(tenant, owner=None, **extra):
    contact = ContactFactory(tenant=tenant, owner=owner, **extra)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


def tasks_of(contact):
    return list(Task.all_objects.filter(contact=contact).order_by("created_at"))


def position(contact, pipe):
    return ContactPipelinePosition.all_objects.get(contact=contact, pipeline=pipe)


def post(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


# ---------------------------------------------------------------- triggers

def test_enters_from_any_stage_and_from_a_named_stage(seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    rule(t, sales, to_stage=stages["qualified"], task_title_template="Any way in")
    rule(t, sales, to_stage=stages["qualified"], from_stage=stages["prospecting"],
         task_title_template="From prospecting")
    a, b = person(t, ff.user), person(t, ff.user)
    pipeline.change_stage(a, stages["prospecting"])
    pipeline.change_stage(a, stages["qualified"])
    pipeline.change_stage(b, stages["follow_up_needed"])
    pipeline.change_stage(b, stages["qualified"])
    assert [x.title for x in tasks_of(a)] == ["Any way in", "From prospecting"]
    assert [x.title for x in tasks_of(b)] == ["Any way in"]


def test_won_and_lost_fire_on_any_stage_with_that_meaning_on_their_pipeline(
        seeded_tenant, sales, stages, referrals, referral_stages, ff):
    t = seeded_tenant
    rule(t, sales, trigger=R.Trigger.WON, to_stage=None, task_title_template="Kick off")
    rule(t, sales, trigger=R.Trigger.LOST, to_stage=None, task_title_template="Ask why")
    second_lost = PipelineStage.all_objects.create(tenant=t, pipeline=sales, code="lost_price",
                                                   label="Lost on price", semantic="lost",
                                                   position=20)
    won, lost, lost2 = person(t, ff.user), person(t, ff.user), person(t, ff.user)
    pipeline.change_stage(won, stages["closed_won"])
    pipeline.change_stage(lost, stages["closed_lost"])
    pipeline.change_stage(lost2, second_lost)
    assert [x.title for x in tasks_of(won)] == ["Kick off"]
    assert [x.title for x in tasks_of(lost)] == ["Ask why"]
    assert [x.title for x in tasks_of(lost2)] == ["Ask why"]
    # Another pipeline's won stage is not this pipeline's win.
    other = person(t, ff.user)
    active = PipelineStage.all_objects.filter(pipeline=referrals, semantic="qualified").first()
    pipeline.change_stage(other, active)
    assert tasks_of(other) == []


def test_idle_fires_once_per_stay_counting_from_the_last_activity(seeded_tenant, sales,
                                                                  stages, ff):
    t = seeded_tenant
    idle = rule(t, sales, trigger=R.Trigger.IDLE, to_stage=stages["prospecting"], idle_days=14,
                task_title_template="Nudge {FirstName}")
    contact = person(t, ff.user, first_name="Ada")
    pipeline.change_stage(contact, stages["prospecting"])
    now = timezone.now()
    assert stage_rules.check_idle(t, now + timedelta(days=13)) == 0
    # A note on day 10 is activity: the days start again from it.
    with tenant_context(t.pk):
        NoteFactory(tenant=t, contact=contact)
    ContactPipelinePosition.all_objects.filter(contact=contact).update(
        last_activity_at=now + timedelta(days=10))
    assert stage_rules.check_idle(t, now + timedelta(days=20)) == 0
    assert stage_rules.check_idle(t, now + timedelta(days=25)) == 1
    assert [x.title for x in tasks_of(contact)] == ["Nudge Ada"]
    # Still idle the next day, and the day after: once per stay.
    assert stage_rules.check_idle(t, now + timedelta(days=26)) == 0
    assert stage_rules.check_idle(t, now + timedelta(days=60)) == 0
    assert StageRuleFiring.all_objects.filter(rule=idle, contact=contact).count() == 1
    # Out and back in is a new stay, which can fire again.
    pipeline.change_stage(contact, stages["follow_up_needed"])
    pipeline.change_stage(contact, stages["prospecting"])
    later = timezone.now() + timedelta(days=30)   # past the day-10 note set above
    assert stage_rules.check_idle(t, later) == 1
    assert len(tasks_of(contact)) == 2


def test_an_inactive_rule_fires_nothing(seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    rule(t, sales, to_stage=stages["qualified"], is_active=False)
    rule(t, sales, trigger=R.Trigger.IDLE, to_stage=stages["qualified"], idle_days=1,
         is_active=False)
    contact = person(t, ff.user)
    pipeline.change_stage(contact, stages["qualified"])
    assert stage_rules.check_idle(t, timezone.now() + timedelta(days=5)) == 0
    assert tasks_of(contact) == []


# ---------------------------------------------------------------- activity and the stay

def test_the_stay_and_last_activity_are_kept_up_to_date(seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    contact = person(t, ff.user)
    pipeline.change_stage(contact, stages["prospecting"])
    first = position(contact, sales)
    assert first.stage_entered_at is not None and first.last_activity_at is not None
    entered = first.stage_entered_at

    def bump():
        ContactPipelinePosition.all_objects.filter(contact=contact).update(
            last_activity_at=timezone.now() - timedelta(days=30))

    def fresh():
        return position(contact, sales).last_activity_at > timezone.now() - timedelta(minutes=1)

    for make in (
        lambda: EmailMessageFactory(tenant=t, thread=EmailThreadFactory(tenant=t, contact=contact),
                                    direction="inbound"),
        lambda: EmailMessageFactory(tenant=t, thread=EmailThreadFactory(tenant=t, contact=contact)),
        lambda: NoteFactory(tenant=t, contact=contact),
        lambda: MeetingParticipantFactory(tenant=t, contact=contact),
    ):
        bump()
        make()
        assert fresh()
    # A task finished is activity; a task merely made is not.
    bump()
    task = TaskFactory(tenant=t, contact=contact)
    assert not fresh()
    task.status = Task.Status.DONE
    task.save(update_fields=["status"])
    assert fresh()
    # None of it is a new stay; a move is.
    assert position(contact, sales).stage_entered_at == entered
    pipeline.change_stage(contact, stages["qualified"])
    assert position(contact, sales).stage_entered_at > entered


def test_an_older_position_falls_back_to_its_last_move_into_the_stage(seeded_tenant, sales,
                                                                     stages, ff):
    t = seeded_tenant
    contact = person(t, ff.user)
    pipeline.change_stage(contact, stages["prospecting"])
    ContactPipelinePosition.all_objects.filter(contact=contact).update(
        stage_entered_at=None, last_activity_at=None)
    p = position(contact, sales)
    change = StageChange.all_objects.filter(contact=contact).first()
    assert stage_rules.stay_started(p) == change.created_at
    assert stage_rules.quiet_since(p) == change.created_at


# ---------------------------------------------------------------- actions

def test_a_task_merges_fields_and_goes_to_whom_the_rule_says(seeded_tenant, sales, stages, ff):
    from .factories import CompanyFactory

    t = seeded_tenant
    cf = MembershipFactory(tenant=t, role="CF")
    cf.user.full_name = "Cass Fraser"
    cf.user.save(update_fields=["full_name"])
    company = CompanyFactory(tenant=t, name="Acme")
    contact = person(t, cf.user, first_name="Ada", last_name="Lovelace", company=company)
    rule(t, sales, to_stage=stages["qualified"], task_for=R.For.CONTACT_OWNER,
         task_title_template="Call {FirstName} {LastName} at {Company} ({Stage}, {Pipeline})",
         task_due_offset_days=4)
    rule(t, sales, to_stage=stages["qualified"], task_for=R.For.PRACTICE_OWNER,
         task_title_template="Owner: {FirstName} with {Owner}")
    va = MembershipFactory(tenant=t, role="VA")
    rule(t, sales, to_stage=stages["qualified"], task_for=R.For.MEMBER, task_assignee=va.user,
         task_title_template="Assistant: {FirstName}")
    pipeline.change_stage(contact, stages["qualified"])
    made = {x.title: x for x in tasks_of(contact)}
    first = made["Call Ada Lovelace at Acme (Qualified, Sales)"]
    assert first.owner_id == cf.user_id
    assert first.due_date == (timezone.now() + timedelta(days=4)).date()
    assert made["Owner: Ada with Cass Fraser"].owner_id == ff.user_id
    assert made["Assistant: Ada"].owner_id == va.user_id
    # A contact with no owner: the practice owner. A member who left: the same.
    nobody = person(t, None, first_name="Bo")
    va.revoked_at = timezone.now()
    va.save(update_fields=["revoked_at"])
    pipeline.change_stage(nobody, stages["qualified"])
    owners = {x.title.split(":")[0]: x.owner_id for x in tasks_of(nobody)}
    assert owners["Assistant"] == ff.user_id


def test_a_draft_email_goes_into_the_outbox_for_approval(seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    template = EmailTemplateFactory(tenant=t, subject="Hello {FirstName}", body="Hi {FirstName},")
    rule(t, sales, to_stage=stages["qualified"], action_type=R.Action.DRAFT_EMAIL,
         email_template=template, task_title_template="")
    contact = person(t, ff.user, first_name="Ada")
    pipeline.change_stage(contact, stages["qualified"], actor=ff.user)
    message = OutboxMessage.all_objects.get(to_contact=contact)
    assert message.state == OutboxMessage.State.PENDING_APPROVAL
    assert message.subject == "Hello Ada" and message.producer == "stage_rule"


def test_a_move_runs_the_new_stages_rules_but_not_their_moves(seeded_tenant, sales, stages, ff):
    """The loop guard: A moves to B, B's rule would move back to A."""
    t = seeded_tenant
    a, b = stages["prospecting"], stages["follow_up_needed"]
    rule(t, sales, to_stage=a, action_type=R.Action.MOVE_STAGE, move_to_stage=b,
         task_title_template="")
    rule(t, sales, to_stage=b, action_type=R.Action.MOVE_STAGE, move_to_stage=a,
         task_title_template="")
    rule(t, sales, to_stage=b, task_title_template="Follow up with {FirstName}")
    contact = person(t, ff.user, first_name="Ada")
    pipeline.change_stage(contact, a, actor=ff.user)
    assert position(contact, sales).stage_id == b.pk           # moved once, not back
    assert [x.title for x in tasks_of(contact)] == ["Follow up with Ada"]   # B's task ran
    assert AuditEvent.all_objects.filter(verb="stage_rule.move_held",
                                         target_id=contact.pk).count() == 1
    changes = list(StageChange.all_objects.filter(contact=contact).order_by("created_at"))
    assert [c.to_stage_id for c in changes] == [a.pk, b.pk]
    assert changes[1].reason.startswith("Stage rule: ")


def test_an_idle_rule_may_move_and_the_next_stage_still_runs_without_moves(
        seeded_tenant, sales, stages, ff):
    t = seeded_tenant
    a, b = stages["prospecting"], stages["follow_up_needed"]
    rule(t, sales, trigger=R.Trigger.IDLE, to_stage=a, idle_days=7,
         action_type=R.Action.MOVE_STAGE, move_to_stage=b, task_title_template="")
    rule(t, sales, to_stage=b, action_type=R.Action.MOVE_STAGE, move_to_stage=a,
         task_title_template="")
    contact = person(t, ff.user)
    pipeline.change_stage(contact, a)
    stage_rules.check_idle(t, timezone.now() + timedelta(days=8))
    assert position(contact, sales).stage_id == b.pk


def test_referral_touches_at_a_cadence_for_partners_only(seeded_tenant, referrals,
                                                        referral_stages, types, ff):
    t = seeded_tenant
    rule(t, referrals, to_stage=referral_stages["new_partner"],
         action_type=R.Action.ENROLL_TOUCHES, touch_cadence="quarterly", task_title_template="")
    partner = person(t, ff.user)
    ContactTypeLinkFactory(tenant=t, contact=partner, contact_type=types["referral_partner"])
    stranger = person(t, ff.user)
    pipeline.change_stage(partner, referral_stages["new_partner"], actor=ff.user)
    pipeline.change_stage(stranger, referral_stages["new_partner"], actor=ff.user)
    partner.refresh_from_db()
    assert Enrollment.all_objects.filter(contact=partner, ended_at__isnull=True).count() == 1
    assert partner.referral_cadence == "quarterly"
    assert not Enrollment.all_objects.filter(contact=stranger).exists()
    assert AuditEvent.all_objects.filter(verb="stage_rule.enrolment_skipped",
                                         target_id=stranger.pk).exists()


def test_a_notice_is_on_home_and_in_one_email_a_day(seeded_tenant, sales, stages, ff, api):
    t = seeded_tenant
    rule(t, sales, trigger=R.Trigger.IDLE, to_stage=stages["decision_making"], idle_days=10,
         action_type=R.Action.NOTIFY, task_for=R.For.PRACTICE_OWNER, task_title_template="",
         notice_text="{FirstName} has been in {Stage} {DaysInStage} days")
    a, b = person(t, None, first_name="Ada"), person(t, None, first_name="Bo")
    pipeline.change_stage(a, stages["decision_making"])
    pipeline.change_stage(b, stages["decision_making"])
    assert stage_rules.check_idle(t, timezone.now() + timedelta(days=11)) == 2
    listed = api.as_(ff).get("/api/pipeline-notices/").json()
    assert sorted(n["text"].split(" has")[0] for n in listed) == ["Ada", "Bo"]
    assert all(" in Decision Making " in n["text"] for n in listed)
    # One email for both; none the next day with nothing new.
    assert stage_rules.send_notice_emails(t) == 1
    mail = OutboxMessage.all_objects.get(producer=OutboxMessage.Producer.PIPELINE_NOTICES)
    assert mail.to_address == ff.user.email and "Ada" in mail.body_text and "Bo" in mail.body_text
    assert stage_rules.send_notice_emails(t) == 0
    # Dismissed, it leaves Home; another person never sees it.
    cf = MembershipFactory(tenant=t, role="CF")
    assert api.as_(cf).get("/api/pipeline-notices/").json() == []
    first = listed[0]["id"]
    assert api.as_(cf).post(f"/api/pipeline-notices/{first}/dismiss/").status_code == 404
    assert api.as_(ff).post(f"/api/pipeline-notices/{first}/dismiss/").status_code == 200
    assert len(api.as_(ff).get("/api/pipeline-notices/").json()) == 1


# ---------------------------------------------------------------- the API

def test_rules_are_checked_in_words(seeded_tenant, sales, referrals, stages, referral_stages,
                                    ff, api):
    client = api.as_(ff)
    base = {"pipeline": str(sales.pk), "action_type": "create_task",
            "task_title_template": "Call"}
    url = "/api/stage-automations/"
    assert post(client, url, {**base, "trigger": "idle", "to_stage": str(stages["prospecting"].pk)}
                ).json()["idle_days"]
    assert "Choose the stage" in str(post(client, url, {**base, "trigger": "enters"}).json())
    assert "another pipeline" in str(post(client, url, {
        **base, "to_stage": str(referral_stages["new_partner"].pk)}).json())
    assert "no merge field called {Nickname}" in str(post(client, url, {
        **base, "to_stage": str(stages["qualified"].pk), "task_title_template": "Hi {Nickname}"}
    ).json())
    assert "where to move" in str(post(client, url, {
        **base, "to_stage": str(stages["qualified"].pk), "action_type": "move_stage"}).json())
    ok = post(client, url, {**base, "trigger": "won", "task_title_template": "Kick off {Company}"})
    assert ok.status_code == 201, ok.content
    assert ok.json()["to_stage"] is None and ok.json()["task_client_visible"] is True
    assert ok.json()["summary"].startswith("When a contact is won in Sales, create task")
    outsider = MembershipFactory(tenant=TenantFactory(), role="CF")
    assert "team" in str(post(client, url, {
        **base, "to_stage": str(stages["qualified"].pk), "task_for": "member",
        "task_assignee": str(outsider.user_id)}).json())


def test_starter_examples_are_one_click_and_found_by_stage_code(seeded_tenant, sales, referrals,
                                                               stages, ff, api):
    client = api.as_(ff)
    offered = client.get(f"/api/stage-automations/examples/?pipeline={sales.pk}").json()
    keys = [e["key"] for e in offered]
    assert "first_call" in keys and "won_kickoff" in keys and not any(e["added"] for e in offered)
    made = post(client, "/api/stage-automations/examples/", {"pipeline": str(sales.pk),
                                                            "key": "prospecting_quiet"})
    assert made.status_code == 201
    assert made.json()["summary"].startswith(
        "When a contact has sat in Prospecting 14 days with no activity in Sales, move them to "
        "Follow Up Needed")
    again = client.get(f"/api/stage-automations/examples/?pipeline={sales.pk}").json()
    assert next(e for e in again if e["key"] == "prospecting_quiet")["added"] is True
    # Renamed stages keep their examples; a removed one takes its examples with it.
    stages["prospecting"].label = "Working it"
    stages["prospecting"].save(update_fields=["label"])
    PipelineStage.all_objects.filter(pk=stages["proposal_given"].pk).delete()
    keys = [e["key"] for e in client.get(
        f"/api/stage-automations/examples/?pipeline={sales.pk}").json()]
    assert "prospecting_quiet" in keys and "proposal_follow_up" not in keys
    partner = client.get(f"/api/stage-automations/examples/?pipeline={referrals.pk}").json()
    assert {e["key"] for e in partner} == {"partner_touches", "active_referrer", "nurturing_quiet"}
    assert post(client, "/api/stage-automations/examples/", {"pipeline": str(sales.pk),
                                                            "key": "partner_touches"}
                ).status_code == 400


def test_stage_cards_rename_reorder_add_and_remove(seeded_tenant, sales, stages, ff, api):
    client = api.as_(ff)
    added = post(client, "/api/pipeline-stages/", {"pipeline": str(sales.pk),
                                                   "label": "Discovery call booked",
                                                   "semantic": "working"})
    assert added.status_code == 201, added.content
    assert added.json()["code"] == "discovery_call_booked"
    assert added.json()["position"] == max(s.position for s in stages.values()) + 1
    renamed = client.patch(f"/api/pipeline-stages/{added.json()['id']}/",
                           json.dumps({"label": "Discovery booked"}),
                           content_type="application/json")
    assert renamed.status_code == 200
    ids = [str(s.pk) for s in sorted(stages.values(), key=lambda s: s.position)]
    ids.insert(1, added.json()["id"])
    reordered = post(client, "/api/pipeline-stages/order/", {"pipeline": str(sales.pk), "ids": ids})
    assert reordered.status_code == 200 and [s["id"] for s in reordered.json()] == ids
    assert post(client, "/api/pipeline-stages/order/", {"pipeline": str(sales.pk),
                                                        "ids": ids[:-1]}).status_code == 400
    # A stage holding contacts can't go; an empty one goes with its rules.
    holder = person(seeded_tenant, ff.user)
    pipeline.change_stage(holder, stages["qualified"])
    refused = client.delete(f"/api/pipeline-stages/{stages['qualified'].pk}/")
    assert refused.status_code == 400 and "Move them" in str(refused.json())
    rule(seeded_tenant, sales, to_stage=PipelineStage.all_objects.get(pk=added.json()["id"]))
    assert client.delete(f"/api/pipeline-stages/{added.json()['id']}/").status_code == 204
    assert not StageAutomation.all_objects.filter(to_stage_id=added.json()["id"]).exists()


def test_only_the_practice_owner_sets_rules_and_stages(seeded_tenant, sales, stages, api):
    url = "/api/stage-automations/"
    body = {"pipeline": str(sales.pk), "to_stage": str(stages["qualified"].pk),
            "action_type": "create_task", "task_title_template": "x"}
    for role in ("CF", "VA"):
        m = MembershipFactory(tenant=seeded_tenant, role=role)
        client = api.as_(m)
        assert post(client, url, body).status_code == 403
        assert post(client, f"{url}examples/", {"pipeline": str(sales.pk),
                                                "key": "first_call"}).status_code == 403
        assert post(client, "/api/pipeline-stages/order/", {"pipeline": str(sales.pk),
                                                            "ids": []}).status_code == 403


def test_another_practices_rules_stages_and_notices_are_out_of_reach(seeded_tenant, sales,
                                                                    stages, ff, api):
    from apps.crm.seed import seed_tenant

    other = TenantFactory()
    seed_tenant(other)
    b_ff = MembershipFactory(tenant=other, role="FF")
    b = api.as_(b_ff)
    a_rule = rule(seeded_tenant, sales, to_stage=stages["qualified"])
    assert b.get(f"/api/stage-automations/?pipeline={sales.pk}").json() == []
    assert b.get(f"/api/stage-automations/{a_rule.pk}/").status_code == 404
    assert post(b, "/api/stage-automations/examples/", {"pipeline": str(sales.pk),
                                                        "key": "first_call"}).status_code == 400
    assert post(b, "/api/pipeline-stages/order/", {"pipeline": str(sales.pk),
                                                   "ids": [str(stages["qualified"].pk)]}
                ).status_code == 400
    notice = PipelineNotice.all_objects.create(tenant=seeded_tenant, recipient=ff.user, text="A's")
    assert b.get("/api/pipeline-notices/").json() == []
    assert post(b, f"/api/pipeline-notices/{notice.pk}/dismiss/", {}).status_code == 404
    # The daily job reads one practice's rules only.
    contact = person(seeded_tenant, ff.user)
    pipeline.change_stage(contact, stages["qualified"])
    rule(seeded_tenant, sales, trigger=R.Trigger.IDLE, to_stage=stages["qualified"], idle_days=1)
    assert stage_rules.check_idle(other, timezone.now() + timedelta(days=3)) == 0
    assert stage_rules.check_idle(seeded_tenant, timezone.now() + timedelta(days=3)) == 1


def test_the_daily_job_is_scheduled():
    from apps.tenancy.management.commands.ensure_schedules import SCHEDULES

    assert ("crm.stage_rules_daily", "apps.crm.tasks.stage_rules_daily") in {
        (name, func) for name, func, *_ in SCHEDULES}
