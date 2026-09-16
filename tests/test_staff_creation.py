"""The practice can create what a client can, with the whole field set.

The portal shipped a real "new task" form; the staff side never got one, so a
fractional could only add a task from inside a goal or project, sending a title
and nothing else. The API allowed everything the whole time — these tests pin
that down, so a later change cannot quietly narrow what the practice may send
while the client's path keeps working.
"""

from __future__ import annotations

import pytest

from apps.crm.models import Task
from apps.work.models import Priority

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactFactory, GoalFactory, MembershipFactory, ProjectFactory,
)


@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Acme Foods", seat_count=3)


@pytest.mark.django_db
def test_staff_create_a_task_with_every_field_the_form_offers(
    seeded_tenant, ff, cf, api, company, in_tenant_a
):
    goal = GoalFactory(tenant=seeded_tenant, title="Cut DSO", client_company=company)
    project = ProjectFactory(tenant=seeded_tenant, title="Order-to-cash",
                             client_company=company, goal=goal)
    owner = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Okafor",
                           company=company)

    response = api.as_(ff).post("/api/tasks/", {
        "title": "Map the invoice process",
        "description": "End to end.",
        "client_company": str(company.pk),
        "goal": str(goal.pk),
        "project": str(project.pk),
        "assignee": str(cf.user_id),
        "client_owner_contact": str(owner.pk),
        "due_date": "2026-10-01",
        "priority": Priority.HIGH,
        "is_client_visible": True,
    }, content_type="application/json")

    assert response.status_code == 201, response.content
    task = Task.all_objects.get(pk=response.json()["id"])
    assert task.title == "Map the invoice process"
    assert task.description == "End to end."
    assert (task.client_company_id, task.goal_id, task.project_id) == \
        (company.pk, goal.pk, project.pk)
    assert task.assignee_id == cf.user_id
    assert task.client_owner_contact_id == owner.pk
    assert str(task.due_date) == "2026-10-01"
    assert task.priority == Priority.HIGH
    assert task.is_client_visible is True
    assert task.created_by_client is False, "The practice's own task, not a client's."


@pytest.mark.django_db
def test_a_practice_task_can_be_kept_from_the_client(seeded_tenant, ff, api, company,
                                                     in_tenant_a):
    """Matrix 7.7 — only the practice sets this, and the form's tick box is it."""
    response = api.as_(ff).post("/api/tasks/", {
        "title": "Draft the fee change", "client_company": str(company.pk),
        "is_client_visible": False,
    }, content_type="application/json")
    assert response.status_code == 201
    assert Task.all_objects.get(pk=response.json()["id"]).is_client_visible is False


@pytest.mark.django_db
def test_an_internal_task_belongs_to_no_client(seeded_tenant, ff, api, in_tenant_a):
    response = api.as_(ff).post("/api/tasks/", {"title": "Our own admin"},
                                content_type="application/json")
    assert response.status_code == 201
    task = Task.all_objects.get(pk=response.json()["id"])
    assert task.client_company_id is None and task.is_client_visible is False


@pytest.mark.django_db
def test_a_va_may_create_a_task_too(seeded_tenant, va, api, company, in_tenant_a):
    """Matrix 4.18 — tasks are a VA's work; only financials and settings are not."""
    response = api.as_(va).post("/api/tasks/", {
        "title": "Chase the AP login", "client_company": str(company.pk),
    }, content_type="application/json")
    assert response.status_code == 201


@pytest.mark.django_db
def test_staff_create_a_project_with_its_description_and_dates(
    seeded_tenant, ff, api, company, in_tenant_a
):
    """The client's form always took these; the practice's took a title."""
    from apps.work.models import Project

    goal = GoalFactory(tenant=seeded_tenant, title="Cut DSO", client_company=company)
    owner = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Okafor",
                           company=company)

    response = api.as_(ff).post("/api/projects/", {
        "title": "Order-to-cash",
        "description": "Invoices end to end.",
        "client_company": str(company.pk),
        "client_owner_contact": str(owner.pk),
        "goal": str(goal.pk),
        "start_date": "2026-10-01",
        "target_date": "2026-12-31",
    }, content_type="application/json")

    assert response.status_code == 201, response.content
    project = Project.all_objects.get(pk=response.json()["id"])
    assert project.description == "Invoices end to end."
    assert project.goal_id == goal.pk and project.client_owner_contact_id == owner.pk
    assert (str(project.start_date), str(project.target_date)) == ("2026-10-01", "2026-12-31")


@pytest.mark.django_db
def test_staff_create_a_goal_with_its_description_and_target(seeded_tenant, ff, api, company,
                                                             in_tenant_a):
    from apps.work.models import Goal

    response = api.as_(ff).post("/api/goals/", {
        "title": "Cut DSO", "description": "From 41 days to 30.",
        "client_company": str(company.pk), "target_date": "2026-12-31",
    }, content_type="application/json")

    assert response.status_code == 201, response.content
    goal = Goal.all_objects.get(pk=response.json()["id"])
    assert goal.description == "From 41 days to 30." and str(goal.target_date) == "2026-12-31"


@pytest.mark.django_db
def test_the_client_rules_are_untouched_by_the_practices_form(
    seeded_tenant, ff, api, company, in_tenant_a
):
    """The staff form exists because the API always allowed it — which must not
    mean a client may now reach past their own company."""
    other = ClientCompanyFactory(tenant=seeded_tenant, name="Other Co")
    client_user = MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=company)

    refused = api.as_(client_user).post("/api/tasks/", {
        "title": "Not mine", "client_company": str(other.pk),
    }, content_type="application/json")
    assert refused.status_code == 400

    hidden = api.as_(client_user).post("/api/tasks/", {
        "title": "Hide this", "is_client_visible": False,
    }, content_type="application/json")
    assert hidden.status_code == 400, "Only the practice sets client visibility."

    mine = api.as_(client_user).post("/api/tasks/", {"title": "Mine"},
                                     content_type="application/json")
    assert mine.status_code == 201
    task = Task.all_objects.get(pk=mine.json()["id"])
    assert task.client_company_id == company.pk and task.created_by_client is True


# ------------------------------------------- editing what a goal or project says

@pytest.mark.django_db
def test_staff_edit_a_goals_details(seeded_tenant, ff, api, company, in_tenant_a):
    """The API always accepted these; no screen ever sent them, so the record was
    write-once in practice."""
    from apps.work.models import Goal

    goal = GoalFactory(tenant=seeded_tenant, title="Cut DSO", client_company=company)
    owner = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Okafor",
                           company=company)

    response = api.as_(ff).patch(f"/api/goals/{goal.pk}/", {
        "title": "Cut DSO to 30 days",
        "description": "From 41 days.",
        "target_date": "2026-12-31",
        "client_owner_contact": str(owner.pk),
    }, content_type="application/json")

    assert response.status_code == 200, response.content
    goal.refresh_from_db()
    assert goal.title == "Cut DSO to 30 days" and goal.description == "From 41 days."
    assert str(goal.target_date) == "2026-12-31" and goal.client_owner_contact_id == owner.pk


@pytest.mark.django_db
def test_staff_edit_a_projects_details_including_its_dates(seeded_tenant, ff, api, company,
                                                           in_tenant_a):
    from apps.work.models import Project

    project = ProjectFactory(tenant=seeded_tenant, title="Order-to-cash",
                             client_company=company)
    response = api.as_(ff).patch(f"/api/projects/{project.pk}/", {
        "title": "Order-to-cash, phase 2",
        "description": "Matching rules.",
        "start_date": "2026-10-01",
        "target_date": "2026-12-31",
    }, content_type="application/json")

    assert response.status_code == 200, response.content
    project.refresh_from_db()
    assert project.title == "Order-to-cash, phase 2"
    assert (str(project.start_date), str(project.target_date)) == ("2026-10-01", "2026-12-31")


@pytest.mark.django_db
def test_a_client_never_edits_the_practices_goals_or_projects(seeded_tenant, ff, api, company,
                                                              in_tenant_a):
    goal = GoalFactory(tenant=seeded_tenant, title="Cut DSO", client_company=company)
    project = ProjectFactory(tenant=seeded_tenant, title="Order-to-cash",
                             client_company=company)
    client_user = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)

    assert api.as_(client_user).patch(f"/api/goals/{goal.pk}/", {"title": "Mine now"},
                                      content_type="application/json").status_code == 403
    assert api.as_(client_user).patch(f"/api/projects/{project.pk}/", {"title": "Mine now"},
                                      content_type="application/json").status_code == 403
    goal.refresh_from_db()
    project.refresh_from_db()
    assert goal.title == "Cut DSO" and project.title == "Order-to-cash"


@pytest.mark.django_db
def test_a_client_may_still_edit_a_project_they_created(seeded_tenant, api, company,
                                                        in_tenant_a):
    """FR-3.35a — their own project stays theirs; only the practice's is refused."""
    from apps.work.models import Project

    client_user = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    made = api.as_(client_user).post("/api/projects/", {"title": "Our tidy-up"},
                                     content_type="application/json")
    assert made.status_code == 201
    project = Project.all_objects.get(pk=made.json()["id"])
    assert project.created_by_client is True

    changed = api.as_(client_user).patch(f"/api/projects/{project.pk}/",
                                         {"description": "Ours to run."},
                                         content_type="application/json")
    assert changed.status_code == 200
    project.refresh_from_db()
    assert project.description == "Ours to run."
