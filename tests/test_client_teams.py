"""P7 phase 1 — client teams and levels (`docs/p7_client_teams_permissions.md`).

Phase 1 is the tables, the data step and the rule, with every portal user a
Manager of their company's default team, so that nobody's portal changes.
These hold four things:

- **the table of §2.1, a level at a time**, through the routes a portal user
  really calls: one parametrized case is one row of it;
- **what no level widens** (P7-4): a hidden task and the practice's own work;
- **the data step**: after it, every portal user reaches exactly what they
  reached before, id for id, and may change exactly what they could;
- **isolation**: a team gives nothing to anyone outside its own company.

Nothing here sets a level through a route: there is none until phase 2. The
tests place people with `apps.work.teams`, which is what phase 2 will call.
"""

from __future__ import annotations

import json

import pytest
from django.apps import apps as live_apps

from apps.crm.models import Task
from apps.tenancy.models import MayCreate, Membership
from apps.work import permissions as work_perms
from apps.work import team_backfill, teams
from apps.work.models import ClientTeam, ClientTeamMember, Goal, Project

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, ContactFactory, MembershipFactory

L = ClientTeamMember.Level


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def make(client, url, **data):
    response = post(client, url, data)
    assert response.status_code == 201, response.content
    return response.json()


def only(membership, team, level):
    """On this team at this level, and on no other."""
    ClientTeamMember.all_objects.filter(membership=membership).delete()
    if team is not None:
        teams.place(team, membership, level)
    return membership


class Asking:
    """What `client_scope` needs of a request."""

    def __init__(self, membership):
        self.membership = membership


@pytest.fixture
def world(seeded_tenant, ff, api):
    """Northwind Foods, with two teams beside its default one, a person at
    each level, and work on each team.

    "Their team" in the table is Operations; "another team" is Sales.
    """
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Northwind Foods", seat_count=20)

    def person(role="ECC"):
        return MembershipFactory(tenant=tenant, role=role, client_company=company)

    owner = person("FCC")
    everyone = ClientTeam.all_objects.get(client_company=company, is_default=True)
    ops = ClientTeam.all_objects.create(tenant=tenant, client_company=company,
                                        name="Operations")
    sales = ClientTeam.all_objects.create(tenant=tenant, client_company=company,
                                          name="Sales")
    who = {
        "owner": owner,
        "viewer": only(person(), everyone, L.VIEWER),
        "member": only(person(), ops, L.MEMBER),
        "manager": only(person(), ops, L.MANAGER),
        "leader": only(person(), ops, L.LEADER),
        "leader_all": only(person(), None, None),
        "on_no_team": only(person(), None, None),
        "ops_colleague": only(person(), ops, L.MEMBER),
        "sales_colleague": only(person(), sales, L.MEMBER),
    }
    Membership.all_objects.filter(pk=who["leader_all"].pk).update(leads_all_teams=True)
    who["leader_all"].refresh_from_db()

    practice = api.as_(ff)
    goal = make(practice, "/api/goals/", title="Cut order-to-cash to 20 days",
                client_company=str(company.pk))
    # A client's project is on its maker's team.
    p_ops = make(api.as_(who["ops_colleague"]), "/api/projects/", title="Ops playbook")
    p_sales = make(api.as_(who["sales_colleague"]), "/api/projects/", title="Sales playbook")
    p_practice = make(practice, "/api/projects/", title="Invoice automation",
                      goal=goal["id"], client_company=str(company.pk))
    Project.all_objects.filter(pk=p_practice["id"]).update(client_team=ops)

    def task(client, title, **data):
        return make(client, "/api/tasks/", title=title, **data)["id"]

    tasks = {
        "ops, of a colleague": task(
            api.as_(who["ops_colleague"]), "Write the receiving checklist",
            project=p_ops["id"], assignee=str(who["ops_colleague"].user_id)),
        "ops, of the member": task(
            practice, "Count the cold room", project=p_ops["id"],
            client_company=str(company.pk), assignee=str(who["member"].user_id)),
        "ops, in no project": task(
            api.as_(who["ops_colleague"]), "Order pallet wrap",
            assignee=str(who["ops_colleague"].user_id)),
        "sales": task(
            api.as_(who["sales_colleague"]), "Call the top ten accounts",
            project=p_sales["id"], assignee=str(who["sales_colleague"].user_id)),
        "of the practice": task(
            practice, "Map the current process", project=p_practice["id"],
            client_company=str(company.pk), assignee=str(ff.user_id)),
        "hidden": task(
            practice, "Draft the renewal terms", client_company=str(company.pk),
            is_client_visible=False),
    }
    return {"tenant": tenant, "company": company, "who": who, "api": api, "ff": ff,
            "teams": {"everyone": everyone, "ops": ops, "sales": sales},
            "goal": goal["id"], "tasks": tasks,
            "projects": {"ops": p_ops["id"], "sales": p_sales["id"],
                         "of the practice": p_practice["id"]}}


def named(world, kind, ids) -> set:
    names = {pk: name for name, pk in world[kind].items()}
    return {names[pk] for pk in ids if pk in names}


ALL_TASKS = {"ops, of a colleague", "ops, of the member", "ops, in no project", "sales",
             "of the practice"}                                   # never "hidden"
ALL_PROJECTS = {"ops", "sales", "of the practice"}
OPS_TASKS = {"ops, of a colleague", "ops, of the member", "ops, in no project"}

#: §2.1, a row a level: what they see, what they may change, and what else
#: they may do. "of the practice" is never in a "changes" set, at any level.
TABLE = {
    "viewer": dict(sees=ALL_TASKS, projects=ALL_PROJECTS, changes=set(),
                   changes_projects=set(), adds=False, comments=False, goals=False),
    "member": dict(sees={"ops, of the member"}, projects={"ops"},
                   changes={"ops, of the member"}, changes_projects=set(),
                   adds=True, comments=True, goals=False),
    "manager": dict(sees=ALL_TASKS, projects=ALL_PROJECTS, changes=OPS_TASKS,
                    changes_projects={"ops"}, adds=True, comments=True, goals=False),
    "leader": dict(sees=ALL_TASKS, projects=ALL_PROJECTS, changes=OPS_TASKS,
                   changes_projects={"ops"}, adds=True, comments=True, goals=True),
    "leader_all": dict(sees=ALL_TASKS, projects=ALL_PROJECTS,
                       changes=OPS_TASKS | {"sales"}, changes_projects={"ops", "sales"},
                       adds=True, comments=True, goals=True),
    "owner": dict(sees=ALL_TASKS, projects=ALL_PROJECTS, changes=OPS_TASKS | {"sales"},
                  changes_projects={"ops", "sales"}, adds=True, comments=True,
                  goals=True),
    # §1.1: on no team at all is a member with nothing assigned.
    "on_no_team": dict(sees=set(), projects=set(), changes=set(),
                       changes_projects=set(), adds=False, comments=False, goals=False),
}


@pytest.mark.django_db
@pytest.mark.parametrize("level", sorted(TABLE))
def test_role_boundaries_each_level_sees_and_changes_what_its_row_says(world, level):
    row, me = TABLE[level], world["who"][level]
    client = world["api"].as_(me)

    # Goals: everyone sees every goal of the company.
    assert [g["id"] for g in client.get("/api/goals/").json()] == [world["goal"]]

    listed = client.get("/api/tasks/").json()
    assert named(world, "tasks", [t["id"] for t in listed]) == row["sees"]
    assert world["tasks"]["hidden"] not in [t["id"] for t in listed]
    assert {name for name in row["sees"]
            if next(t for t in listed if t["id"] == world["tasks"][name])["may_edit"]} \
        == row["changes"], "what the list says they may change"
    assert named(world, "projects",
                 [p["id"] for p in client.get("/api/projects/").json()]) == row["projects"]

    for name, pk in world["tasks"].items():
        got = client.get(f"/api/tasks/{pk}/")
        assert got.status_code == (200 if name in row["sees"] else 404), name
        changed = patch(client, f"/api/tasks/{pk}/", {"status": "in_progress"})
        expected = (200 if name in row["changes"]
                    else 403 if name in row["sees"] else 404)      # out of scope: not found
        assert changed.status_code == expected, (name, changed.content)
        # Steps carry no permissions of their own (§2.6): as the task.
        step = post(client, f"/api/tasks/{pk}/checklist/", {"text": "Check it twice"})
        assert step.status_code == (201 if name in row["changes"] else expected), name
        # A shared comment: whoever sees it, unless they only look.
        said = post(client, "/api/comments/", {"task": pk, "body": "Seen."})
        assert said.status_code == (404 if name not in row["sees"]
                                    else 201 if row["comments"] else 403), name

    for name, pk in world["projects"].items():
        changed = patch(client, f"/api/projects/{pk}/", {"title": f"{name}, renamed"})
        expected = (200 if name in row["changes_projects"]
                    else 403 if name in row["projects"] else 404)
        assert changed.status_code == expected, (name, changed.content)

    # Creating: by "may create", which is "projects and tasks" for everyone
    # until someone sets it, and nothing for someone who only looks.
    added = post(client, "/api/tasks/", {"title": "A new task"})
    assert added.status_code == (201 if row["adds"] else 403), added.content
    project = post(client, "/api/projects/", {"title": "A new project"})
    assert project.status_code == (201 if row["adds"] else 403), project.content

    # Goals (phase 4): a senior leader and the client owner change one; nobody
    # here may add one, since nobody has "Goals too".
    goal = Goal.all_objects.get(pk=world["goal"])
    assert work_perms.client_may_edit_goal(Asking(me), goal) is row["goals"]
    assert patch(client, f"/api/goals/{world['goal']}/", {"title": "x"}).status_code == \
        (200 if row["goals"] else 403)
    assert post(client, "/api/goals/", {"title": "A goal of ours"}).status_code == 403


@pytest.mark.django_db
def test_role_boundaries_new_work_lands_on_its_makers_team(world):
    who, t = world["who"], world["teams"]
    client = world["api"].as_

    alone = make(client(who["member"]), "/api/tasks/", title="Label the racks")
    assert Task.all_objects.get(pk=alone["id"]).client_team_id == t["ops"].pk
    # In a project a task follows the project, and holds no team of its own.
    inside = make(client(who["ops_colleague"]), "/api/tasks/", title="Train the night shift",
                  project=world["projects"]["ops"])
    assert Task.all_objects.get(pk=inside["id"]).client_team_id is None
    mine = make(client(who["sales_colleague"]), "/api/projects/", title="Q1 pipeline")
    assert Project.all_objects.get(pk=mine["id"]).client_team_id == t["sales"].pk
    # The client owner is on every team: the one they name, else the default.
    owners = make(client(who["owner"]), "/api/tasks/", title="Board pack")
    assert Task.all_objects.get(pk=owners["id"]).client_team_id == t["everyone"].pk
    named_team = make(client(who["owner"]), "/api/tasks/", title="Sales kickoff",
                      client_team=str(t["sales"].pk))
    assert Task.all_objects.get(pk=named_team["id"]).client_team_id == t["sales"].pk

    # Not on another team: a manager sees Sales' project and adds nothing to it.
    refused = post(client(who["manager"]), "/api/tasks/",
                   {"title": "Help Sales", "project": world["projects"]["sales"]})
    assert refused.status_code == 403 and "another team's" in refused.json()["detail"]
    refused = post(client(who["member"]), "/api/tasks/",
                   {"title": "For Sales", "client_team": str(t["sales"].pk)})
    assert refused.status_code == 403
    # A member cannot name a project they do not see: it is not there for them.
    assert post(client(who["member"]), "/api/tasks/",
                {"title": "x", "project": world["projects"]["sales"]}).status_code == 400

    # The practice's own new work for a client starts on the default team.
    practice = world["api"].as_(world["ff"])
    project = make(practice, "/api/projects/", title="Month-end close",
                   client_company=str(world["company"].pk))
    assert Project.all_objects.get(pk=project["id"]).client_team_id == t["everyone"].pk
    task = make(practice, "/api/tasks/", title="Send the agenda",
                client_company=str(world["company"].pk))
    assert Task.all_objects.get(pk=task["id"]).client_team_id == t["everyone"].pk
    internal = make(practice, "/api/tasks/", title="Renew the domain")
    assert Task.all_objects.get(pk=internal["id"]).client_team_id is None


@pytest.mark.django_db
def test_role_boundaries_a_task_is_handed_to_someone_on_its_team(world):
    who, client = world["who"], world["api"].as_
    mine = world["tasks"]["ops, of the member"]

    def hand(me, task, to):
        return patch(client(who[me]), f"/api/tasks/{task}/",
                     {"assignee": str(who[to].user_id)})

    # A member, within their team (P7-6). It leaves their list: they did not make it.
    assert hand("member", mine, "sales_colleague").status_code == 400
    assert hand("member", mine, "viewer").status_code == 400, "never to someone who only looks"
    assert hand("member", mine, "on_no_team").status_code == 400
    assert hand("member", mine, "ops_colleague").status_code == 200
    assert client(who["member"]).get(f"/api/tasks/{mine}/").status_code == 404
    # A manager, to anyone on the team; a senior leader of every team, and
    # the client owner, across teams.
    assert hand("manager", mine, "sales_colleague").status_code == 400
    assert hand("manager", mine, "member").status_code == 200
    assert hand("leader_all", mine, "sales_colleague").status_code == 200
    assert hand("owner", mine, "ops_colleague").status_code == 200
    assert hand("owner", mine, "viewer").status_code == 400
    # Never to someone at the practice (FR-3.9a.2), at any level.
    refused = patch(client(who["owner"]), f"/api/tasks/{mine}/",
                    {"assignee": str(world["ff"].user_id)})
    assert refused.status_code == 400


@pytest.mark.django_db
def test_role_boundaries_a_manager_does_not_delete_a_colleagues_task(world):
    """P7-13: delete stays with whoever made the thing."""
    who, client = world["who"], world["api"].as_
    colleagues = world["tasks"]["ops, of a colleague"]
    for level in ("manager", "leader", "leader_all"):
        refused = client(who[level]).delete(f"/api/tasks/{colleagues}/")
        assert refused.status_code == 403 and "client owner" in refused.json()["detail"]
        cancelled = patch(client(who[level]), f"/api/tasks/{colleagues}/",
                          {"status": "cancelled"})
        assert cancelled.status_code == 200, level
    # The client owner may, as for a project; and never the practice's task.
    assert client(who["owner"]).get(f"/api/tasks/{colleagues}/").json()["may_delete"] is True
    practices = world["tasks"]["of the practice"]
    assert client(who["owner"]).delete(f"/api/tasks/{practices}/").status_code == 403
    members = world["tasks"]["ops, of the member"]          # made by the practice, assigned
    assert client(who["owner"]).delete(f"/api/tasks/{members}/").status_code == 403
    assert Task.all_objects.filter(pk__in=[practices, members],
                                   deleted_at__isnull=True).count() == 2
    alone = world["tasks"]["ops, in no project"]
    assert client(who["owner"]).delete(f"/api/tasks/{alone}/").status_code == 204
    assert client(who["ops_colleague"]).delete(f"/api/tasks/{colleagues}/").status_code == 204

    # The same for a project (Bryan, 2026-10-13): its maker or the client
    # owner deletes it; a manager or a senior leader cancels it. Before P7
    # any client user of the company could delete a colleague's project.
    ops, sales = world["projects"]["ops"], world["projects"]["sales"]
    for level in ("viewer", "manager", "leader", "leader_all", "sales_colleague"):
        refused = client(who[level]).delete(f"/api/projects/{ops}/")
        assert refused.status_code in (403, 404), level
        assert Project.all_objects.get(pk=ops).deleted_at is None, level
    assert "set it to cancelled" in client(who["manager"]).delete(
        f"/api/projects/{ops}/").json()["detail"]
    cancelled = patch(client(who["manager"]), f"/api/projects/{ops}/",
                      {"status_override": "cancelled"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client(who["ops_colleague"]).delete(f"/api/projects/{ops}/").status_code == 200
    assert client(who["owner"]).delete(f"/api/projects/{sales}/").status_code == 200
    # The practice's project is the practice's, the client owner's included.
    theirs = world["projects"]["of the practice"]
    assert client(who["owner"]).delete(f"/api/projects/{theirs}/").status_code == 403


@pytest.mark.django_db
def test_role_boundaries_a_project_that_is_theirs_and_the_work_in_it(world):
    """"Theirs" for a project is made by them, or theirs as its client-side
    owner (P7-3); and the tasks in a project that is theirs are theirs."""
    who, client = world["who"], world["api"].as_
    maker = who["ops_colleague"]
    assert named(world, "tasks", [t["id"] for t in client(maker).get("/api/tasks/").json()]) \
        == OPS_TASKS, "their own two, and the member's task in the project they made"
    renamed = patch(client(maker), f"/api/projects/{world['projects']['ops']}/",
                    {"title": "Ops playbook, v2"})
    assert renamed.status_code == 200

    # The client-side owner of a project the practice made sees it and its
    # client-visible tasks. It stays the practice's to change (P7-4).
    contact = ContactFactory(tenant=world["tenant"], company=world["company"])
    Membership.all_objects.filter(pk=who["member"].pk).update(contact=contact)
    Project.all_objects.filter(pk=world["projects"]["of the practice"]).update(
        client_owner_contact=contact)
    member = Membership.all_objects.get(pk=who["member"].pk)
    seen = client(member).get("/api/projects/").json()
    assert named(world, "projects", [p["id"] for p in seen]) == {"ops", "of the practice"}
    assert named(world, "tasks", [t["id"] for t in client(member).get("/api/tasks/").json()]) \
        == {"ops, of the member", "of the practice"}
    assert patch(client(member), f"/api/projects/{world['projects']['of the practice']}/",
                 {"title": "Mine now"}).status_code == 403
    assert patch(client(member), f"/api/tasks/{world['tasks']['of the practice']}/",
                 {"status": "done"}).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("setting, task, project, rule", [
    (MayCreate.NOTHING, 403, 403, set()),
    (MayCreate.TASKS, 201, 403, {"task"}),
    (MayCreate.PROJECTS, 201, 201, {"task", "project"}),
    (MayCreate.GOALS, 201, 201, {"task", "project", "goal"}),
])
def test_role_boundaries_may_create_is_its_own_setting(world, setting, task, project, rule):
    """§3: separate from the level. A member may be given projects; a manager
    held to tasks; and "nothing" still leaves them their assigned work."""
    for level in ("member", "manager"):
        me = world["who"][level]
        Membership.all_objects.filter(pk=me.pk).update(may_create=setting)
        me.refresh_from_db()
        client = world["api"].as_(me)
        made = post(client, "/api/tasks/", {"title": "One more"})
        assert made.status_code == task, (level, made.content)
        if task == 403:
            assert "not been set up to add tasks" in made.json()["detail"]
        assert post(client, "/api/projects/", {"title": "One more"}).status_code == project
        assert {kind for kind in ("task", "project", "goal")
                if work_perms.client_may_create(Asking(me), kind)} == rule
        # Goals (phase 4): made by "Goals too", and by nothing less.
        assert post(client, "/api/goals/", {"title": "Ours"}).status_code == \
            (201 if "goal" in rule else 403)
    # Assigned work is still theirs to do.
    member = world["api"].as_(world["who"]["member"])
    done = patch(member, f"/api/tasks/{world['tasks']['ops, of the member']}/",
                 {"status": "done"})
    assert done.status_code == 200
    # Someone who only looks makes nothing, whatever their setting says.
    viewer = world["who"]["viewer"]
    Membership.all_objects.filter(pk=viewer.pk).update(may_create=MayCreate.GOALS)
    viewer.refresh_from_db()
    assert not work_perms.client_may_create(Asking(viewer), "task")


@pytest.mark.django_db
def test_a_goals_progress_is_the_same_for_everyone_who_sees_the_goal(world):
    """Decided 10/12: the value report keeps its audience. A member's list is
    their own work; the report's arithmetic is the company's."""
    member, manager = Asking(world["who"]["member"]), Asking(world["who"]["manager"])
    every = Task.all_objects.filter(tenant=world["tenant"])
    assert set(work_perms.report_task_queryset_for(member, every)) \
        == set(work_perms.report_task_queryset_for(manager, every)) \
        == set(work_perms.task_queryset_for(manager, every))
    assert set(work_perms.task_queryset_for(member, every)) \
        < set(work_perms.report_task_queryset_for(member, every))
    report = world["api"].as_(world["who"]["member"]).get("/api/value-report/")
    assert report.status_code == 200


@pytest.mark.django_db
def test_a_person_on_two_teams_has_the_higher_level_on_each_and_a_viewer_row_adds_sight(world):
    me, t = world["who"]["member"], world["teams"]          # a member of Operations
    teams.place(t["sales"], me, L.MANAGER)
    client = world["api"].as_(me)
    listed = {x["id"]: x for x in client.get("/api/tasks/").json()}
    assert named(world, "tasks", listed) == ALL_TASKS
    assert listed[world["tasks"]["sales"]]["may_edit"] is True
    assert listed[world["tasks"]["ops, of a colleague"]]["may_edit"] is False
    assert listed[world["tasks"]["ops, of the member"]]["may_edit"] is True

    only(me, t["ops"], L.MEMBER)
    teams.place(t["everyone"], me, L.VIEWER)
    listed = {x["id"]: x for x in world["api"].as_(me).get("/api/tasks/").json()}
    assert named(world, "tasks", listed) == ALL_TASKS
    assert {name for name in ALL_TASKS if listed[world["tasks"][name]]["may_edit"]} \
        == {"ops, of the member"}

    # An archived team gives nothing: they are on no team, which is a member
    # who sees the work that is theirs and changes none of it (§1.1).
    only(me, t["sales"], L.MANAGER)
    from django.utils import timezone
    ClientTeam.all_objects.filter(pk=t["sales"].pk).update(archived_at=timezone.now())
    listed = world["api"].as_(me).get("/api/tasks/").json()
    assert [(x["id"], x["may_edit"]) for x in listed] == [
        (world["tasks"]["ops, of the member"], False)]


# ============================================================== isolation

@pytest.mark.django_db
def test_tenant_isolation_a_team_gives_nothing_outside_its_own_company(world, tenant_b):
    tenant, t = world["tenant"], world["teams"]
    other = ClientCompanyFactory(tenant=tenant, name="Globex Logistics")
    outsider = MembershipFactory(tenant=tenant, role="ECC", client_company=other)
    stranger = MembershipFactory(tenant=tenant_b, role="ECC", client_company=ClientCompanyFactory(
        tenant=tenant_b, name="Initech"))
    staff = world["ff"]

    # Nobody but a client user of the team's own company can be put on it.
    for wrong in (outsider, stranger, staff):
        with pytest.raises(ValueError):
            teams.place(t["ops"], wrong, L.MANAGER)
    # And a row that got there some other way is read past.
    ClientTeamMember.all_objects.create(tenant=tenant, team=t["ops"], membership=outsider,
                                        level=L.LEADER)
    scope = work_perms.client_scope(Asking(outsider))
    assert t["ops"].pk not in scope.levels and not scope.runs(t["ops"].pk)
    client = world["api"].as_(outsider)
    assert client.get("/api/tasks/").json() == [] and client.get("/api/projects/").json() == []
    for pk in world["tasks"].values():
        assert client.get(f"/api/tasks/{pk}/").status_code == 404
        assert patch(client, f"/api/tasks/{pk}/", {"status": "done"}).status_code == 404
    # Naming another company's team for new work is refused, and nothing is made.
    before = Task.all_objects.count()
    refused = post(client, "/api/tasks/", {"title": "x", "client_team": str(t["ops"].pk)})
    assert refused.status_code == 403 and Task.all_objects.count() == before
    # Each company has its own default team, and a person is on their own.
    assert ClientTeamMember.all_objects.get(
        membership=outsider, team__is_default=True).team.client_company_id == other.pk
    assert ClientTeam.all_objects.filter(tenant=tenant_b).count() == 1
    assert not ClientTeamMember.all_objects.filter(
        membership=stranger, team__tenant=tenant).exists()


# ============================================== a portal user is always placed

@pytest.mark.django_db
def test_a_new_portal_user_is_a_manager_of_the_default_team(seeded_tenant, ff):
    """P7-1, §7: what every client user could see and do before P7. Without
    it a person invited after the release would see less than everyone
    invited before. Phase 2's invitation form chooses, and starts at Member."""
    company = ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods")
    assert not ClientTeam.all_objects.filter(client_company=company).exists()
    first = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    second = MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=company)
    [team] = ClientTeam.all_objects.filter(client_company=company)
    assert (team.name, team.is_default) == ("Everyone", True)
    assert set(ClientTeamMember.all_objects.filter(team=team)
               .values_list("membership_id", "level")) == {
        (first.pk, "manager"), (second.pk, "manager")}
    assert (second.may_create, second.leads_all_teams) == ("projects", False)
    # Nobody at the practice is on a team.
    assert not ClientTeamMember.all_objects.filter(membership=ff).exists()

    # A level someone chose is left alone by any later save...
    teams.place(team, second, L.MEMBER)
    second.save()
    assert ClientTeamMember.all_objects.get(membership=second).level == "member"
    # ...and a sign-in taken away and given back is where it was.
    from django.utils import timezone
    second.revoked_at = timezone.now()
    second.save(update_fields=["revoked_at", "updated_at"])
    second.revoked_at = None
    second.save(update_fields=["revoked_at", "updated_at"])
    assert ClientTeamMember.all_objects.get(membership=second).level == "member"


# ============================================================ the data step

def as_before_p7(tenant, company, membership) -> dict:
    """What a client user reached before P7, written out again here so the
    data step is held to the old rule and not to the new one's own answer:
    every project of their company; every client-visible task of it; and a
    task is theirs to change when a client made it or a client-side user has
    it (FR-3.9a)."""
    client_users = set(Membership.all_objects.filter(
        tenant=tenant, client_company=company, role__in=("FCC", "ECC"),
        revoked_at__isnull=True).values_list("user_id", flat=True))
    tasks = Task.all_objects.filter(tenant=tenant, client_company=company,
                                    is_client_visible=True, deleted_at__isnull=True)
    projects = Project.all_objects.filter(tenant=tenant, client_company=company,
                                          deleted_at__isnull=True)
    return {
        "tasks": {str(t.pk): t.created_by_client or t.assignee_id in client_users
                  for t in tasks},
        "projects": {str(p.pk): p.created_by_client for p in projects},
    }


def reach(api, membership) -> dict:
    client = api.as_(membership)
    projects = {p["id"] for p in client.get("/api/projects/").json()}
    return {
        "tasks": {t["id"]: t["may_edit"] for t in client.get("/api/tasks/").json()},
        "projects": {pk: patch(client, f"/api/projects/{pk}/", {}).status_code == 200
                     for pk in projects},
    }


@pytest.mark.django_db
def test_the_data_step_leaves_every_portal_user_reaching_exactly_what_they_did(world):
    tenant, company, api = world["tenant"], world["company"], world["api"]
    people = list(Membership.all_objects.filter(tenant=tenant, client_company=company))
    assert len(people) == 9
    quiet = ClientCompanyFactory(tenant=tenant, name="No Portal Yet")      # work, no users
    make(api.as_(world["ff"]), "/api/tasks/", title="Send the proposal",
         client_company=str(quiet.pk))
    untouched = ClientCompanyFactory(tenant=tenant, name="Nothing At All")

    # As the tables stood before P7: no team anywhere, nothing on one.
    Task.all_objects.update(client_team=None)
    Project.all_objects.update(client_team=None)
    ClientTeam.all_objects.all().delete()
    Membership.all_objects.update(leads_all_teams=False)
    assert not ClientTeamMember.all_objects.exists()

    plan = team_backfill.plan(live_apps)
    assert [(row["company"], len(row["people"]), row["projects"], row["tasks_alone"],
             row["tasks_in_projects"]) for row in plan] == [
        ("No Portal Yet", 0, 0, 1, 0), ("Northwind Foods", 9, 3, 2, 4)]
    said = team_backfill.say(plan)
    assert "9 on it as Manager" in said and "Nothing At All" not in said
    assert not ClientTeam.all_objects.exists(), "the plan writes nothing"

    done = team_backfill.teams_people_and_projects(live_apps)
    assert done == {"teams": 2, "people": 9, "projects": 3}
    assert team_backfill.tasks(live_apps) == {"tasks": 3}
    # Twice is the same as once.
    assert team_backfill.teams_people_and_projects(live_apps) == {
        "teams": 2, "people": 0, "projects": 0}
    assert team_backfill.tasks(live_apps) == {"tasks": 0}

    [team] = ClientTeam.all_objects.filter(client_company=company)
    assert (team.name, team.is_default, team.archived_at) == ("Everyone", True, None)
    assert set(ClientTeamMember.all_objects.filter(team=team)
               .values_list("membership_id", "level")) == {(m.pk, "manager") for m in people}
    assert not Project.all_objects.filter(client_company=company,
                                          client_team__isnull=True).exists()
    assert {(t.project_id is None, t.client_team_id is None)
            for t in Task.all_objects.filter(client_company=company)} == {
        (True, False), (False, True)}, "alone: on the team; in a project: follows it"
    assert not ClientTeam.all_objects.filter(client_company=untouched).exists()
    assert set(Membership.all_objects.values_list("may_create", "leads_all_teams")) == {
        ("projects", False)}

    # Every one of them reaches exactly what they reached, id for id, and may
    # change exactly what they could.
    for person in people:
        assert reach(api, Membership.all_objects.get(pk=person.pk)) \
            == as_before_p7(tenant, company, person), person.role

    # And it can be taken back.
    team_backfill.undo_tasks(live_apps)
    team_backfill.undo_teams(live_apps)
    assert not ClientTeam.all_objects.exists() and not ClientTeamMember.all_objects.exists()
    assert not Task.all_objects.filter(client_team__isnull=False).exists()


@pytest.mark.django_db
def test_the_dry_run_prints_the_plan_and_writes_nothing(world, capsys):
    from django.core.management import call_command

    before = (ClientTeam.all_objects.count(), ClientTeamMember.all_objects.count())
    call_command("client_teams_dry_run")
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN. Nothing is written.")
    assert "Northwind Foods" in out and "before: 9 portal user(s)" in out
    assert "after:  one team, \"Everyone\" (the default); 9 on it as Manager" in out
    assert (ClientTeam.all_objects.count(), ClientTeamMember.all_objects.count()) == before


@pytest.mark.django_db
def test_the_script_for_a_database_without_p7_says_what_the_command_says(world, capsys):
    """Production is asked before the release, by code that has no teams yet:
    `scripts/p7_phase1_dry_run.py`, piped into its shell. It must read what
    the migration will do, word for word."""
    import runpy
    from pathlib import Path

    from django.core.management import call_command

    # As before P7, which is when it is run: nobody placed, nothing on a team.
    ClientTeam.all_objects.all().delete()
    call_command("client_teams_dry_run")
    command = capsys.readouterr().out
    before = (ClientTeam.all_objects.count(), ClientTeamMember.all_objects.count())
    runpy.run_path(str(Path(__file__).parent.parent / "scripts" / "p7_phase1_dry_run.py"))
    script = capsys.readouterr().out
    assert script == command and "Northwind Foods" in script
    assert (ClientTeam.all_objects.count(), ClientTeamMember.all_objects.count()) == before
    source = (Path(__file__).parent.parent / "scripts" / "p7_phase1_dry_run.py").read_text()
    assert "team_backfill" not in source.split('"""')[2], "it imports nothing P7 added"
    assert "ClientTeam" not in source and "client_team" not in source.split('"""')[2]

