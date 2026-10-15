"""P7 phase 4 — the portal for members, managers, senior leaders and viewers
(`docs/p7_client_teams_permissions.md` §2, §3, §4.3).

What the portal is told so it offers only what a person may do, and the
routes that hold it on their own:

- **What each person may do,** on `/api/me` (`portal`), and their level as
  their shown role (P7-10), the acting banner's included.
- **Mine / My team / Everyone** on the task and project lists: it narrows,
  never widens.
- **Why a thing is read-only,** once, in words, on its payload.
- **Who a task may be handed to,** for a team.
- **Goals:** added by "Goals too", changed by senior leadership and the
  client owner (title, description, target date only), deleted by their
  maker or the client owner.
- **Isolation:** nothing here reaches another company or practice.
"""

from __future__ import annotations

import pytest

from apps.tenancy.models import AuditEvent, Membership
from apps.work.models import ClientTeamMember, Goal

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory
from .test_client_teams import (  # noqa: F401
    ALL_TASKS, OPS_TASKS, named, patch, post, world,
)

L = ClientTeamMember.Level


def me(client):
    response = client.get("/api/me")
    assert response.status_code == 200, response.content
    return response.json()


def tasks(world, client, query=""):
    response = client.get(f"/api/tasks/{query}")
    assert response.status_code == 200, response.content
    return response.json()


def give(membership, may_create):
    Membership.all_objects.filter(pk=membership.pk).update(may_create=may_create)
    membership.refresh_from_db()


# =========================================================== what the portal is told

@pytest.mark.django_db
def test_each_person_is_told_what_they_may_do_and_is_called_by_their_level(world):
    who, api, t = world["who"], world["api"], world["teams"]
    expected = {
        # level: (shown as, may create task/project/goal, edits goals, the switch)
        "owner": ("Client owner", (True, True, False), True, True),
        "member": ("Member", (True, True, False), False, False),
        "manager": ("Manager", (True, True, False), False, True),
        "leader": ("Senior leadership", (True, True, False), True, True),
        "leader_all": ("Senior leadership", (True, True, False), True, True),
        "viewer": ("Viewer", (False, False, False), False, False),
        "on_no_team": ("On no team", (False, False, False), False, False),
    }
    for level, (label, creates, goals, switch) in expected.items():
        data = me(api.as_(who[level]))
        assert data["role_label"] == label, level
        portal = data["portal"]
        assert portal["level_label"] == label
        assert (portal["may_create"]["task"], portal["may_create"]["project"],
                portal["may_create"]["goal"]) == creates, level
        assert (portal["edits_goals"], portal["has_teams_view"]) == (goals, switch), level
        assert portal["may_propose_goal"] is (level == "owner"), level
    # The teams new work may go on: their own; everyone's for the owner.
    assert [x["name"] for x in me(api.as_(who["member"]))["portal"]["teams"]] == [
        "Operations"]
    assert [x["name"] for x in me(api.as_(who["owner"]))["portal"]["teams"]] == [
        "Everyone", "Operations", "Sales"]
    assert me(api.as_(who["viewer"]))["portal"]["teams"] == []
    # "Goals too" moves the owner from proposing to adding.
    give(who["owner"], "goals")
    portal = me(api.as_(who["owner"]))["portal"]
    assert (portal["may_create"]["goal"], portal["may_propose_goal"]) == (True, False)
    # The practice is told nothing of the kind.
    assert me(api.as_(world["ff"]))["portal"] is None
    assert t["ops"].name == "Operations"


@pytest.mark.django_db
def test_the_acting_banner_names_a_client_user_by_their_level(world):
    who = world["who"]
    practice = world["api"].as_(world["ff"])
    assert post(practice, "/api/act-as/", {"membership": str(who["manager"].pk)}
                ).status_code == 201
    data = me(practice)
    assert (data["acting"]["as_label"], data["role_label"]) == ("Manager", "Manager")
    assert "Client team member" not in str(data)
    assert post(practice, "/api/act-as/stop/").status_code == 200


# ==================================================== Mine / My team / Everyone

@pytest.mark.django_db
def test_role_boundaries_mine_my_team_and_everyone_narrow_and_never_widen(world):
    who, api = world["who"], world["api"]
    manager = api.as_(who["manager"])
    every = named(world, "tasks", [x["id"] for x in tasks(world, manager)])
    assert every == ALL_TASKS
    assert named(world, "tasks", [x["id"] for x in tasks(world, manager, "?view=everyone")]
                 ) == ALL_TASKS
    # Their team: Operations' work, the practice's project on it included.
    assert named(world, "tasks", [x["id"] for x in tasks(world, manager, "?view=team")]
                 ) == OPS_TASKS | {"of the practice"}
    assert named(world, "tasks", [x["id"] for x in tasks(world, manager, "?view=mine")]
                 ) == set()
    projects = manager.get("/api/projects/?view=team").json()
    assert named(world, "projects", [p["id"] for p in projects]) == {"ops", "of the practice"}

    # A member asking for everyone gets what they see: their own.
    member = api.as_(who["member"])
    for view in ("mine", "team", "everyone"):
        assert named(world, "tasks", [x["id"] for x in tasks(world, member, f"?view={view}")]
                     ) == {"ops, of the member"}, view
    # The colleague who made the ops project: it, and its tasks, are theirs.
    colleague = api.as_(who["ops_colleague"])
    assert named(world, "projects", [p["id"] for p in colleague.get(
        "/api/projects/?view=mine").json()]) == {"ops"}

    assert manager.get("/api/tasks/?view=all").status_code == 400
    # The practice's lists take the word and change nothing.
    practice = api.as_(world["ff"])
    assert len(practice.get("/api/tasks/?view=mine").json()) == \
        len(practice.get("/api/tasks/").json())


# ============================================================ why it is read-only

@pytest.mark.django_db
def test_a_thing_seen_and_not_changeable_says_why_once(world):
    who, api, t = world["who"], world["api"], world["tasks"]
    manager = api.as_(who["manager"])
    rows = {x["id"]: x for x in tasks(world, manager)}
    assert (rows[t["sales"]]["may_edit"], rows[t["sales"]]["read_only_line"]) == (
        False, "Only Sales's manager can change this.")
    assert rows[t["of the practice"]]["read_only_line"].startswith(
        "This task is the practice's to change.")
    assert rows[t["ops, of a colleague"]]["read_only_line"] == ""
    # The same sentence is the refusal.
    refused = patch(manager, f"/api/tasks/{t['sales']}/", {"status": "done"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only Sales's manager can change this."

    projects = {p["id"]: p for p in manager.get("/api/projects/").json()}
    sales = projects[world["projects"]["sales"]]
    assert (sales["may_edit"], sales["may_delete"], sales["read_only_line"]) == (
        False, False, "Only Sales's manager can change this.")
    ops = projects[world["projects"]["ops"]]
    assert (ops["may_edit"], ops["may_delete"], ops["read_only_line"]) == (True, False, "")
    assert projects[world["projects"]["of the practice"]]["read_only_line"] == \
        "This project belongs to the practice."
    # The practice's payloads carry none of it.
    practice = api.as_(world["ff"])
    assert "read_only_line" not in practice.get(
        f"/api/projects/{world['projects']['ops']}/").json()
    assert practice.get(f"/api/tasks/{t['sales']}/").json()["read_only_line"] == ""


# ============================================================ who it goes to

@pytest.mark.django_db
def test_role_boundaries_the_people_a_task_may_go_to_are_its_teams(world):
    who, api, team = world["who"], world["api"], world["teams"]

    def offered(level, team_id):
        response = api.as_(who[level]).get(f"/api/portal-people/?team={team_id}")
        assert response.status_code == 200, response.content
        return {row["id"] for row in response.json()}

    ops_people = {str(who[x].user_id) for x in ("member", "manager", "leader",
                                                 "ops_colleague")}
    takes_any = {str(who[x].user_id) for x in ("owner", "leader_all")}
    # A member hands an Operations task to someone who works on Operations.
    assert offered("member", team["ops"].pk) == ops_people | takes_any
    assert str(who["viewer"].user_id) not in offered("owner", team["ops"].pk)
    assert str(who["sales_colleague"].user_id) not in offered("member", team["ops"].pk)
    # The client owner hands work to anyone who takes work.
    assert str(who["sales_colleague"].user_id) in offered("owner", team["ops"].pk)
    # Each is listed by level, not by "Client team member".
    rows = api.as_(who["member"]).get("/api/portal-people/").json()
    labels = {row["id"]: row["label"] for row in rows}
    assert labels[str(who["manager"].user_id)] == "Manager"
    assert labels[str(who["owner"].user_id)] == "Client owner"
    assert labels[str(who["viewer"].user_id)] == "Viewer"
    assert api.as_(who["member"]).get("/api/portal-people/?team=nope").status_code == 400


# ===================================================================== goals

@pytest.mark.django_db
def test_goals_too_adds_a_goal_live_marked_and_the_practice_is_told(world):
    who, api, company = world["who"], world["api"], world["company"]
    give(who["member"], "goals")
    member = api.as_(who["member"])
    made = post(member, "/api/goals/", {"title": "Ship same day", "description": "Ours",
                                        "target_date": "2026-12-31"})
    assert made.status_code == 201, made.content
    goal = Goal.all_objects.get(pk=made.json()["id"])
    assert (goal.created_by_client, goal.client_company_id, goal.owner_id) == (
        True, company.pk, who["member"].user_id)
    name = who["member"].user.full_name or who["member"].user.email
    assert made.json()["added_by"] == f"{name}, Northwind Foods"
    # Live at once: everyone sees it, and the practice is told.
    assert goal.pk in {g.pk for g in Goal.all_objects.filter(client_company=company)}
    assert made.json()["id"] in [g["id"] for g in api.as_(who["viewer"]).get(
        "/api/goals/").json()]
    practice = api.as_(world["ff"])
    shown = next(g for g in practice.get("/api/goals/").json() if g["id"] == str(goal.pk))
    assert shown["added_by"] == f"{name}, Northwind Foods"
    entry = next(e for e in practice.get("/api/activity/?category=work").json()
                 if e["kind"] == "goal.added_by_client")
    assert entry["text"] == "added a goal for Northwind Foods: “Ship same day”"
    assert AuditEvent.all_objects.filter(verb="goal.added_by_client").count() == 1

    # Only their words: the measurable and the outcome are the practice's.
    refused = post(member, "/api/goals/", {"title": "x", "outcome_statement": "We won"})
    assert refused.status_code == 403 and "the rest is set by" in refused.json()["detail"]
    # Whatever "may create" says, someone who only looks adds nothing.
    give(who["viewer"], "goals")
    assert post(api.as_(who["viewer"]), "/api/goals/", {"title": "x"}).status_code == 403
    # Less than "Goals too": refused with a sentence that names who can change it.
    refused = post(api.as_(who["manager"]), "/api/goals/", {"title": "x"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == ("You have not been set up to add goals. "
                                        "Your client owner can change that.")
    owner_refused = post(api.as_(who["owner"]), "/api/goals/", {"title": "x"})
    assert "Your client owner" not in owner_refused.json()["detail"]


@pytest.mark.django_db
def test_role_boundaries_who_changes_and_deletes_a_goal(world):
    who, api = world["who"], world["api"]
    practices = world["goal"]
    leader = api.as_(who["leader"])
    for level in ("leader", "leader_all", "owner"):
        changed = patch(api.as_(who[level]), f"/api/goals/{practices}/",
                        {"title": f"Cut it, says {level}", "target_date": "2027-01-31"})
        assert changed.status_code == 200, (level, changed.content)
    for level in ("member", "manager", "viewer"):
        refused = patch(api.as_(who[level]), f"/api/goals/{practices}/", {"title": "x"})
        assert refused.status_code == 403, level
        assert "senior leadership" in refused.json()["detail"]
    refused = patch(leader, f"/api/goals/{practices}/", {"measurable": "Days"})
    assert refused.status_code == 403
    assert Goal.all_objects.get(pk=practices).measurable == ""
    # The practice's goal is never a client's to delete.
    for level in ("owner", "leader_all"):
        assert api.as_(who[level]).delete(f"/api/goals/{practices}/").status_code == 403

    # A goal a member added: they delete it, or the client owner; nobody else.
    give(who["member"], "goals")
    theirs = post(api.as_(who["member"]), "/api/goals/", {"title": "Ours"}).json()["id"]
    for level in ("leader_all", "manager"):
        refused = api.as_(who[level]).delete(f"/api/goals/{theirs}/")
        assert refused.status_code == 403, level
        assert "Only the person who added this goal" in refused.json()["detail"]
    assert api.as_(who["owner"]).delete(f"/api/goals/{theirs}/").status_code == 200
    again = post(api.as_(who["member"]), "/api/goals/", {"title": "Ours again"}).json()["id"]
    assert api.as_(who["member"]).delete(f"/api/goals/{again}/").status_code == 200
    # What a client is told they may do, per goal.
    goals = {g["id"]: g for g in leader.get("/api/goals/").json()}
    assert (goals[practices]["may_edit"], goals[practices]["may_delete"]) == (True, False)
    assert goals[practices]["editable_fields"] == ["title", "description", "target_date"]
    member_view = {g["id"]: g for g in api.as_(who["member"]).get("/api/goals/").json()}
    assert member_view[practices]["may_edit"] is False


@pytest.mark.django_db
def test_tenant_isolation_nothing_in_phase_4_reaches_another_company_or_practice(
        world, tenant_b):
    who, api = world["who"], world["api"]
    other = ClientCompanyFactory(tenant=world["tenant"], name="Globex Logistics")
    outsider = MembershipFactory(tenant=world["tenant"], role="ECC", client_company=other)
    their_goal = post(api.as_(world["ff"]), "/api/goals/",
                      {"title": "Globex's goal", "client_company": str(other.pk)}).json()["id"]
    owner = api.as_(who["owner"])
    give(who["owner"], "goals")
    assert patch(owner, f"/api/goals/{their_goal}/", {"title": "Ours"}).status_code == 404
    assert owner.delete(f"/api/goals/{their_goal}/").status_code == 404
    # A goal added names the client's own company, whatever is sent.
    made = post(owner, "/api/goals/", {"title": "Ours", "client_company": str(other.pk)})
    assert made.status_code == 400
    # The people offered are the company's own only.
    offered = {row["id"] for row in owner.get("/api/portal-people/").json()}
    assert str(outsider.user_id) not in offered
    # Another practice's client owner reaches nothing of practice A.
    b_owner = api.as_(MembershipFactory(
        tenant=tenant_b, role="FCC", may_create="goals",
        client_company=ClientCompanyFactory(tenant=tenant_b, name="Initech")))
    assert patch(b_owner, f"/api/goals/{world['goal']}/", {"title": "x"}).status_code == 404
    assert b_owner.get(f"/api/tasks/?view=everyone").json() == []
    assert Goal.all_objects.get(pk=world["goal"]).title == "Cut order-to-cash to 20 days"


@pytest.mark.django_db
def test_senior_leadership_of_every_team_is_what_a_viewer_is_then_called(world):
    """Bryan's demo check 5 (2026-10-14): a viewer on Everyone given senior
    leadership of every team on the Teams card reads "Senior leadership" on
    Portal access and in the acting banner, not "Viewer"."""
    who, api, company = world["who"], world["api"], world["company"]
    practice = api.as_(world["ff"])
    viewer = who["viewer"]
    assert post(practice, "/api/client-teams/person/",
                {"membership": str(viewer.pk), "leads_all_teams": True}).status_code == 200

    listed = practice.get(f"/api/portal-access/?company={company.pk}").json()["people"]
    assert {p["id"]: p["level_label"] for p in listed}[str(viewer.pk)] == "Senior leadership"

    assert post(practice, "/api/act-as/", {"membership": str(viewer.pk)}).status_code in (200, 201)
    assert me(practice)["acting"]["as_label"] == "Senior leadership"


@pytest.mark.django_db
def test_the_reason_nearest_the_person_is_the_read_only_line(world):
    """Bryan, 2026-10-15: a viewer is told they change nothing, whoever's the
    work is; a manager on another team's work is told whose manager can; on
    the practice's own work, the practice's line."""
    from apps.work.permissions import PRACTICES_PROJECT, PRACTICES_TASK

    who, api, t, p = world["who"], world["api"], world["tasks"], world["projects"]
    viewer, manager = api.as_(who["viewer"]), api.as_(who["manager"])

    def line(client, kind, pk):
        response = client.get(f"/api/{kind}/{pk}/")
        assert response.status_code == 200, response.content
        assert response.json()["may_edit"] is False
        return response.json()["read_only_line"]

    looks = "You can look at everything at Northwind Foods and change nothing."
    for pk in (t["sales"], t["of the practice"], t["ops, of a colleague"]):
        assert line(viewer, "tasks", pk) == looks
    for pk in (p["sales"], p["of the practice"]):
        assert line(viewer, "projects", pk) == looks

    assert line(manager, "tasks", t["sales"]) == "Only Sales's manager can change this."
    assert line(manager, "projects", p["sales"]) == "Only Sales's manager can change this."
    assert line(manager, "tasks", t["of the practice"]) == PRACTICES_TASK
    assert line(manager, "projects", p["of the practice"]) == PRACTICES_PROJECT

    # The same sentence is the refusal when they try.
    refused = patch(viewer, f"/api/tasks/{t['of the practice']}/", {"title": "x"})
    assert (refused.status_code, refused.json()["detail"]) == (403, looks)


@pytest.mark.django_db
def test_a_viewer_reads_comments_and_adds_none(world):
    who, api, t = world["who"], world["api"], world["tasks"]
    viewer = api.as_(who["viewer"])
    assert me(viewer)["portal"]["may_comment"] is False
    assert me(api.as_(who["member"]))["portal"]["may_comment"] is True
    assert viewer.get(f"/api/comments/?task={t['sales']}").status_code == 200
    refused = post(viewer, "/api/comments/", {"task": t["sales"], "body": "Looks good"})
    assert refused.status_code == 403
