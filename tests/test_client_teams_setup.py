"""P7 phase 2 — the practice sets a client's teams up
(`docs/p7_client_teams_permissions.md` §1.3, §4.1).

The Teams card's routes, the Team field on a project and a task, and the
invitation that names a team, a level and what the person may create.

- **Isolation:** a team, a person on it and a company's card are not found
  from another practice, and one company's team is never reached through
  another company of the same practice.
- **Role boundaries:** the practice owner, and an associate on a company
  they are assigned, set teams up. An assistant reads the teams' names, to
  file work, and changes nothing. A client user reaches none of it (phase 3).
- **A level takes effect when it is set:** asked through the routes the
  person themselves calls.
"""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Task
from apps.tenancy.models import AuditEvent, Membership
from apps.work import teams
from apps.work.models import ClientTeam, ClientTeamMember, Project

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)
from .test_client_teams import ALL_TASKS, make, named, patch, post, world  # noqa: F401

L = ClientTeamMember.Level
T = "/api/client-teams/"


def card(client, company):
    response = client.get(f"{T}?company={company.pk}")
    assert response.status_code == 200, response.content
    return response.json()


def verbs(tenant, prefix):
    return list(AuditEvent.all_objects.filter(tenant=tenant, verb__startswith=prefix)
                .order_by("created_at").values_list("verb", flat=True))


def a_contact(tenant, company, first, email):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True, address=email)
    return contact


# ===================================================================== the card

@pytest.mark.django_db
def test_the_card_lists_each_team_with_its_people_and_each_person_with_their_teams(world):
    practice = world["api"].as_(world["ff"])
    data = card(practice, world["company"])
    assert data["may_manage"] is True
    assert [(t["name"], t["is_default"]) for t in data["teams"]] == [
        ("Everyone", True), ("Operations", False), ("Sales", False)]
    ops = data["teams"][1]
    assert sorted(p["level"] for p in ops["people"]) == ["leader", "manager", "member",
                                                         "member"]
    # What a team holds: its projects, and its open tasks (inside them too).
    assert (ops["projects"], ops["open_tasks"]) == (2, 4)
    assert (data["teams"][2]["projects"], data["teams"][2]["open_tasks"]) == (1, 1)
    assert (data["teams"][0]["projects"], data["teams"][0]["open_tasks"]) == (0, 1), \
        "the hidden task, filed for the company by the practice"
    people = {p["id"]: p for p in data["people"]}
    assert len(people) == 9
    owner = people[str(world["who"]["owner"].pk)]
    assert (owner["role"], owner["may_create"], owner["leads_all_teams"]) == (
        "FCC", "projects", False)
    assert people[str(world["who"]["leader_all"].pk)]["leads_all_teams"] is True
    assert people[str(world["who"]["member"].pk)]["teams"] == [
        {"team": str(world["teams"]["ops"].pk), "level": "member"}]
    assert people[str(world["who"]["on_no_team"].pk)]["teams"] == []
    # No contact details beyond the address they sign in with, and no codes in words.
    assert "Client team member" not in json.dumps(data)


@pytest.mark.django_db
def test_a_team_is_made_renamed_and_archived_and_each_is_in_the_audit_trail(world):
    tenant, company, t = world["tenant"], world["company"], world["teams"]
    practice = world["api"].as_(world["ff"])

    made = post(practice, T, {"company": str(company.pk), "name": "  Front   office "})
    assert made.status_code == 201
    assert [x["name"] for x in made.json()["teams"]] == [
        "Everyone", "Front office", "Operations", "Sales"]
    for bad, why in (("", "needs a name"), ("operations", "already has a team called")):
        refused = post(practice, T, {"company": str(company.pk), "name": bad})
        assert refused.status_code == 400 and why in refused.json()["detail"], bad
    front = ClientTeam.all_objects.get(client_company=company, name="Front office")
    assert front.created_by_id == world["ff"].user_id and not front.is_default

    renamed = patch(practice, f"{T}{front.pk}/", {"name": "Front of house"})
    assert renamed.status_code == 200
    assert patch(practice, f"{T}{front.pk}/", {"name": "Sales"}).status_code == 400
    # The default team is renamed like any other, and never archived.
    assert patch(practice, f"{T}{t['everyone'].pk}/", {"name": "Whole company"}
                 ).status_code == 200
    assert practice.get(f"{T}{t['everyone'].pk}/archive/").status_code == 400
    assert post(practice, f"{T}{t['everyone'].pk}/archive/").status_code == 400

    # Archiving says what will move before it is confirmed, then moves it:
    # the work to the default team, and anyone who was on no other team too.
    preview = practice.get(f"{T}{t['ops'].pk}/archive/").json()
    assert preview == {"projects": 2, "tasks": 1, "people": 4, "people_left_on_no_team": 4,
                       "moves_to": "Whole company"}
    assert ClientTeam.all_objects.get(pk=t["ops"].pk).archived_at is None, "a look moves nothing"
    done = post(practice, f"{T}{t['ops'].pk}/archive/")
    assert done.status_code == 200
    assert done.json()["archived"] == {"projects": 2, "tasks": 1, "people_moved": 4,
                                       "moved_to": "Whole company"}
    assert [x["name"] for x in done.json()["teams"]] == [
        "Whole company", "Front of house", "Sales"]
    assert set(Project.all_objects.filter(pk__in=[world["projects"]["ops"],
                                                  world["projects"]["of the practice"]])
               .values_list("client_team_id", flat=True)) == {t["everyone"].pk}
    assert Task.all_objects.get(pk=world["tasks"]["ops, in no project"]).client_team_id \
        == t["everyone"].pk
    # Never deletes work, and nobody loses their sign-in or their level.
    assert Task.all_objects.filter(pk__in=world["tasks"].values(),
                                   deleted_at__isnull=True).count() == 6
    assert set(ClientTeamMember.all_objects.filter(team=t["everyone"]).exclude(
        level=L.VIEWER).values_list("level", flat=True)) == {"member", "manager", "leader"}
    assert Membership.all_objects.filter(client_company=company,
                                         revoked_at__isnull=True).count() == 9
    # An archived team is not found again.
    assert patch(practice, f"{T}{t['ops'].pk}/", {"name": "Ops"}).status_code == 404
    assert verbs(tenant, "client_team.") == [
        "client_team.created", "client_team.renamed", "client_team.renamed",
        "client_team.archived"]
    archived = AuditEvent.all_objects.get(tenant=tenant, verb="client_team.archived")
    assert archived.actor_id == world["ff"].user_id
    assert archived.payload["projects"] == 2 and archived.payload["people_moved"] == 4


@pytest.mark.django_db
def test_role_boundaries_a_level_takes_effect_when_it_is_set(world):
    tenant, who, t = world["tenant"], world["who"], world["teams"]
    practice = world["api"].as_(world["ff"])
    manager = who["manager"]

    def sees(person):
        listed = world["api"].as_(Membership.all_objects.get(pk=person.pk)).get(
            "/api/tasks/").json()
        return named(world, "tasks", [x["id"] for x in listed])

    def level(team, person, value):
        return post(practice, f"{T}{team.pk}/level/",
                    {"membership": str(person.pk), "level": value})

    assert sees(manager) == ALL_TASKS
    assert level(t["ops"], manager, "member").status_code == 200
    assert sees(manager) == set(), "a member, with nothing of their own"
    assert level(t["ops"], manager, "viewer").status_code == 200
    assert sees(manager) == ALL_TASKS
    assert world["api"].as_(manager).post(
        "/api/tasks/", json.dumps({"title": "x"}), content_type="application/json"
    ).status_code == 403, "and a viewer makes nothing"
    # On a second team, and off the first: on no team is allowed, and said by the card.
    assert level(t["sales"], manager, "leader").status_code == 200
    taken_off = level(t["ops"], manager, None)
    assert taken_off.status_code == 200
    person = next(p for p in taken_off.json()["people"] if p["id"] == str(manager.pk))
    assert person["teams"] == [{"team": str(t["sales"].pk), "level": "leader"}]
    assert level(t["ops"], manager, None).status_code == 200, "twice is the same as once"
    assert level(t["ops"], manager, "boss").status_code == 400

    # Senior leadership of every team, and what they may create.
    def person_(person, **settings):
        return post(practice, f"{T}person/", {"membership": str(person.pk), **settings})

    member = who["member"]
    assert sees(member) == {"ops, of the member"}
    assert person_(member, leads_all_teams=True).status_code == 200
    assert sees(member) == ALL_TASKS
    assert person_(member, leads_all_teams=False, may_create="nothing").status_code == 200
    refused = post(world["api"].as_(Membership.all_objects.get(pk=member.pk)),
                   "/api/tasks/", {"title": "x"})
    assert refused.status_code == 403
    assert person_(member, may_create="goals").status_code == 200
    assert Membership.all_objects.get(pk=member.pk).may_create == "goals"
    assert person_(member, may_create="everything").status_code == 400
    assert person_(member, leads_all_teams="yes").status_code == 400
    # Nobody at the practice has these settings.
    assert person_(world["ff"], may_create="goals").status_code == 404

    assert verbs(tenant, "client_team.") == [
        "client_team.level_set", "client_team.level_set", "client_team.level_set",
        "client_team.person_removed"]
    assert verbs(tenant, "portal.may_create") == ["portal.may_create_changed"] * 2
    assert verbs(tenant, "portal.leads_all") == ["portal.leads_all_teams_changed"] * 2
    first = AuditEvent.all_objects.filter(tenant=tenant,
                                          verb="client_team.level_set").earliest("created_at")
    assert (first.payload["from"], first.payload["to"], first.payload["team_name"]) == (
        "manager", "member", "Operations")
    assert first.target_id == manager.pk and first.actor_id == world["ff"].user_id


# ============================================================== who may, and where

@pytest.mark.django_db
def test_role_boundaries_who_sets_a_clients_teams_up(world, cf, va):
    company, t, who = world["company"], world["teams"], world["who"]
    api = world["api"]
    other = ClientCompanyFactory(tenant=world["tenant"], name="Globex Logistics")
    writes = [
        ("post", T, {"company": str(company.pk), "name": "Finance"}),
        ("patch", f"{T}{t['sales'].pk}/", {"name": "Revenue"}),
        ("get", f"{T}{t['sales'].pk}/archive/", None),
        ("post", f"{T}{t['sales'].pk}/level/",
         {"membership": str(who["member"].pk), "level": "member"}),
        ("post", f"{T}person/", {"membership": str(who["member"].pk),
                                 "may_create": "tasks"}),
    ]

    def call(client, method, url, body):
        if method == "get":
            return client.get(url)
        return getattr(client, method)(url, json.dumps(body or {}),
                                       content_type="application/json")

    # An assistant reads the names, to file work on a team, and nothing else.
    assistant = api.as_(va)
    assert [x["name"] for x in assistant.get(f"{T}names/?company={company.pk}").json()] == [
        "Everyone", "Operations", "Sales"]
    assert assistant.get(f"{T}?company={company.pk}").status_code == 403
    for method, url, body in writes:
        refused = call(assistant, method, url, body)
        assert refused.status_code == 403, (url, refused.content)
        assert "Assistants" in refused.json()["detail"]

    # An associate: only on a company they are assigned. Otherwise not found.
    associate = api.as_(cf)
    assert associate.get(f"{T}?company={company.pk}").status_code == 404
    assert associate.get(f"{T}names/?company={company.pk}").status_code == 404
    for method, url, body in writes:
        assert call(associate, method, url, body).status_code == 404, url
    ClientAssignmentFactory(tenant=world["tenant"], user=cf.user, company=company)
    assert card(associate, company)["may_manage"] is True
    assert associate.get(f"{T}?company={other.pk}").status_code == 404

    # A client user, the client owner included, reaches none of it yet.
    for level in ("owner", "manager", "leader_all", "viewer"):
        client = api.as_(who[level])
        assert client.get(f"{T}?company={company.pk}").status_code == 404, level
        assert client.get(f"{T}names/?company={company.pk}").status_code == 404, level
        for method, url, body in writes:
            assert call(client, method, url, body).status_code == 404, (level, url)

    assert not ClientTeam.all_objects.filter(name__in=("Finance", "Revenue")).exists()
    assert Membership.all_objects.get(pk=who["member"].pk).may_create == "projects"
    # Then the same five, by the people who may.
    for method, url, body in writes:
        assert call(associate, method, url, body).status_code in (200, 201), url


@pytest.mark.django_db
def test_tenant_isolation_a_team_is_not_found_from_another_practice_or_company(
        world, tenant_b):
    company, t, who, api = world["company"], world["teams"], world["who"], world["api"]
    stranger = api.as_(MembershipFactory(tenant=tenant_b, role="FF"))
    theirs = ClientCompanyFactory(tenant=tenant_b, name="Initech")
    their_user = MembershipFactory(tenant=tenant_b, role="ECC", client_company=theirs)
    their_team = ClientTeam.all_objects.get(client_company=theirs)

    # Practice B's owner, with practice A's ids.
    assert stranger.get(f"{T}?company={company.pk}").status_code == 404
    assert stranger.get(f"{T}names/?company={company.pk}").status_code == 404
    assert post(stranger, T, {"company": str(company.pk), "name": "Ours now"}
                ).status_code == 404
    assert patch(stranger, f"{T}{t['ops'].pk}/", {"name": "Ours now"}).status_code == 404
    assert post(stranger, f"{T}{t['ops'].pk}/archive/").status_code == 404
    assert post(stranger, f"{T}{their_team.pk}/level/",
                {"membership": str(who["member"].pk), "level": "leader"}).status_code == 404
    assert post(stranger, f"{T}person/", {"membership": str(who["member"].pk),
                                          "leads_all_teams": True}).status_code == 404
    # Practice A's owner, with practice B's.
    practice = api.as_(world["ff"])
    assert practice.get(f"{T}?company={theirs.pk}").status_code == 404
    assert post(practice, f"{T}{their_team.pk}/level/",
                {"membership": str(their_user.pk), "level": "leader"}).status_code == 404
    assert post(practice, f"{T}{t['ops'].pk}/level/",
                {"membership": str(their_user.pk), "level": "leader"}).status_code == 404

    # Two companies of the same practice: a person of one is never put on a
    # team of the other, and a team of one is not a place for the other's work.
    other = ClientCompanyFactory(tenant=world["tenant"], name="Globex Logistics")
    outsider = MembershipFactory(tenant=world["tenant"], role="ECC", client_company=other)
    assert post(practice, f"{T}{t['ops'].pk}/level/",
                {"membership": str(outsider.pk), "level": "manager"}).status_code == 404
    refused = post(practice, "/api/projects/", {
        "title": "Misfiled", "client_company": str(other.pk),
        "client_team": str(t["ops"].pk)})
    assert refused.status_code == 400
    assert "not one of Globex Logistics's" in json.dumps(refused.json())
    assert ClientTeam.all_objects.get(pk=t["ops"].pk).name == "Operations"
    assert not ClientTeamMember.all_objects.filter(
        team=t["ops"], membership__in=[outsider, their_user]).exists()
    assert Membership.all_objects.get(pk=who["member"].pk).leads_all_teams is False


# ================================================================ the Team field

@pytest.mark.django_db
def test_the_practice_files_a_project_and_a_task_on_a_team_and_filters_by_it(world):
    company, t = world["company"], world["teams"]
    practice = world["api"].as_(world["ff"])

    project = make(practice, "/api/projects/", title="Route planning",
                   client_company=str(company.pk), client_team=str(t["sales"].pk))
    assert (project["client_team"], project["client_team_name"]) == (
        str(t["sales"].pk), "Sales")
    unnamed = make(practice, "/api/projects/", title="Year-end", client_company=str(company.pk))
    assert unnamed["client_team_name"] == "Everyone"
    internal = make(practice, "/api/projects/", title="Our own website")
    assert (internal["client_team"], internal["client_team_name"]) == (None, "")
    assert post(practice, "/api/projects/", {"title": "x", "client_team": str(t["ops"].pk)}
                ).status_code == 201, "a team with no company is dropped, not kept"
    assert Project.all_objects.get(title="x").client_team_id is None

    alone = make(practice, "/api/tasks/", title="Book the venue",
                 client_company=str(company.pk), client_team=str(t["ops"].pk))
    assert alone["client_team_name"] == "Operations"
    # In a project a task is on the project's team, whatever it is sent.
    inside = make(practice, "/api/tasks/", title="Draw the routes", project=project["id"],
                  client_company=str(company.pk), client_team=str(t["ops"].pk))
    assert inside["client_team_name"] == "Sales"
    assert Task.all_objects.get(pk=inside["id"]).client_team_id is None

    # Moving a project to another team moves its tasks with it.
    moved = patch(practice, f"/api/projects/{project['id']}/",
                  {"client_team": str(t["ops"].pk)})
    assert moved.status_code == 200 and moved.json()["client_team_name"] == "Operations"
    assert practice.get(f"/api/tasks/{inside['id']}/").json()["client_team_name"] \
        == "Operations"
    moved = patch(practice, f"/api/tasks/{alone['id']}/", {"client_team": str(t["sales"].pk)})
    assert moved.status_code == 200 and moved.json()["client_team_name"] == "Sales"
    assert patch(practice, f"/api/tasks/{alone['id']}/", {"client_team": None}
                 ).json()["client_team_name"] == "Everyone"

    # The filter, beside the one by client: a project by its own team, a task
    # by its project's, and a thing never given a team by its company's default.
    Project.all_objects.filter(pk=unnamed["id"]).update(client_team=None)

    def titles(url):
        return {row["title"] for row in practice.get(url).json()}

    assert titles(f"/api/projects/?client_team={t['ops'].pk}") == {
        "Ops playbook", "Invoice automation", "Route planning"}
    assert titles(f"/api/projects/?client_team={t['everyone'].pk}") == {"Year-end"}
    assert "Draw the routes" in titles(f"/api/tasks/?client_team={t['ops'].pk}")
    assert titles(f"/api/tasks/?client_team={t['sales'].pk}") == {
        "Call the top ten accounts"}
    assert "Book the venue" in titles(f"/api/tasks/?client_team={t['everyone'].pk}")
    assert practice.get("/api/tasks/?client_team=nonsense").status_code == 400

    # What a client user sent is still placed by their own teams, not by the field.
    theirs = make(world["api"].as_(world["who"]["sales_colleague"]), "/api/projects/",
                  title="Their own")
    assert theirs["client_team_name"] == "Sales"


# ================================================================ the invitation

@pytest.mark.django_db
def test_an_invitation_names_the_team_the_level_and_what_they_may_create(
        world, dev_outbox):
    tenant, company, t = world["tenant"], world["company"], world["teams"]
    practice = world["api"].as_(world["ff"])

    def invite(first, **chosen):
        contact = a_contact(tenant, company, first, f"{first.lower()}@northwind.invalid")
        return post(practice, "/api/portal-access/", {"contact": str(contact.pk), **chosen})

    # P7-9: nothing chosen is the default team, Member, projects and tasks.
    plain = invite("Ada")
    assert plain.status_code == 201
    assert (plain.json()["level_label"], plain.json()["may_create"]) == (
        "Member", "projects")
    assert plain.json()["teams"] == [
        {"team": str(t["everyone"].pk), "name": "Everyone", "level": "member"}]
    ada = Membership.all_objects.get(pk=plain.json()["id"])
    assert world["api"].as_(ada).get("/api/tasks/").json() == [], "new people start narrow"

    chosen = invite("Ben", team=str(t["sales"].pk), level="manager", may_create="tasks")
    assert chosen.status_code == 201
    assert chosen.json()["teams"] == [
        {"team": str(t["sales"].pk), "name": "Sales", "level": "manager"}], "and not the default"
    assert (chosen.json()["level_label"], chosen.json()["may_create"]) == ("Manager", "tasks")
    looker = invite("Cy", level="viewer", may_create="nothing")
    assert looker.json()["level_label"] == "Viewer"
    owner = invite("Di", role="FCC")
    assert owner.json()["level_label"] == "Client owner"

    other = ClientCompanyFactory(tenant=tenant, name="Globex Logistics")
    elsewhere = ClientTeam.all_objects.create(tenant=tenant, client_company=other,
                                              name="Dispatch")
    before = Membership.all_objects.count()
    for bad in ({"team": str(elsewhere.pk)}, {"level": "boss"}, {"may_create": "all"},
                {"team": "nonsense"}):
        refused = invite(f"No{len(bad)}{list(bad)[0]}", **bad)
        assert refused.status_code == 400, bad
    assert Membership.all_objects.count() == before, "and nobody was signed in"

    granted = AuditEvent.all_objects.filter(tenant=tenant, verb="portal.access_granted")
    ben = granted.get(target_id=chosen.json()["id"]).payload
    assert (ben["team"], ben["level"], ben["may_create"]) == (
        str(t["sales"].pk), "manager", "tasks")

    # Access taken away and given back: they are where they were.
    membership = Membership.all_objects.get(pk=chosen.json()["id"])
    assert practice.delete(f"/api/portal-access/{membership.pk}/").status_code == 200
    again = post(practice, "/api/portal-access/", {"contact": str(membership.contact_id)})
    assert again.status_code == 201
    assert again.json()["teams"] == chosen.json()["teams"]
    assert again.json()["may_create"] == "tasks"

    # The people already there are listed by level, the client owner by name.
    listed = practice.get(f"/api/portal-access/?company={company.pk}").json()["people"]
    labels = {p["id"]: p["level_label"] for p in listed}
    assert labels[str(world["who"]["owner"].pk)] == "Client owner"
    assert labels[str(world["who"]["leader_all"].pk)] == "Senior leadership"
    assert labels[str(world["who"]["on_no_team"].pk)] == "On no team"
    assert labels[str(world["who"]["viewer"].pk)] == "Viewer"


@pytest.mark.django_db
def test_the_services_refuse_what_the_routes_would_not_send(world):
    t, who = world["teams"], world["who"]
    with pytest.raises(teams.TeamError):
        teams.set_person(world["ff"], actor=None, may_create="goals")
    with pytest.raises(teams.TeamError):
        teams.archive_team(t["everyone"], actor=None)
    with pytest.raises(teams.TeamError):
        teams.set_level(t["ops"], world["ff"], "manager", actor=None)
    assert teams.team_of_company(world["company"], "not-an-id") is None
    assert teams.team_of_company(world["company"], t["ops"].pk) == t["ops"]
    # The same level again is no change, and is not audited.
    teams.set_level(t["ops"], who["member"], "member", actor=None)
    assert not AuditEvent.all_objects.filter(verb="client_team.level_set").exists()
