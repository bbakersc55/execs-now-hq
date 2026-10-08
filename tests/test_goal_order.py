"""The order of a client company's goals (owner, 2026-10-07).

- One order per company: current goals by rank (unranked after, by creation),
  historical goals after. Work, the practice's report and the portal read it.
- **The practice sets it; a client proposes it.** A proposal changes nothing
  until the practice owner or an assigned associate accepts it.
- Every change and every proposal is audited with who made it.
"""

from __future__ import annotations

import json

import pytest

from apps.tenancy.models import AuditEvent
from apps.work.models import CompanyGoalOrder, GoalOrderProposal

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)

URL = "/api/goal-order/"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def make(client, url, **data):
    response = post(client, url, data)
    assert response.status_code == 201, response.content
    return response.json()


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
def goals(seeded_tenant, ff, api, company, in_tenant_a):
    """Four goals, made in this order: Cash, Hiring, Hours, Vendors."""
    return {title: make(api.as_(ff), "/api/goals/", title=title,
                        client_company=str(company.pk))["id"]
            for title in ("Cash", "Hiring", "Hours", "Vendors")}


@pytest.fixture
def dana(seeded_tenant, company):
    return a_client(seeded_tenant, company, "FCC")


def ids(goals, *titles):
    return [goals[t] for t in titles]


def report_order(client, company=None):
    query = f"?client_company={company.pk}" if company is not None else ""
    body = client.get(f"/api/value-report/{query}").json()
    return ([b["title"] for b in body["current"]], [b["title"] for b in body["historical"]])


def order_of(client, company=None):
    query = f"?client_company={company.pk}" if company is not None else ""
    return [g["title"] for g in client.get(f"{URL}{query}").json()["order"]]


def resolve(api, ff, goal, how="achieved"):
    made = post(api.as_(ff), "/api/goal-resolutions/",
                {"goal": goal, "resolution": how, "reason": "It is done."})
    assert made.status_code == 201, made.content


# ------------------------------------------------------------ the default

@pytest.mark.django_db
def test_unordered_goals_read_by_creation_with_historical_ones_after(
    goals, ff, api, company, dana, in_tenant_a
):
    resolve(api, ff, goals["Hiring"])

    expected = (["Cash", "Hours", "Vendors"], ["Hiring"])
    assert report_order(api.as_(ff), company) == expected
    assert report_order(api.as_(dana)) == expected, "The portal read a different order."
    assert order_of(api.as_(ff), company) == ["Cash", "Hours", "Vendors"]

    listed = api.as_(ff).get("/api/goals/").json()
    assert [(g["title"], g["priority"], g["is_historical"]) for g in listed] == [
        ("Cash", 1, False), ("Hours", 2, False), ("Vendors", 3, False),
        ("Hiring", None, True)]


@pytest.mark.django_db
def test_two_companies_each_keep_their_own_order_in_the_goals_list(
    goals, ff, api, company, seeded_tenant, in_tenant_a
):
    other = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight", seat_count=2)
    for title in ("Fleet", "Routes"):
        make(api.as_(ff), "/api/goals/", title=title, client_company=str(other.pk))
    assert post(api.as_(ff), URL, {"client_company": str(company.pk),
                                   "order": ids(goals, "Vendors", "Hours", "Hiring", "Cash")}
                ).status_code == 200

    listed = api.as_(ff).get("/api/goals/").json()
    by_company = {}
    for g in listed:
        by_company.setdefault(g["client_company_name"], []).append((g["title"], g["priority"]))
    assert by_company["Northwind Foods"] == [("Vendors", 1), ("Hours", 2), ("Hiring", 3),
                                            ("Cash", 4)]
    assert by_company["Ridgeline Freight"] == [("Fleet", 1), ("Routes", 2)]


# ------------------------------------------------------- the practice sets it

@pytest.mark.django_db
def test_the_practice_sets_the_order_and_everyone_reads_it(
    goals, ff, api, company, dana, in_tenant_a
):
    new = ["Vendors", "Cash", "Hours", "Hiring"]
    done = post(api.as_(ff), URL, {"client_company": str(company.pk),
                                   "order": ids(goals, *new)})
    assert done.status_code == 200, done.content
    assert [g["title"] for g in done.json()["order"]] == new

    assert report_order(api.as_(ff), company) == (new, [])
    assert report_order(api.as_(dana)) == (new, [])
    assert order_of(api.as_(dana)) == new
    assert [g["title"] for g in api.as_(dana).get("/api/goals/").json()] == new
    # No proposal was involved: the practice's order is the order.
    assert not GoalOrderProposal.all_objects.exists()


@pytest.mark.django_db
def test_a_goal_made_after_the_order_was_set_comes_last_among_current(
    goals, ff, api, company, in_tenant_a
):
    post(api.as_(ff), URL, {"client_company": str(company.pk),
                            "order": ids(goals, "Vendors", "Hours", "Hiring", "Cash")})
    make(api.as_(ff), "/api/goals/", title="Pricing", client_company=str(company.pk))
    assert order_of(api.as_(ff), company) == ["Vendors", "Hours", "Hiring", "Cash", "Pricing"]


@pytest.mark.django_db
def test_a_resolved_goal_leaves_the_order_and_a_resumed_one_returns_to_its_place(
    goals, ff, api, company, in_tenant_a
):
    post(api.as_(ff), URL, {"client_company": str(company.pk),
                            "order": ids(goals, "Vendors", "Hours", "Hiring", "Cash")})
    resolve(api, ff, goals["Hours"], "paused")
    assert report_order(api.as_(ff), company) == (["Vendors", "Hiring", "Cash"], ["Hours"])

    resolve(api, ff, goals["Hours"], "resumed")
    assert report_order(api.as_(ff), company) == (["Vendors", "Hours", "Hiring", "Cash"], [])


@pytest.mark.django_db
@pytest.mark.parametrize("bad,why", [
    (lambda g: ids(g, "Cash", "Hiring", "Hours"), "have changed"),              # one missing
    (lambda g: ids(g, "Cash", "Cash", "Hiring", "Hours"), "twice"),             # a duplicate
    (lambda g: ids(g, "Cash", "Hiring", "Hours", "Vendors") + ["not-an-id"], "have changed"),
    (lambda g: "Cash", "list of goal ids"),
    (lambda g: None, "list of goal ids"),
])
def test_an_order_that_is_not_exactly_the_current_goals_is_refused_whole(
    bad, why, goals, ff, api, company, in_tenant_a
):
    refused = post(api.as_(ff), URL, {"client_company": str(company.pk), "order": bad(goals)})
    assert refused.status_code == 400 and why in refused.json()["detail"]
    assert not CompanyGoalOrder.all_objects.exists(), "It was half-applied."
    assert not AuditEvent.all_objects.filter(verb="goal.reordered").exists()


@pytest.mark.django_db
def test_a_historical_goal_cannot_be_put_in_the_order(goals, ff, api, company, in_tenant_a):
    resolve(api, ff, goals["Hiring"])
    refused = post(api.as_(ff), URL, {"client_company": str(company.pk),
                                      "order": ids(goals, "Hiring", "Cash", "Hours", "Vendors")})
    assert refused.status_code == 400


@pytest.mark.django_db
def test_setting_the_order_is_audited_with_before_and_after(goals, ff, api, company,
                                                            in_tenant_a):
    post(api.as_(ff), URL, {"client_company": str(company.pk),
                            "order": ids(goals, "Vendors", "Cash", "Hours", "Hiring")})
    event = AuditEvent.all_objects.get(verb="goal.reordered")
    assert event.actor_id == ff.user_id and str(event.target_id) == str(company.pk)
    assert event.payload == {"from": ["Cash", "Hiring", "Hours", "Vendors"],
                             "to": ["Vendors", "Cash", "Hours", "Hiring"]}

    # The same order again moves nothing and is not written down twice.
    post(api.as_(ff), URL, {"client_company": str(company.pk),
                            "order": ids(goals, "Vendors", "Cash", "Hours", "Hiring")})
    assert AuditEvent.all_objects.filter(verb="goal.reordered").count() == 1

    row = next(r for r in api.as_(ff).get("/api/activity/").json()
               if r["kind"] == "goal.reordered")
    assert row["text"] == "changed the order of Northwind Foods's goals"


# ------------------------------------------------------- a client proposes it

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_clients_reorder_is_a_proposal_and_changes_nothing(
    role, goals, ff, api, company, seeded_tenant, in_tenant_a
):
    member = a_client(seeded_tenant, company, role)
    wanted = ["Hours", "Cash", "Hiring", "Vendors"]
    made = post(api.as_(member), URL, {"order": ids(goals, *wanted),
                                       "note": "Hours is what hurts most."})
    assert made.status_code == 201, made.content
    state = made.json()
    assert [g["title"] for g in state["order"]] == ["Cash", "Hiring", "Hours", "Vendors"]
    assert state["proposal"]["state"] == "pending"
    assert [g["title"] for g in state["proposal"]["order"]] == wanted
    assert state["proposal"]["note"] == "Hours is what hurts most."
    assert state["may_propose"] is True and state["may_reorder"] is False

    # Nothing moved, for them or for the practice.
    unchanged = (["Cash", "Hiring", "Hours", "Vendors"], [])
    assert report_order(api.as_(member)) == unchanged
    assert report_order(api.as_(ff), company) == unchanged
    assert not CompanyGoalOrder.all_objects.exists()

    event = AuditEvent.all_objects.get(verb="goal.order_proposed")
    assert event.actor_id == member.user_id and event.payload["to"] == wanted
    assert not AuditEvent.all_objects.filter(verb="goal.reordered").exists()


@pytest.mark.django_db
def test_proposing_the_order_they_are_already_in_is_refused(goals, dana, api, in_tenant_a):
    refused = post(api.as_(dana), URL, {"order": ids(goals, "Cash", "Hiring", "Hours", "Vendors")})
    assert refused.status_code == 400 and "already in" in refused.json()["detail"]
    assert not GoalOrderProposal.all_objects.exists()


@pytest.mark.django_db
def test_a_second_proposal_replaces_the_first_and_keeps_it(goals, dana, api, in_tenant_a):
    post(api.as_(dana), URL, {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")})
    second = post(api.as_(dana), URL, {"order": ids(goals, "Vendors", "Cash", "Hiring", "Hours")})
    assert second.status_code == 201

    states = sorted(GoalOrderProposal.all_objects.values_list("state", flat=True))
    assert states == ["pending", "superseded"]
    assert [g["title"] for g in second.json()["proposal"]["order"]][0] == "Vendors"


@pytest.mark.django_db
def test_the_practice_accepts_and_the_proposed_order_becomes_the_order(
    goals, ff, dana, api, company, in_tenant_a
):
    wanted = ["Hours", "Cash", "Hiring", "Vendors"]
    proposal = post(api.as_(dana), URL, {"order": ids(goals, *wanted)}).json()["proposal"]

    # The practice sees it waiting, with who proposed it.
    seen = api.as_(ff).get(f"{URL}?client_company={company.pk}").json()
    assert seen["proposal"]["id"] == proposal["id"] and seen["may_reorder"] is True
    assert seen["proposal"]["proposed_by"] == (dana.user.full_name or dana.user.email)

    accepted = post(api.as_(ff), f"{URL}{proposal['id']}/accept/")
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["proposal"] is None
    assert [g["title"] for g in accepted.json()["order"]] == wanted

    assert report_order(api.as_(ff), company) == (wanted, [])
    assert report_order(api.as_(dana)) == (wanted, [])
    # And the client is told, on their own page.
    theirs = api.as_(dana).get(URL).json()
    assert theirs["proposal"] is None and theirs["last_decided"]["state"] == "accepted"
    assert theirs["last_decided"]["decided_by"] == (ff.user.full_name or ff.user.email)

    event = AuditEvent.all_objects.get(verb="goal.order_accepted")
    assert event.actor_id == ff.user_id
    assert event.payload["proposed_by"] == str(dana.user_id)
    assert event.payload["from"] == ["Cash", "Hiring", "Hours", "Vendors"]
    assert event.payload["to"] == wanted


@pytest.mark.django_db
def test_the_practice_declines_and_the_client_reads_why(goals, ff, dana, api, company,
                                                        in_tenant_a):
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    declined = post(api.as_(ff), f"{URL}{proposal['id']}/decline/",
                    {"note": "Cash has to land before Hours can move."})
    assert declined.status_code == 200

    assert report_order(api.as_(dana)) == (["Cash", "Hiring", "Hours", "Vendors"], [])
    theirs = api.as_(dana).get(URL).json()
    assert theirs["proposal"] is None
    assert theirs["last_decided"]["state"] == "declined"
    assert theirs["last_decided"]["decision_note"] == "Cash has to land before Hours can move."
    assert AuditEvent.all_objects.filter(verb="goal.order_declined").count() == 1
    assert not CompanyGoalOrder.all_objects.exists()


@pytest.mark.django_db
def test_a_proposal_is_answered_once(goals, ff, dana, api, in_tenant_a):
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    assert post(api.as_(ff), f"{URL}{proposal['id']}/decline/").status_code == 200
    again = post(api.as_(ff), f"{URL}{proposal['id']}/accept/")
    assert again.status_code == 409 and "already been answered" in again.json()["detail"]
    assert not CompanyGoalOrder.all_objects.exists()


@pytest.mark.django_db
def test_accepting_after_the_goals_changed_applies_what_still_makes_sense(
    goals, ff, dana, api, company, in_tenant_a
):
    """Between proposing and accepting, one goal was achieved and one added."""
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Vendors", "Hiring", "Cash")}
                    ).json()["proposal"]
    resolve(api, ff, goals["Vendors"])
    make(api.as_(ff), "/api/goals/", title="Pricing", client_company=str(company.pk))

    # What the practice is shown is what accepting will do.
    shown = api.as_(ff).get(f"{URL}?client_company={company.pk}").json()["proposal"]
    assert [g["title"] for g in shown["order"]] == ["Hours", "Hiring", "Cash", "Pricing"]

    assert post(api.as_(ff), f"{URL}{proposal['id']}/accept/").status_code == 200
    assert report_order(api.as_(ff), company) == (
        ["Hours", "Hiring", "Cash", "Pricing"], ["Vendors"])


# -------------------------------------------------------------------- roles

@pytest.mark.django_db
def test_an_assistant_reads_the_order_and_decides_nothing(goals, va, dana, api, company,
                                                         in_tenant_a):
    assert order_of(api.as_(va), company) == ["Cash", "Hiring", "Hours", "Vendors"]
    assert api.as_(va).get(f"{URL}?client_company={company.pk}").json()["may_reorder"] is False

    refused = post(api.as_(va), URL, {"client_company": str(company.pk),
                                      "order": ids(goals, "Vendors", "Cash", "Hours", "Hiring")})
    assert refused.status_code == 403
    assert not CompanyGoalOrder.all_objects.exists()

    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    for verb in ("accept", "decline"):
        assert post(api.as_(va), f"{URL}{proposal['id']}/{verb}/").status_code == 403
    assert GoalOrderProposal.all_objects.get().state == "pending"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_cannot_accept_a_proposal_not_even_their_own(
    role, goals, api, company, seeded_tenant, in_tenant_a
):
    member = a_client(seeded_tenant, company, role)
    proposal = post(api.as_(member), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    for verb in ("accept", "decline"):
        assert post(api.as_(member), f"{URL}{proposal['id']}/{verb}/").status_code == 403
    assert GoalOrderProposal.all_objects.get().state == "pending"
    assert not CompanyGoalOrder.all_objects.exists()


@pytest.mark.django_db
def test_an_associate_orders_and_accepts_only_at_a_company_they_are_assigned(
    goals, cf, dana, api, company, seeded_tenant, in_tenant_a
):
    new = {"client_company": str(company.pk),
           "order": ids(goals, "Vendors", "Cash", "Hours", "Hiring")}
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]

    assert api.as_(cf).get(f"{URL}?client_company={company.pk}").status_code == 404
    assert post(api.as_(cf), URL, new).status_code == 404
    assert post(api.as_(cf), f"{URL}{proposal['id']}/accept/").status_code == 404
    assert api.as_(cf).get(f"{URL}pending/").json() == []
    assert not CompanyGoalOrder.all_objects.exists()

    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert [p["id"] for p in api.as_(cf).get(f"{URL}pending/").json()] == [proposal["id"]]
    assert post(api.as_(cf), f"{URL}{proposal['id']}/accept/").status_code == 200
    assert post(api.as_(cf), URL, new).status_code == 200


@pytest.mark.django_db
def test_the_waiting_list_is_the_practices(goals, ff, va, dana, api, in_tenant_a):
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    for member in (ff, va):
        waiting = api.as_(member).get(f"{URL}pending/").json()
        assert [(p["id"], p["company_name"]) for p in waiting] == [
            (proposal["id"], "Northwind Foods")]
    assert api.as_(dana).get(f"{URL}pending/").status_code == 403


# ------------------------------------------- another company, another practice

@pytest.mark.django_db
def test_another_company_in_the_same_practice_sees_and_touches_none_of_it(
    goals, ff, dana, api, company, seeded_tenant, in_tenant_a
):
    """FR-0.2. A client's company is implied, so the only ways across are a
    goal id in the order and a proposal id in the address. Both are closed."""
    rival_company = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight",
                                         seat_count=2)
    rival = a_client(seeded_tenant, rival_company, "FCC", first="Rival")
    make(api.as_(ff), "/api/goals/", title="Fleet", client_company=str(rival_company.pk))
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]

    # Their own page shows their own goal, and no proposal of Northwind's.
    theirs = api.as_(rival).get(URL).json()
    assert [g["title"] for g in theirs["order"]] == ["Fleet"] and theirs["proposal"] is None
    # Naming Northwind does nothing: a client's company is never read from the request.
    named = api.as_(rival).get(f"{URL}?client_company={company.pk}").json()
    assert [g["title"] for g in named["order"]] == ["Fleet"]
    # Northwind's goals in an order are not "the current goals" of Ridgeline.
    assert post(api.as_(rival), URL,
                {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}).status_code == 400
    assert post(api.as_(rival), URL, {"client_company": str(company.pk),
                "order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}).status_code == 400
    for verb in ("accept", "decline"):
        assert post(api.as_(rival), f"{URL}{proposal['id']}/{verb}/").status_code == 404

    assert GoalOrderProposal.all_objects.count() == 1
    assert GoalOrderProposal.all_objects.get().state == "pending"


@pytest.mark.django_db
def test_another_practice_sees_and_touches_none_of_it(goals, dana, api, company, tenant_b):
    proposal = post(api.as_(dana), URL,
                    {"order": ids(goals, "Hours", "Cash", "Hiring", "Vendors")}
                    ).json()["proposal"]
    for role in ("FF", "CF", "VA"):
        theirs = MembershipFactory(tenant=tenant_b, role=role)
        client = api.as_(theirs)
        assert client.get(f"{URL}?client_company={company.pk}").status_code == 404
        assert post(client, URL, {"client_company": str(company.pk),
                                  "order": ids(goals, "Vendors", "Cash", "Hours", "Hiring")}
                    ).status_code == 404
        for verb in ("accept", "decline"):
            assert post(client, f"{URL}{proposal['id']}/{verb}/").status_code == 404
        assert client.get(f"{URL}pending/").json() == []

    assert GoalOrderProposal.all_objects.get().state == "pending"
    assert not CompanyGoalOrder.all_objects.exists()


@pytest.mark.django_db
def test_signed_out_gets_nothing(goals, company, client):
    assert client.get(f"{URL}?client_company={company.pk}").status_code in (401, 403)
    assert client.get(f"{URL}pending/").status_code in (401, 403)
