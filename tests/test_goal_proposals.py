"""Goals a client owner proposes (owner, 2026-10-07).

A client still never creates a goal. A **client owner** may propose one; it
waits in the practice's review, and only the practice owner or an assigned
associate makes it a goal or declines it. Nothing is created until then.
"""

from __future__ import annotations

import json

import pytest

from apps.tenancy.models import AuditEvent
from apps.work.models import Goal, GoalProposal

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)

URL = "/api/goal-proposals/"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def a_client(tenant, company, role="FCC", first="Dana"):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address=f"{first.lower()}@{company.pk}.invalid")
    return MembershipFactory(tenant=tenant, role=role, client_company=company,
                             contact=contact)


@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=3)


@pytest.fixture
def dana(seeded_tenant, company):
    return a_client(seeded_tenant, company, "FCC")


@pytest.fixture
def proposed(dana, api, in_tenant_a):
    made = post(api.as_(dana), URL, {"title": "Stop losing drivers in their first month",
                                     "why": "We hired nine and kept four."})
    assert made.status_code == 201, made.content
    return made.json()


def titles_on_report(client, company=None):
    query = f"?client_company={company.pk}" if company is not None else ""
    body = client.get(f"/api/value-report/{query}").json()
    return [b["title"] for b in body["current"] + body["historical"]]


# ----------------------------------------------------------------- proposing

@pytest.mark.django_db
def test_a_client_owner_proposes_a_goal_and_no_goal_is_created(
    proposed, dana, ff, api, company, in_tenant_a
):
    assert proposed["state"] == "pending" and proposed["goal"] is None
    assert proposed["title"] == "Stop losing drivers in their first month"
    assert proposed["why"] == "We hired nine and kept four."
    assert proposed["proposed_by"] == (dana.user.full_name or dana.user.email)

    assert not Goal.all_objects.exists(), "A proposal created a goal."
    assert titles_on_report(api.as_(dana)) == []
    assert titles_on_report(api.as_(ff), company) == []

    event = AuditEvent.all_objects.get(verb="goal.proposed")
    assert event.actor_id == dana.user_id and str(event.target_id) == str(company.pk)
    assert event.payload["title"] == "Stop losing drivers in their first month"


@pytest.mark.django_db
def test_it_lands_in_the_practices_review(proposed, ff, va, api, company, in_tenant_a):
    for member in (ff, va):
        waiting = api.as_(member).get(f"{URL}pending/").json()
        assert [(p["id"], p["company_name"], p["title"]) for p in waiting] == [
            (proposed["id"], "Northwind Foods", "Stop losing drivers in their first month")]
    page = api.as_(ff).get(f"{URL}?client_company={company.pk}").json()
    assert page["may_decide"] is True and page["may_propose"] is False
    assert [p["id"] for p in page["proposals"]] == [proposed["id"]]


@pytest.mark.django_db
def test_the_client_owner_sees_their_proposal_waiting(proposed, dana, api, in_tenant_a):
    page = api.as_(dana).get(URL).json()
    assert page["may_propose"] is True and page["may_decide"] is False
    assert [(p["title"], p["state"]) for p in page["proposals"]] == [
        ("Stop losing drivers in their first month", "pending")]


@pytest.mark.django_db
@pytest.mark.parametrize("body,why", [
    ({}, "Say what the goal is"),
    ({"title": "   "}, "Say what the goal is"),
    ({"title": 7}, "Say what the goal is"),
    ({"title": "x" * 256}, "at most 255"),
])
def test_a_proposal_needs_a_title(body, why, dana, api, in_tenant_a):
    refused = post(api.as_(dana), URL, body)
    assert refused.status_code == 400 and why in refused.json()["detail"]
    assert not GoalProposal.all_objects.exists()


@pytest.mark.django_db
def test_the_queue_has_an_end(dana, api, in_tenant_a):
    for n in range(10):
        assert post(api.as_(dana), URL, {"title": f"Goal {n}"}).status_code == 201
    refused = post(api.as_(dana), URL, {"title": "One more"})
    assert refused.status_code == 400 and "already waiting" in refused.json()["detail"]
    assert GoalProposal.all_objects.count() == 10


# ----------------------------------------------------------------- who may

@pytest.mark.django_db
def test_a_client_team_member_reads_the_proposals_and_cannot_make_one(
    proposed, seeded_tenant, company, api, in_tenant_a
):
    """"Client owners" is the rule: proposing strategy is the founder's."""
    member = a_client(seeded_tenant, company, "ECC", first="Priya")
    refused = post(api.as_(member), URL, {"title": "My idea"})
    assert refused.status_code == 403
    assert "company owner" in refused.json()["detail"]
    page = api.as_(member).get(URL).json()
    assert page["may_propose"] is False and len(page["proposals"]) == 1
    assert GoalProposal.all_objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_the_practice_does_not_propose_it_creates(role, seeded_tenant, company, api,
                                                  in_tenant_a):
    member = MembershipFactory(tenant=seeded_tenant, role=role)
    ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    refused = post(api.as_(member), URL, {"client_company": str(company.pk), "title": "Ours"})
    assert refused.status_code == 403
    assert not GoalProposal.all_objects.exists()


@pytest.mark.django_db
def test_a_client_still_cannot_create_a_goal_directly(dana, api, in_tenant_a):
    assert post(api.as_(dana), "/api/goals/", {"title": "Our strategy"}).status_code == 403
    assert not Goal.all_objects.exists()


# ------------------------------------------------------------ the decision

@pytest.mark.django_db
def test_accepting_is_what_makes_it_a_goal(proposed, ff, dana, api, company, in_tenant_a):
    accepted = post(api.as_(ff), f"{URL}{proposed['id']}/accept/")
    assert accepted.status_code == 200, accepted.content
    body = accepted.json()
    assert body["state"] == "accepted" and body["goal"]

    goal = Goal.all_objects.get()
    assert str(goal.pk) == body["goal"]
    assert goal.title == "Stop losing drivers in their first month"
    assert goal.client_company_id == company.pk and goal.owner_id == ff.user_id
    assert goal.description == "We hired nine and kept four."
    # It is on the report, for the practice and for the client who asked.
    for client, co in ((api.as_(ff), company), (api.as_(dana), None)):
        assert titles_on_report(client, co) == ["Stop losing drivers in their first month"]
    assert api.as_(ff).get(f"{URL}pending/").json() == []

    theirs = api.as_(dana).get(URL).json()["proposals"][0]
    assert theirs["state"] == "accepted" and theirs["goal"] == str(goal.pk)
    assert theirs["decided_by"] == (ff.user.full_name or ff.user.email)

    event = AuditEvent.all_objects.get(verb="goal.proposal_accepted")
    assert event.actor_id == ff.user_id and event.payload["goal"] == str(goal.pk)
    assert event.payload["proposed_by"] == str(dana.user_id)


@pytest.mark.django_db
def test_the_practice_may_reword_it_and_the_proposal_keeps_the_clients_words(
    proposed, ff, dana, api, in_tenant_a
):
    accepted = post(api.as_(ff), f"{URL}{proposed['id']}/accept/",
                    {"title": "  Keep new drivers past 30 days  "})
    assert accepted.status_code == 200
    assert Goal.all_objects.get().title == "Keep new drivers past 30 days"

    theirs = api.as_(dana).get(URL).json()["proposals"][0]
    assert theirs["title"] == "Stop losing drivers in their first month"
    assert theirs["goal_title"] == "Keep new drivers past 30 days"


@pytest.mark.django_db
def test_accepting_with_a_blank_title_is_refused_and_it_stays_waiting(
    proposed, ff, api, in_tenant_a
):
    refused = post(api.as_(ff), f"{URL}{proposed['id']}/accept/", {"title": "  "})
    assert refused.status_code == 400
    assert GoalProposal.all_objects.get().state == "pending"
    assert not Goal.all_objects.exists()


@pytest.mark.django_db
def test_declining_creates_nothing_and_the_client_reads_why(proposed, ff, dana, api,
                                                           in_tenant_a):
    declined = post(api.as_(ff), f"{URL}{proposed['id']}/decline/",
                    {"note": "It belongs under the hiring goal we already have."})
    assert declined.status_code == 200 and declined.json()["state"] == "declined"
    assert not Goal.all_objects.exists()

    theirs = api.as_(dana).get(URL).json()["proposals"][0]
    assert theirs["state"] == "declined" and theirs["goal"] is None
    assert theirs["decision_note"] == "It belongs under the hiring goal we already have."
    assert AuditEvent.all_objects.filter(verb="goal.proposal_declined").count() == 1


@pytest.mark.django_db
def test_a_proposal_is_answered_once(proposed, ff, api, in_tenant_a):
    assert post(api.as_(ff), f"{URL}{proposed['id']}/accept/").status_code == 200
    for verb in ("accept", "decline"):
        again = post(api.as_(ff), f"{URL}{proposed['id']}/{verb}/")
        assert again.status_code == 409
        assert "already been answered" in again.json()["detail"]
    assert Goal.all_objects.count() == 1, "A second accept made a second goal."


@pytest.mark.django_db
def test_the_proposal_shows_in_the_activity_log_in_words(proposed, ff, api, in_tenant_a):
    post(api.as_(ff), f"{URL}{proposed['id']}/accept/")
    rows = {r["kind"]: r["text"] for r in api.as_(ff).get("/api/activity/").json()}
    assert rows["goal.proposed"] == "proposed a goal for Northwind Foods"
    assert rows["goal.proposal_accepted"] == "accepted a goal Northwind Foods proposed"


@pytest.mark.django_db
def test_an_assistant_reads_the_review_and_decides_nothing(proposed, va, api, company,
                                                          in_tenant_a):
    assert api.as_(va).get(f"{URL}?client_company={company.pk}").json()["may_decide"] is False
    for verb in ("accept", "decline"):
        assert post(api.as_(va), f"{URL}{proposed['id']}/{verb}/").status_code == 403
    assert GoalProposal.all_objects.get().state == "pending"
    assert not Goal.all_objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_cannot_accept_a_proposal_not_even_their_own(
    role, proposed, dana, seeded_tenant, company, api, in_tenant_a
):
    member = dana if role == "FCC" else a_client(seeded_tenant, company, "ECC", first="Priya")
    for verb in ("accept", "decline"):
        assert post(api.as_(member), f"{URL}{proposed['id']}/{verb}/").status_code == 403
    assert GoalProposal.all_objects.get().state == "pending"
    assert not Goal.all_objects.exists()
    assert api.as_(member).get(f"{URL}pending/").status_code == 403


@pytest.mark.django_db
def test_an_associate_decides_only_at_a_company_they_are_assigned(
    proposed, cf, api, company, seeded_tenant, in_tenant_a
):
    assert api.as_(cf).get(f"{URL}?client_company={company.pk}").status_code == 404
    assert post(api.as_(cf), f"{URL}{proposed['id']}/accept/").status_code == 404
    assert api.as_(cf).get(f"{URL}pending/").json() == []
    assert not Goal.all_objects.exists()

    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert [p["id"] for p in api.as_(cf).get(f"{URL}pending/").json()] == [proposed["id"]]
    assert post(api.as_(cf), f"{URL}{proposed['id']}/accept/").status_code == 200


# ------------------------------------------- another company, another practice

@pytest.mark.django_db
def test_another_company_in_the_same_practice_sees_and_touches_none_of_it(
    proposed, seeded_tenant, company, api, in_tenant_a
):
    """FR-0.2."""
    rival_company = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight",
                                         seat_count=2)
    for role in ("FCC", "ECC"):
        rival = a_client(seeded_tenant, rival_company, role, first=f"Rival{role}")
        assert api.as_(rival).get(URL).json()["proposals"] == []
        # Naming Northwind changes nothing: a client's company is never read
        # from the request.
        named = api.as_(rival).get(f"{URL}?client_company={company.pk}").json()
        assert named["company"] == str(rival_company.pk) and named["proposals"] == []
        for verb in ("accept", "decline"):
            assert post(api.as_(rival), f"{URL}{proposed['id']}/{verb}/").status_code == 404

    # And a rival owner's proposal is filed under their own company whatever
    # company the request names.
    rival_owner = a_client(seeded_tenant, rival_company, "FCC", first="Owner")
    made = post(api.as_(rival_owner), URL,
                {"client_company": str(company.pk), "title": "Ours, not theirs"})
    assert made.status_code == 201 and made.json()["company"] == str(rival_company.pk)
    assert GoalProposal.all_objects.get(pk=proposed["id"]).state == "pending"


@pytest.mark.django_db
def test_another_practice_sees_and_touches_none_of_it(proposed, company, api, tenant_b):
    for role in ("FF", "CF", "VA"):
        theirs = MembershipFactory(tenant=tenant_b, role=role)
        client = api.as_(theirs)
        assert client.get(f"{URL}?client_company={company.pk}").status_code == 404
        assert client.get(f"{URL}pending/").json() == []
        for verb in ("accept", "decline"):
            assert post(client, f"{URL}{proposed['id']}/{verb}/").status_code == 404
    their_company = ClientCompanyFactory(tenant=tenant_b, name="Elsewhere Ltd", seat_count=2)
    their_owner = a_client(tenant_b, their_company, "FCC", first="Elsewhere")
    assert api.as_(their_owner).get(URL).json()["proposals"] == []

    assert GoalProposal.all_objects.get(pk=proposed["id"]).state == "pending"
    assert not Goal.all_objects.exists()


@pytest.mark.django_db
def test_signed_out_gets_nothing(company, client):
    assert client.get(f"{URL}?client_company={company.pk}").status_code in (401, 403)
    assert client.post(URL, {"title": "Anyone"}).status_code in (401, 403)
