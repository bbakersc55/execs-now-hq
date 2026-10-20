"""A promise is a mark on a task, not a second list (owner, 2026-10-20).

The prompt asks for each thing once, a promise flagged on its action item. A
task line ticked "Promised to <company>" makes the task and a commitment of
ours, owed to the client, done when the task is. Proposals read before the
change fold a deliverable that repeats an action item into it before they are
shown. Every prompt where Claude drafts words for a person asks for American
spelling.
"""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Task
from apps.meetings.models import Commitment, MeetingProposal, ProposalItem

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, MeetingFactory, MeetingProposalFactory,
    MeetingSourceFileFactory, ProposalItemFactory,
)


def _approve(api, member, item, **choice):
    return api.as_(member).post(f"/api/proposal-items/{item.pk}/approve/", choice,
                                content_type="application/json")


@pytest.fixture
def acme_meeting(seeded_tenant, in_tenant_a):
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    meeting = MeetingFactory(tenant=seeded_tenant, client_company=acme)
    proposal = MeetingProposalFactory(tenant=seeded_tenant, meeting=meeting)
    return acme, proposal


# ------------------------------------------------------------------ the prompt

@pytest.mark.django_db
def test_the_prompt_asks_for_each_thing_once_with_the_promise_flagged(
        seeded_tenant, fake_claude, in_tenant_a):
    from apps.meetings import parsing

    assert '"deliverables"' not in parsing.SYSTEM
    assert '"promised_to_client"' in parsing.SYSTEM
    assert "Each thing appears once" in parsing.SYSTEM
    fake_claude.reply = json.dumps({
        "title": "Acme review", "meeting_date": None, "summary": "x", "participants": [],
        "action_items": [
            {"text": "Send the SOP draft", "owner": "", "owner_side": "practice",
             "promised_to_client": True, "due_date": None,
             "excerpt": "We will send Acme the SOP draft."},
            {"text": "Book the site visit", "owner": "", "owner_side": "practice",
             "promised_to_client": False, "due_date": None, "excerpt": "Book a visit."}]})
    proposal = parsing.parse(MeetingSourceFileFactory(tenant=seeded_tenant, text="notes"))
    rows = list(ProposalItem.objects.filter(proposal=proposal).order_by("position"))
    assert [(r.kind, r.payload["promised_to_client"]) for r in rows] == [
        ("action_item", True), ("action_item", False)]
    assert "Use American spelling." in fake_claude.requests[-1]["system"]


@pytest.mark.django_db
def test_a_deliverables_list_sent_anyway_folds_or_becomes_a_promised_item(
        seeded_tenant, fake_claude, in_tenant_a):
    from apps.meetings import parsing

    fake_claude.reply = json.dumps({
        "title": "Acme review", "meeting_date": None, "summary": "x", "participants": [],
        "action_items": [
            {"text": "Send Acme the SOP draft", "owner": "", "owner_side": "practice",
             "due_date": None, "excerpt": "We will send Acme the SOP draft."}],
        "deliverables": [
            {"text": "The SOP draft", "owner": "", "due_date": "2026-10-30",
             "excerpt": "Acme is waiting on the SOP draft."},
            {"text": "Rebuild the inspection checklist", "owner": "", "due_date": None,
             "excerpt": "We promised the checklist."}]})
    proposal = parsing.parse(MeetingSourceFileFactory(tenant=seeded_tenant, text="notes"))
    rows = list(ProposalItem.objects.filter(proposal=proposal).order_by("position"))
    assert {r.kind for r in rows} == {"action_item"}
    assert [(r.payload["text"], r.payload["promised_to_client"],
             r.payload["proposed_due_date"]) for r in rows] == [
        ("Send Acme the SOP draft", True, "2026-10-30"),
        ("Rebuild the inspection checklist", True, None)]


# ------------------------------------------------------------------- the fold

@pytest.mark.django_db
def test_an_older_proposal_folds_its_repeated_line_before_it_is_shown(
        seeded_tenant, ff, api, acme_meeting):
    _acme, proposal = acme_meeting
    action = ProposalItemFactory(tenant=seeded_tenant, proposal=proposal, payload={
        "text": "Send the SOP draft to Acme", "owner_side": "practice"},
        source_excerpt="We will send the SOP draft.")
    ProposalItemFactory(tenant=seeded_tenant, proposal=proposal,
                        kind=ProposalItem.Kind.DELIVERABLE,
                        payload={"text": "SOP draft", "proposed_due_date": "2026-10-30"},
                        source_excerpt="Acme waits on the SOP draft.")
    other = ProposalItemFactory(tenant=seeded_tenant, proposal=proposal,
                                kind=ProposalItem.Kind.DELIVERABLE,
                                payload={"text": "Rebuild the inspection checklist"},
                                source_excerpt="We promised the checklist.")

    shown = api.as_(ff).get(f"/api/meeting-proposals/{proposal.pk}/").json()
    assert sorted((i["kind"], i["payload"]["text"]) for i in shown["items"]) == [
        ("action_item", "Send the SOP draft to Acme"),
        ("deliverable", "Rebuild the inspection checklist")]
    action.refresh_from_db()
    assert action.payload["promised_to_client"] is True
    assert action.payload["proposed_due_date"] == "2026-10-30"
    # The line that says something else keeps its shape, and a second look
    # folds nothing more.
    assert ProposalItem.objects.filter(pk=other.pk).exists()
    api.as_(ff).get(f"/api/meeting-proposals/{proposal.pk}/")
    assert ProposalItem.objects.filter(proposal=proposal).count() == 2
    # The queue's list folds too.
    assert api.as_(ff).get("/api/meeting-proposals/").status_code == 200


@pytest.mark.django_db
def test_decided_lines_are_never_folded(seeded_tenant, ff, api, acme_meeting):
    _acme, proposal = acme_meeting
    ProposalItemFactory(tenant=seeded_tenant, proposal=proposal,
                        state=ProposalItem.State.APPROVED,
                        payload={"text": "Send the SOP draft"})
    ProposalItemFactory(tenant=seeded_tenant, proposal=proposal,
                        kind=ProposalItem.Kind.DELIVERABLE, payload={"text": "SOP draft"})
    api.as_(ff).get(f"/api/meeting-proposals/{proposal.pk}/")
    assert ProposalItem.objects.filter(proposal=proposal).count() == 2


# ------------------------------------------------------------ the commitment

@pytest.mark.django_db
def test_promised_makes_the_task_and_our_commitment_to_the_client(
        seeded_tenant, ff, api, acme_meeting):
    acme, proposal = acme_meeting
    item = ProposalItemFactory(tenant=seeded_tenant, proposal=proposal, payload={
        "text": "Send the SOP draft", "owner_side": "practice",
        "promised_to_client": True, "proposed_due_date": "2026-10-30"})
    shown = api.as_(ff).get(f"/api/proposal-items/?proposal={proposal.pk}").json()
    assert shown[0]["promised_to"] == {"id": str(acme.pk), "name": "Acme Facilities"}

    response = _approve(api, ff, item, owner_side="practice", promised=True)
    assert response.status_code == 201, response.json()
    task = Task.objects.get()
    assert task.client_company_id == acme.pk
    c = Commitment.objects.get()
    assert (c.side, c.outcome, c.task_id, c.company_id, c.text, str(c.due_date)) == (
        "ours", "promised", task.pk, acme.pk, "Send the SOP draft", "2026-10-30")

    client = api.as_(ff)
    # Not on "Waiting on others", nor in its dashboard count: it is ours.
    assert client.get("/api/commitments/").json() == []
    ours = client.get(f"/api/commitments/?company={acme.pk}&side=ours&state=all").json()
    assert [(r["side"], r["outcome_label"], r["task"]) for r in ours] == [
        ("ours", "Our task", str(task.pk))]

    # Done when the task is.
    task.status = "done"
    task.save(update_fields=["status"])
    done = client.get(f"/api/commitments/?company={acme.pk}&side=ours&state=all").json()
    assert done[0]["state"] == "done"


@pytest.mark.django_db
def test_unticked_is_a_task_only(seeded_tenant, ff, api, acme_meeting):
    _acme, proposal = acme_meeting
    item = ProposalItemFactory(tenant=seeded_tenant, proposal=proposal, payload={
        "text": "Send the SOP draft", "owner_side": "practice", "promised_to_client": True})
    assert _approve(api, ff, item, owner_side="practice", promised=False).status_code == 201
    assert Task.objects.count() == 1 and Commitment.objects.count() == 0


@pytest.mark.django_db
def test_the_client_company_comes_from_the_participants_before_a_meeting_exists(
        seeded_tenant, ff, api, in_tenant_a):
    from apps.meetings import approval

    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    proposal = MeetingProposalFactory(tenant=seeded_tenant)
    ProposalItemFactory(tenant=seeded_tenant, proposal=proposal,
                        kind=ProposalItem.Kind.PARTICIPANT, payload={
                            "parsed_name": "Dana Reyes",
                            "company_candidates": [{"company_id": str(acme.pk)}]})
    assert approval.promise_company(proposal) == acme
    assert approval.promise_company(MeetingProposalFactory(tenant=seeded_tenant)) is None


@pytest.mark.django_db
def test_our_commitments_stay_in_the_practice(
        seeded_tenant, ff, fcc, api, tenant_b, acme_meeting):
    from apps.tenancy.context import tenant_context

    acme, proposal = acme_meeting
    item = ProposalItemFactory(tenant=seeded_tenant, proposal=proposal, payload={
        "text": "Send the SOP draft", "owner_side": "practice"})
    assert _approve(api, ff, item, owner_side="practice", promised=True).status_code == 201
    # A client user is refused the commitments list outright.
    assert api.as_(fcc).get("/api/commitments/?side=all").status_code == 403
    with tenant_context(tenant_b):
        assert Commitment.objects.count() == 0
    assert MeetingProposal.objects.filter(pk=proposal.pk).exists()


# ------------------------------------------------------------ American spelling

def test_every_drafting_prompt_asks_for_american_spelling():
    """Each call where Claude writes words a person reads goes through
    `claude.drafting`, which appends the line; extraction and labelling do not
    need it."""
    from pathlib import Path

    from apps.tenancy import claude

    assert claude.drafting("Write.").endswith("Use American spelling.")
    root = Path(__file__).resolve().parent.parent / "apps"
    drafting = ["notes/summary.py", "work/narratives.py", "work/digests.py",
                "finance/explain.py", "finance/forecast_ai.py", "strategy/prep.py",
                "strategy/diagnostic.py", "strategy/document.py", "strategy/ai.py",
                "strategy/v3.py", "personal/budget_ai.py", "personal/forecast_ai.py",
                "personal/sort_ai.py"]
    for name in drafting:
        assert "claude.drafting(" in (root / name).read_text(), name
