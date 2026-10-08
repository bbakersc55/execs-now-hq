"""A goal opened in place on the value report (2026-10-07).

`GET /api/goals/<id>/tree/` is the work under one goal: its projects with their
tasks, and the tasks filed straight on it. It is scoped as everything else
about a goal is — and the two families that are not optional are here: another
practice, and another company inside the same practice.

What a client may do to an open goal is the existing rules, pinned in one
place: add a task, comment, and neither record a reading nor resolve it.
"""

from __future__ import annotations

import json

import pytest

from apps.tenancy.models import Role

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)


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
def world(seeded_tenant, ff, api, company, in_tenant_a):
    """One goal with a project of two tasks (one internal), a task filed
    straight on it, and a second goal whose work must never leak in."""
    staff = api.as_(ff)
    co = str(company.pk)
    goal = make(staff, "/api/goals/", title="Cut order-to-cash", client_company=co)
    project = make(staff, "/api/projects/", title="Invoice run", goal=goal["id"],
                   client_company=co)
    shown = make(staff, "/api/tasks/", title="Send invoices weekly",
                 project=project["id"], client_company=co)
    hidden = make(staff, "/api/tasks/", title="Chase the CFO quietly",
                  project=project["id"], client_company=co, is_client_visible=False)
    direct = make(staff, "/api/tasks/", title="Agree the target", goal=goal["id"],
                  client_company=co)

    other = make(staff, "/api/goals/", title="Hiring bench", client_company=co)
    elsewhere = make(staff, "/api/tasks/", title="Write the job ad", goal=other["id"],
                     client_company=co)
    return {"goal": goal, "project": project, "shown": shown, "hidden": hidden,
            "direct": direct, "other": other, "elsewhere": elsewhere}


def titles(tree):
    return ([(p["title"], [t["title"] for t in p["tasks"]]) for p in tree["projects"]],
            [t["title"] for t in tree["tasks"]])


# -------------------------------------------------------------------- shape

@pytest.mark.django_db
def test_the_tree_is_the_goals_projects_with_their_tasks_and_its_direct_tasks(
    world, ff, api, in_tenant_a
):
    tree = api.as_(ff).get(f"/api/goals/{world['goal']['id']}/tree/")
    assert tree.status_code == 200
    assert titles(tree.json()) == (
        [("Invoice run", ["Send invoices weekly", "Chase the CFO quietly"])],
        ["Agree the target"],
    )
    # Each carries the status the report shows beside it.
    body = tree.json()
    assert body["projects"][0]["status"] and body["projects"][0]["tasks"][0]["status"]
    assert body["tasks"][0]["status"] == "not_started"


@pytest.mark.django_db
def test_a_task_under_a_project_is_listed_once_under_the_project(world, ff, api, in_tenant_a):
    body = api.as_(ff).get(f"/api/goals/{world['goal']['id']}/tree/").json()
    every = [t["id"] for p in body["projects"] for t in p["tasks"]] \
        + [t["id"] for t in body["tasks"]]
    assert len(every) == len(set(every)) == 3
    assert world["elsewhere"]["id"] not in every, "Another goal's task was listed."


@pytest.mark.django_db
def test_a_project_has_no_tree(world, ff, api, in_tenant_a):
    assert api.as_(ff).get(
        f"/api/projects/{world['project']['id']}/tree/").status_code == 404


# ------------------------------------------------------------- who sees what

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_sees_their_goals_work_without_the_internal_task(
    role, world, seeded_tenant, company, api, in_tenant_a
):
    member = a_client(seeded_tenant, company, role)
    tree = api.as_(member).get(f"/api/goals/{world['goal']['id']}/tree/")
    assert tree.status_code == 200
    assert titles(tree.json()) == (
        [("Invoice run", ["Send invoices weekly"])], ["Agree the target"])
    assert "Chase the CFO quietly" not in tree.content.decode()


@pytest.mark.django_db
def test_another_company_in_the_same_practice_cannot_open_the_tree(
    world, seeded_tenant, api, in_tenant_a
):
    """FR-0.2 — two client companies of one practice are as invisible to each
    other as two practices are."""
    rival = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight", seat_count=2)
    for role in ("FCC", "ECC"):
        member = a_client(seeded_tenant, rival, role, first=f"Rival{role}")
        response = api.as_(member).get(f"/api/goals/{world['goal']['id']}/tree/")
        assert response.status_code == 404
        assert "Invoice run" not in response.content.decode()


@pytest.mark.django_db
def test_another_practice_cannot_open_the_tree(world, tenant_b, api):
    for role in ("FF", "CF", "VA"):
        theirs = MembershipFactory(tenant=tenant_b, role=role)
        response = api.as_(theirs).get(f"/api/goals/{world['goal']['id']}/tree/")
        assert response.status_code == 404
        assert "Invoice run" not in response.content.decode()


@pytest.mark.django_db
def test_an_associate_opens_it_only_at_a_company_they_are_assigned(
    world, seeded_tenant, cf, company, api, in_tenant_a
):
    url = f"/api/goals/{world['goal']['id']}/tree/"
    assert api.as_(cf).get(url).status_code == 404
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert api.as_(cf).get(url).status_code == 200


@pytest.mark.django_db
def test_an_assistant_reads_the_tree(world, va, api, in_tenant_a):
    """Tasks are an assistant's work; nothing financial is in here."""
    tree = api.as_(va).get(f"/api/goals/{world['goal']['id']}/tree/")
    assert tree.status_code == 200 and len(tree.json()["projects"]) == 1


@pytest.mark.django_db
def test_signed_out_gets_nothing(world, client):
    assert client.get(f"/api/goals/{world['goal']['id']}/tree/").status_code in (401, 403)


# ------------------------------------- what a client may do to an open goal

@pytest.mark.django_db
def test_a_client_adds_a_task_on_the_goal_and_under_its_project_and_sees_both(
    world, seeded_tenant, company, api, in_tenant_a
):
    member = a_client(seeded_tenant, company, "ECC")
    theirs = api.as_(member)
    # What the open goal sends: no company, the server sets a client's own.
    on_goal = make(theirs, "/api/tasks/", title="Send the AP export",
                   goal=world["goal"]["id"])
    in_project = make(theirs, "/api/tasks/", title="Check the invoice template",
                      project=world["project"]["id"])
    assert on_goal["client_company"] == in_project["client_company"] == str(company.pk)
    assert on_goal["created_by_client"] is True and on_goal["is_client_visible"] is True

    assert titles(theirs.get(f"/api/goals/{world['goal']['id']}/tree/").json()) == (
        [("Invoice run", ["Send invoices weekly", "Check the invoice template"])],
        ["Agree the target", "Send the AP export"])


@pytest.mark.django_db
def test_a_client_cannot_add_a_task_to_another_companys_goal(
    world, seeded_tenant, api, in_tenant_a
):
    rival = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight", seat_count=2)
    member = a_client(seeded_tenant, rival, "FCC", first="Rival")
    refused = post(api.as_(member), "/api/tasks/",
                   {"title": "Not mine to add", "goal": world["goal"]["id"]})
    assert refused.status_code in (400, 404)


@pytest.mark.django_db
def test_a_client_comments_on_the_goal_and_the_practice_reads_it(
    world, seeded_tenant, company, ff, api, in_tenant_a
):
    member = a_client(seeded_tenant, company, "FCC")
    made = post(api.as_(member), "/api/comments/",
                {"goal": world["goal"]["id"], "body": "This is the one that matters."})
    assert made.status_code == 201, made.content
    assert made.json()["visibility"] == "shared"

    seen = api.as_(ff).get(f"/api/comments/?goal={world['goal']['id']}").json()
    assert [c["body"] for c in seen] == ["This is the one that matters."]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_readings_and_resolutions_stay_the_practices(
    role, world, seeded_tenant, company, api, in_tenant_a
):
    from apps.work.models import GoalMeasurement, GoalResolution

    member = a_client(seeded_tenant, company, role)
    theirs = api.as_(member)
    goal = world["goal"]["id"]
    assert post(theirs, "/api/goal-measurements/",
                {"goal": goal, "value": "12"}).status_code == 403
    assert post(theirs, "/api/goal-resolutions/",
                {"goal": goal, "resolution": "achieved", "reason": "We say so."}
                ).status_code == 403
    assert not GoalMeasurement.all_objects.filter(goal_id=goal).exists()
    assert not GoalResolution.all_objects.filter(goal_id=goal).exists()
    # And the block they are sent carries no readings table.
    block = theirs.get(f"/api/value-report/{goal}/").json()
    assert "measurements" not in block


@pytest.mark.django_db
def test_the_goal_block_names_its_company_so_a_link_opens_the_right_report(
    world, ff, company, api, in_tenant_a
):
    block = api.as_(ff).get(f"/api/value-report/{world['goal']['id']}/").json()
    assert block["client_company"] == str(company.pk)


# ------------------------- a client's project under a goal (owner, 2026-10-07)

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_adds_a_project_under_their_companys_goal(
    role, world, seeded_tenant, company, ff, api, in_tenant_a
):
    """FR-3.35a said a client's project never sat under a goal. It may now."""
    member = a_client(seeded_tenant, company, role)
    project = make(api.as_(member), "/api/projects/", title="Our own follow-ups",
                   goal=world["goal"]["id"])
    assert project["goal"] == world["goal"]["id"]
    assert project["created_by_client"] is True
    assert project["client_company"] == str(company.pk)

    # It is in the goal's tree for them and for the practice, and they can
    # file a task in it.
    make(api.as_(member), "/api/tasks/", title="Ring the supplier", project=project["id"])
    for reader in (member, ff):
        tree = api.as_(reader).get(f"/api/goals/{world['goal']['id']}/tree/").json()
        ours = next(p for p in tree["projects"] if p["id"] == project["id"])
        assert [t["title"] for t in ours["tasks"]] == ["Ring the supplier"]


@pytest.mark.django_db
def test_a_clients_project_with_no_goal_is_still_fine(world, seeded_tenant, company, api,
                                                      in_tenant_a):
    member = a_client(seeded_tenant, company, "FCC")
    project = make(api.as_(member), "/api/projects/", title="Our own tidy-up")
    assert project["goal"] is None and project["created_by_client"] is True


@pytest.mark.django_db
def test_a_client_cannot_file_a_project_under_another_companys_goal(
    world, seeded_tenant, api, in_tenant_a
):
    from apps.work.models import Project

    rival = ClientCompanyFactory(tenant=seeded_tenant, name="Ridgeline Freight", seat_count=2)
    member = a_client(seeded_tenant, rival, "FCC", first="Rival")
    refused = post(api.as_(member), "/api/projects/",
                   {"title": "Not ours to file", "goal": world["goal"]["id"]})
    assert refused.status_code == 400
    assert "not available to you" in refused.content.decode()
    assert not Project.all_objects.filter(title="Not ours to file").exists()


@pytest.mark.django_db
def test_a_client_cannot_file_a_project_under_another_practices_goal(
    world, tenant_b, api
):
    from apps.work.models import Project

    their_company = ClientCompanyFactory(tenant=tenant_b, name="Elsewhere Ltd", seat_count=2)
    member = a_client(tenant_b, their_company, "FCC", first="Elsewhere")
    refused = post(api.as_(member), "/api/projects/",
                   {"title": "Across the wall", "goal": world["goal"]["id"]})
    assert refused.status_code == 400
    assert not Project.all_objects.filter(title="Across the wall").exists()


@pytest.mark.django_db
def test_a_client_still_cannot_create_a_goal(world, seeded_tenant, company, api, in_tenant_a):
    member = a_client(seeded_tenant, company, "FCC")
    assert post(api.as_(member), "/api/goals/", {"title": "Our strategy"}).status_code == 403
