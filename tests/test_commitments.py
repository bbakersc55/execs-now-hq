"""Other people's action items (owner, 2026-09-28).

An action item owned by the practice is a task, as before. One owned by
someone else is a commitment: follow up (a check task for the practice),
record only (no task for anyone), or — only for a client user with a real
portal seat — their task in the portal, waiting on the client.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import Task
from apps.meetings import ownership
from apps.meetings.models import Commitment, MeetingProposal, ProposalItem
from apps.work.models import Stakeholder

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactFactory, ContactTypeLinkFactory, MeetingProposalFactory,
    MembershipFactory, ProposalItemFactory,
)


@pytest.fixture
def people(seeded_tenant, ff, in_tenant_a):
    """The FF (named, with a contact row), a client user with a seat, a
    client contact without one, a prospect, a vendor."""
    from apps.crm.models import ContactType

    ff.user.full_name = "Bryan Baker"
    ff.user.save(update_fields=["full_name"])
    ff.contact = ContactFactory(tenant=seeded_tenant, first_name="Bryan", last_name="Baker")
    ff.save(update_fields=["contact"])
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme")
    seated = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                            company=acme)
    seat = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=acme,
                             contact=seated)
    unseated = ContactFactory(tenant=seeded_tenant, first_name="Priya", last_name="Shah",
                              company=acme)
    prospect = ContactFactory(tenant=seeded_tenant, first_name="Tom", last_name="Okafor")
    vendor = ContactFactory(tenant=seeded_tenant, first_name="Vic", last_name="Vendor")
    for contact, code in ((prospect, "prospect"), (vendor, "vendor")):
        ContactTypeLinkFactory(tenant=seeded_tenant, contact=contact,
                               contact_type=ContactType.objects.get(code=code))
    return {"acme": acme, "seated": seated, "seat": seat, "unseated": unseated,
            "prospect": prospect, "vendor": vendor}


def classify(tenant, text, contact=None, **hints):
    return ownership.classify(tenant, owner_text=text,
                              owner_contact_id=contact.pk if contact else None, **hints)


# ------------------------------------------------------------ classification

@pytest.mark.django_db
def test_classification(seeded_tenant, people):
    t = seeded_tenant
    # A staff name is the practice, whatever Claude said.
    assert classify(t, "Bryan Baker", claude_side="other")["owner_side"] == "practice"
    seated = classify(t, "Dana Reyes", people["seated"], claude_side="other",
                      claude_kind="prospect")
    assert (seated["owner_side"], seated["owner_kind"], seated["owner_has_seat"],
            seated["proposed_outcome"]) == ("other", "client", True, "portal")
    assert classify(t, "Priya Shah", people["unseated"])["proposed_outcome"] == "record_only"
    assert classify(t, "Tom Okafor", people["prospect"])["proposed_outcome"] == "follow_up"
    assert classify(t, "Vic Vendor", people["vendor"])["proposed_outcome"] == "record_only"
    stranger = classify(t, "Lee from the bank", claude_side="other", claude_kind="third_party")
    assert (stranger["owner_kind"], stranger["proposed_outcome"]) == ("third_party", "follow_up")
    assert classify(t, "")["owner_side"] == ""


@pytest.mark.django_db
def test_a_fresh_parse_carries_the_classification(seeded_tenant, people, fake_claude):
    from apps.meetings import parsing
    from .factories import MeetingSourceFileFactory

    fake_claude.reply = json.dumps({
        "title": "Acme review", "meeting_date": "2026-09-28", "summary": "x",
        "participants": [],
        "action_items": [
            {"text": "Send the agenda", "owner": "Bryan Baker", "owner_side": "practice",
             "due_date": None, "excerpt": "Bryan will send the agenda."},
            {"text": "Send the Q3 numbers", "owner": "Dana Reyes", "owner_side": "other",
             "owner_kind": "client", "due_date": "2026-10-03",
             "excerpt": "Dana will send the Q3 numbers by Friday."}],
        "deliverables": []})
    source = MeetingSourceFileFactory(tenant=seeded_tenant, text="notes")
    proposal = parsing.parse(source)
    ours, theirs = ProposalItem.objects.filter(proposal=proposal).order_by("position")
    assert ours.payload["owner_side"] == "practice"
    assert (theirs.payload["owner_side"], theirs.payload["proposed_outcome"]) == \
        ("other", "portal")
    assert "Dana will send" in theirs.source_excerpt


# -------------------------------------------------------------- the outcomes

def _item(tenant, contact, name, **payload):
    return ProposalItemFactory(tenant=tenant, payload={
        "text": "Send the Q3 numbers", "proposed_owner_text": name,
        "proposed_owner_contact_id": str(contact.pk) if contact else None,
        "proposed_due_date": payload.pop("due", None), **payload})


def _approve(api, member, item, **choice):
    return api.as_(member).post(f"/api/proposal-items/{item.pk}/approve/", choice,
                                content_type="application/json")


@pytest.mark.django_db
def test_follow_up_makes_our_check_task_linked_to_the_person(seeded_tenant, ff, api, people):
    item = _item(seeded_tenant, people["prospect"], "Tom Okafor", due="2026-10-03")
    response = _approve(api, ff, item, owner_side="other", outcome="follow_up")

    assert response.status_code == 201, response.json()
    c = Commitment.objects.get()
    assert (c.outcome, c.state, c.contact_id, str(c.follow_up_date)) == \
        ("follow_up", "open", people["prospect"].pk, "2026-10-03")
    assert c.task.title == "Check that Tom Okafor send the Q3 numbers"
    assert c.task.contact_id == people["prospect"].pk and not c.task.is_client_visible
    assert c.source_excerpt.startswith("Dana said")


@pytest.mark.django_db
def test_follow_up_without_a_date_is_a_week_out(seeded_tenant, ff, api, people):
    item = _item(seeded_tenant, None, "Lee from the bank")
    _approve(api, ff, item, owner_side="other", outcome="follow_up")
    c = Commitment.objects.get()
    assert c.follow_up_date == timezone.localdate() + timedelta(days=7)
    assert c.owner_name == "Lee from the bank" and c.contact is None


@pytest.mark.django_db
def test_record_only_creates_no_task_for_anyone(seeded_tenant, ff, api, people):
    tasks = Task.objects.count()
    item = _item(seeded_tenant, people["vendor"], "Vic Vendor", due="2026-10-10")
    assert _approve(api, ff, item, owner_side="other", outcome="record_only").status_code == 201
    c = Commitment.objects.get()
    assert (c.outcome, c.task) == ("record_only", None)
    assert Task.objects.count() == tasks
    item.refresh_from_db()
    assert (item.state, item.created_record_type) == ("approved", "commitment")


@pytest.mark.django_db
def test_assign_in_the_portal_makes_it_theirs_and_waiting_on_client(
    seeded_tenant, ff, api, people
):
    item = _item(seeded_tenant, people["seated"], "Dana Reyes", due="2026-10-03")
    response = _approve(api, ff, item, owner_side="other", outcome="portal", notify_me=True)

    assert response.status_code == 201, response.json()
    task = Commitment.objects.get().task
    assert task.assignee_id == people["seat"].user_id
    assert task.client_company_id == people["acme"].pk and task.is_client_visible
    assert task.status == Task.Status.WAITING_ON_CLIENT
    me = Stakeholder.objects.get(task=task)
    assert (me.contact_id, me.cadence) == (ff.contact_id, "every_update")


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["unseated", "prospect"])
def test_the_portal_needs_a_real_seat(seeded_tenant, ff, api, people, who):
    tasks = Task.objects.count()
    item = _item(seeded_tenant, people[who], "Someone")
    response = _approve(api, ff, item, owner_side="other", outcome="portal")
    assert response.status_code == 400 and "no portal seat" in response.json()["detail"]
    assert not Commitment.objects.exists() and Task.objects.count() == tasks


@pytest.mark.django_db
def test_a_revoked_seat_is_no_seat(seeded_tenant, ff, api, people):
    people["seat"].revoked_at = timezone.now()
    people["seat"].save(update_fields=["revoked_at"])
    assert ownership.seat_for(people["seated"]) is None


@pytest.mark.django_db
def test_the_practices_own_item_is_still_a_task(seeded_tenant, ff, api, people):
    item = _item(seeded_tenant, None, "Bryan Baker", owner_side="practice")
    assert _approve(api, ff, item).status_code == 201
    assert not Commitment.objects.exists()
    assert Task.objects.filter(title="Send the Q3 numbers").exists()


# --------------------------------------------------------- waiting on others

@pytest.mark.django_db
def test_waiting_on_others_lists_marks_done_and_snoozes(seeded_tenant, ff, api, people):
    _approve(api, ff, _item(seeded_tenant, people["prospect"], "Tom Okafor",
                            due=str(timezone.localdate() - timedelta(days=2))),
             owner_side="other", outcome="follow_up")
    client = api.as_(ff)
    [row] = client.get("/api/commitments/?overdue=1").json()
    assert row["overdue"] and row["owner_name"] == "Tom Okafor"
    assert api.as_(ff).get("/api/dashboard/").json()["waiting"] == {"open": 1, "overdue": 1}

    snoozed = client.post(f"/api/commitments/{row['id']}/snooze/", {"days": 7}).json()
    assert snoozed["follow_up_date"] == str(timezone.localdate() + timedelta(days=7))
    c = Commitment.objects.get()
    assert c.task.due_date == c.follow_up_date           # the check task moves with it
    assert client.get("/api/commitments/?overdue=1").json() == []

    client.post(f"/api/commitments/{row['id']}/done/")
    c.refresh_from_db(); c.task.refresh_from_db()
    assert c.state == "done" and c.task.status == "done"
    assert client.get("/api/commitments/").json() == []


@pytest.mark.django_db
def test_a_portal_commitment_is_done_when_the_client_finishes_it(seeded_tenant, ff, api,
                                                                 people):
    _approve(api, ff, _item(seeded_tenant, people["seated"], "Dana Reyes"),
             owner_side="other", outcome="portal")
    Task.objects.filter(pk=Commitment.objects.get().task_id).update(status="done")
    assert api.as_(ff).get("/api/commitments/").json() == []
    assert Commitment.objects.get().state == "done"


@pytest.mark.django_db
def test_commitments_show_on_the_contacts_page_and_to_the_va(seeded_tenant, ff, va, api,
                                                             people):
    _approve(api, ff, _item(seeded_tenant, people["vendor"], "Vic Vendor"),
             owner_side="other", outcome="record_only")
    rows = api.as_(va).get(f"/api/commitments/?contact={people['vendor'].pk}&state=all").json()
    assert [r["owner_name"] for r in rows] == ["Vic Vendor"]


@pytest.mark.django_db
def test_a_client_never_sees_waiting_on_others(seeded_tenant, fcc, api):
    assert api.as_(fcc).get("/api/commitments/").status_code == 403


# ------------------------------------------------------------ the queue, again

@pytest.mark.django_db
def test_reclassifying_touches_only_unreviewed_items(seeded_tenant, ff, people, fake_claude):
    pending = MeetingProposalFactory(tenant=seeded_tenant)
    done = MeetingProposalFactory(tenant=seeded_tenant, state=MeetingProposal.State.ACTIONED)
    waiting = ProposalItemFactory(tenant=seeded_tenant, proposal=pending, payload={
        "text": "Send numbers", "proposed_owner_text": "Lee from the bank"})
    reviewed = ProposalItemFactory(tenant=seeded_tenant, proposal=done, payload={
        "text": "x", "proposed_owner_text": "Lee"})

    plan = ownership.plan_reclassification()
    assert (plan["proposals"], plan["items"]) == (1, 1)
    assert fake_claude.requests == []                    # a plan calls nothing

    fake_claude.reply = json.dumps([{"item": 1, "owner_side": "other",
                                     "owner_kind": "third_party"}])
    result = ownership.reclassify(seeded_tenant, use_claude=True)
    assert result["claude_calls"] == 1
    waiting.refresh_from_db(); reviewed.refresh_from_db()
    assert waiting.payload["owner_side"] == "other"
    assert waiting.payload["proposed_outcome"] == "follow_up"
    assert "owner_side" not in reviewed.payload


@pytest.mark.django_db
def test_reclassifying_without_claude_is_free(seeded_tenant, ff, people, fake_claude):
    item = ProposalItemFactory(tenant=seeded_tenant, payload={
        "text": "Send the agenda", "proposed_owner_text": "Bryan Baker"})
    ownership.reclassify(seeded_tenant, use_claude=False)
    item.refresh_from_db()
    assert item.payload["owner_side"] == "practice" and fake_claude.requests == []



@pytest.mark.django_db
def test_one_failed_call_does_not_stop_the_run(seeded_tenant, ff, people, fake_claude,
                                                monkeypatch):
    from apps.tenancy import claude

    first = ProposalItemFactory(tenant=seeded_tenant, payload={
        "text": "a", "proposed_owner_text": "Lee"})
    second = ProposalItemFactory(tenant=seeded_tenant, payload={
        "text": "b", "proposed_owner_text": "Sam"})
    real, seen = claude.complete_with_call, []

    def flaky(**kwargs):
        seen.append(kwargs["target_id"])
        if len(seen) == 1:
            raise claude.ClaudeUnavailable("cut off")
        return real(**kwargs)
    monkeypatch.setattr(claude, "complete_with_call", flaky)
    fake_claude.reply = json.dumps([{"item": 1, "owner_side": "other",
                                     "owner_kind": "vendor"}])

    result = ownership.reclassify(seeded_tenant, use_claude=True)

    assert result["claude_calls"] == 2 and len(result["failed"]) == 1
    classified = [i for i in (first, second) if (i.refresh_from_db() or True)
                  and "owner_side" in i.payload]
    assert len(classified) == 1
    assert ownership.plan_reclassification()["items"] == 1     # the failed one is left
