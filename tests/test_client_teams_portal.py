"""P7 phase 3 — the client owner sets their own company's teams up
(`docs/p7_client_teams_permissions.md` §1.3, §4.2).

The same routes as the practice's Teams card (phase 2), reached by the client
owner for their own company.

- **Isolation:** another company of the same practice, its teams and its
  people are not found by a client owner; nor is anything of another
  practice.
- **Role boundaries:** the client owner, and no other client user, acting
  as a colleague included. Two limits on the client owner: a client owner's
  settings (theirs, or another client owner's) are the practice's, and they
  give nobody more to create than they may create themselves.
- **A change takes effect when it is made:** asked through the routes the
  person themselves calls.
"""

from __future__ import annotations

import json

import pytest

from apps.tenancy.models import AuditEvent, Membership
from apps.work.models import ClientTeam, ClientTeamMember

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory
from .test_client_teams import ALL_TASKS, named, patch, post, world  # noqa: F401
from .test_client_teams_setup import card

L = ClientTeamMember.Level
T = "/api/client-teams/"


def call(client, method, url, body=None):
    if method == "get":
        return client.get(url)
    return getattr(client, method)(url, json.dumps(body or {}), content_type="application/json")


def task_names(world, client):
    response = client.get("/api/tasks/")
    assert response.status_code == 200, response.content
    rows = response.json()
    rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    return named(world, "tasks", [row["id"] for row in rows])


@pytest.mark.django_db
def test_the_client_owner_sets_up_their_companys_teams_and_each_is_audited_as_theirs(world):
    tenant, company, t, who = world["tenant"], world["company"], world["teams"], world["who"]
    owner = world["api"].as_(who["owner"])

    data = card(owner, company)
    assert data["may_manage"] is True
    assert [x["name"] for x in data["teams"]] == ["Everyone", "Operations", "Sales"]
    assert len(data["people"]) == 9
    assert [x["name"] for x in owner.get(f"{T}names/?company={company.pk}").json()] == [
        "Everyone", "Operations", "Sales"]

    made = post(owner, T, {"company": str(company.pk), "name": "Front office"})
    assert made.status_code == 201
    front = ClientTeam.all_objects.get(client_company=company, name="Front office")
    assert front.created_by_id == who["owner"].user_id
    assert patch(owner, f"{T}{front.pk}/", {"name": "Front of house"}).status_code == 200
    assert post(owner, f"{T}{front.pk}/level/",
                {"membership": str(who["viewer"].pk), "level": "manager"}).status_code == 200
    assert post(owner, f"{T}person/", {"membership": str(who["member"].pk),
                                       "may_create": "tasks",
                                       "leads_all_teams": True}).status_code == 200
    preview = owner.get(f"{T}{t['sales'].pk}/archive/").json()
    assert (preview["projects"], preview["moves_to"]) == (1, "Everyone")
    done = post(owner, f"{T}{t['sales'].pk}/archive/")
    assert done.status_code == 200 and done.json()["archived"]["projects"] == 1

    member = Membership.all_objects.get(pk=who["member"].pk)
    assert (member.may_create, member.leads_all_teams) == ("tasks", True)
    events = AuditEvent.all_objects.filter(tenant=tenant).filter(
        verb__in=("client_team.created", "client_team.renamed", "client_team.level_set",
                  "client_team.archived", "portal.may_create_changed",
                  "portal.leads_all_teams_changed"))
    assert events.count() == 6
    assert set(events.values_list("actor_id", flat=True)) == {who["owner"].user_id}


@pytest.mark.django_db
def test_role_boundaries_a_level_the_client_owner_sets_takes_effect_at_once(world):
    who, t = world["who"], world["teams"]
    member = world["api"].as_(who["member"])
    assert task_names(world, member) == {"ops, of the member"}

    owner = world["api"].as_(who["owner"])
    assert post(owner, f"{T}{t['ops'].pk}/level/",
                {"membership": str(who["member"].pk), "level": "manager"}).status_code == 200
    assert task_names(world, member) == ALL_TASKS

    assert post(owner, f"{T}{t['ops'].pk}/level/",
                {"membership": str(who["member"].pk), "level": None}).status_code == 200
    assert task_names(world, member) == {"ops, of the member"}, "theirs, and no more"


@pytest.mark.django_db
def test_role_boundaries_a_client_owners_settings_are_the_practices(world):
    company, t, who = world["company"], world["teams"], world["who"]
    owner = world["api"].as_(who["owner"])
    second = MembershipFactory(tenant=world["tenant"], role="FCC", client_company=company)

    for person in (who["owner"], second):
        for url, body in (
                (f"{T}person/", {"membership": str(person.pk), "may_create": "nothing"}),
                (f"{T}person/", {"membership": str(person.pk), "leads_all_teams": True}),
                (f"{T}{t['ops'].pk}/level/", {"membership": str(person.pk),
                                              "level": "member"})):
            refused = post(owner, url, body)
            assert refused.status_code == 403, (person, url)
            assert "A client owner's settings are set by" in refused.json()["detail"]
            assert "FCC" not in refused.json()["detail"]
    assert not ClientTeamMember.all_objects.filter(
        team=t["ops"], membership__in=[who["owner"], second]).exists()
    assert Membership.all_objects.get(pk=who["owner"].pk).may_create == "projects"

    # The practice sets them, as in phase 2.
    practice = world["api"].as_(world["ff"])
    assert post(practice, f"{T}person/", {"membership": str(second.pk),
                                          "may_create": "goals"}).status_code == 200


@pytest.mark.django_db
def test_role_boundaries_the_client_owner_gives_no_more_to_create_than_they_may(world):
    who = world["who"]
    owner = world["api"].as_(who["owner"])               # may create projects and tasks
    target = {"membership": str(who["member"].pk)}

    for allowed in ("nothing", "tasks", "projects"):
        assert post(owner, f"{T}person/", {**target, "may_create": allowed}
                    ).status_code == 200, allowed
    refused = post(owner, f"{T}person/", {**target, "may_create": "goals"})
    assert refused.status_code == 403
    assert "at most what you may create yourself (projects and tasks)" in \
        refused.json()["detail"]
    assert Membership.all_objects.get(pk=who["member"].pk).may_create == "projects"

    # Once the practice gives the client owner "Goals too", they may give it.
    practice = world["api"].as_(world["ff"])
    assert post(practice, f"{T}person/", {"membership": str(who["owner"].pk),
                                          "may_create": "goals"}).status_code == 200
    assert post(owner, f"{T}person/", {**target, "may_create": "goals"}).status_code == 200
    # Lowering someone who has more than the client owner is never refused.
    Membership.all_objects.filter(pk=who["owner"].pk).update(may_create="tasks")
    assert post(owner, f"{T}person/", {**target, "may_create": "nothing"}).status_code == 200


@pytest.mark.django_db
def test_role_boundaries_no_other_client_user_and_not_while_acting_as_one(world):
    company, t, who = world["company"], world["teams"], world["who"]
    writes = [
        ("get", f"{T}?company={company.pk}", None),
        ("get", f"{T}names/?company={company.pk}", None),
        ("post", T, {"company": str(company.pk), "name": "Finance"}),
        ("patch", f"{T}{t['sales'].pk}/", {"name": "Revenue"}),
        ("get", f"{T}{t['sales'].pk}/archive/", None),
        ("post", f"{T}{t['sales'].pk}/level/",
         {"membership": str(who["member"].pk), "level": "viewer"}),
        ("post", f"{T}person/", {"membership": str(who["member"].pk), "may_create": "tasks"}),
    ]
    for level in ("member", "manager", "leader", "leader_all", "viewer", "on_no_team"):
        client = world["api"].as_(who[level])
        for method, url, body in writes:
            refused = call(client, method, url, body)
            assert refused.status_code == 403, (level, url)
            assert refused.json()["detail"] == \
                "Only your client owner sets up your company's teams."

    # The client owner acting as a colleague has that colleague's reach.
    owner = world["api"].as_(who["owner"])
    assert post(owner, "/api/act-as/", {"membership": str(who["manager"].pk)}
                ).status_code in (200, 201)
    for method, url, body in writes:
        assert call(owner, method, url, body).status_code == 403, url
    assert post(owner, "/api/act-as/stop/").status_code == 200
    assert card(owner, company)["may_manage"] is True

    assert not ClientTeam.all_objects.filter(name__in=("Finance", "Revenue")).exists()
    assert Membership.all_objects.get(pk=who["member"].pk).may_create == "projects"


@pytest.mark.django_db
def test_tenant_isolation_a_client_owner_reaches_only_their_own_company(world, tenant_b):
    tenant, company, t, who = world["tenant"], world["company"], world["teams"], world["who"]
    owner = world["api"].as_(who["owner"])

    # Another company of the same practice: its card, its team, its people.
    other = ClientCompanyFactory(tenant=tenant, name="Globex Logistics")
    outsider = MembershipFactory(tenant=tenant, role="ECC", client_company=other)
    their_team = ClientTeam.all_objects.get(client_company=other)
    for method, url, body in (
            ("get", f"{T}?company={other.pk}", None),
            ("get", f"{T}names/?company={other.pk}", None),
            ("post", T, {"company": str(other.pk), "name": "Ours now"}),
            ("patch", f"{T}{their_team.pk}/", {"name": "Ours now"}),
            ("get", f"{T}{their_team.pk}/archive/", None),
            ("post", f"{T}{their_team.pk}/level/",
             {"membership": str(outsider.pk), "level": "leader"}),
            ("post", f"{T}person/", {"membership": str(outsider.pk), "may_create": "nothing"}),
            # One of theirs onto one of ours: not found either.
            ("post", f"{T}{t['ops'].pk}/level/",
             {"membership": str(outsider.pk), "level": "member"})):
        assert call(owner, method, url, body).status_code == 404, url
    # No company named is not "my company": it is not found.
    assert owner.get(T).status_code == 404

    # Another practice.
    theirs = ClientCompanyFactory(tenant=tenant_b, name="Initech")
    stranger = MembershipFactory(tenant=tenant_b, role="ECC", client_company=theirs)
    b_team = ClientTeam.all_objects.get(client_company=theirs)
    assert owner.get(f"{T}?company={theirs.pk}").status_code == 404
    assert patch(owner, f"{T}{b_team.pk}/", {"name": "Ours now"}).status_code == 404
    assert post(owner, f"{T}person/", {"membership": str(stranger.pk),
                                       "may_create": "nothing"}).status_code == 404
    # And practice B's client owner, with practice A's ids.
    b_owner = world["api"].as_(MembershipFactory(tenant=tenant_b, role="FCC",
                                                 client_company=theirs))
    assert b_owner.get(f"{T}?company={company.pk}").status_code == 404
    assert post(b_owner, f"{T}{t['ops'].pk}/level/",
                {"membership": str(who["member"].pk), "level": "viewer"}).status_code == 404

    assert ClientTeam.all_objects.get(pk=their_team.pk).name == "Everyone"
    assert ClientTeam.all_objects.get(pk=b_team.pk).name == "Everyone"
    assert not ClientTeamMember.all_objects.filter(team=t["ops"], membership=outsider).exists()
    assert Membership.all_objects.get(pk=outsider.pk).may_create == "projects"
    assert Membership.all_objects.get(pk=stranger.pk).may_create == "projects"
