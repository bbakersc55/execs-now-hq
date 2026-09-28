"""A task made by a Phase 1 stage rule is made like any other task (2026-09-28).

Three "Follow up" tasks from the stage automation looked as if they would not
open from the Tasks board. The API was never the cause: the board card was only
clickable on its title line (fixed in the frontend). These tests keep it that
way from the server's side, because the rule makes a task unlike anything made
since Phase 3 — internal (no client company), unassigned, linked to a contact,
and with no history row. Every endpoint the sheet calls must answer for that
shape, for everyone on the staff who can see it.
"""

from __future__ import annotations

import pytest

from apps.crm.models import Task
from apps.tenancy.context import tenant_context
from apps.work.models import TaskUpdate

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CompanyFactory, ContactEmailFactory, ContactFactory,
    StageAutomationFactory,
)


def _fire_rule(tenant, sales, stages, ff, api, *, company=None, stage="qualified"):
    """Exactly what a drag on the board does, with a task rule on the stage."""
    StageAutomationFactory(
        tenant=tenant, pipeline=sales, to_stage=stages[stage],
        action_type="create_task", task_title_template="Follow up",
        task_due_offset_days=3,
    )
    contact = ContactFactory(tenant=tenant, owner=ff.user, company=company)
    ContactEmailFactory(tenant=tenant, contact=contact)
    response = api.as_(ff).post(
        f"/api/contacts/{contact.pk}/change-stage/",
        {"stage": str(stages[stage].pk)}, content_type="application/json",
    )
    assert response.status_code == 200
    with tenant_context(tenant.pk):
        return Task.objects.get(contact=contact, title="Follow up")


def _sheet_paths(task_id) -> list[str]:
    """Every call the task sheet makes when it opens (TaskDetail and its panels)."""
    return [
        f"/api/tasks/{task_id}/",
        f"/api/tasks/{task_id}/updates/",
        f"/api/tasks/{task_id}/checklist/",
        f"/api/comments/?task={task_id}",
        f"/api/stakeholders/?effective={task_id}",
        f"/api/stakeholders/candidates/?task={task_id}",
        f"/api/notes/?task={task_id}",
    ]


@pytest.mark.django_db
def test_a_contact_with_no_company_gets_an_internal_hidden_task(
    seeded_tenant, sales, stages, ff, api
):
    """The shape the three "Follow up" tasks had — still right when there is no
    company to file it under."""
    task = _fire_rule(seeded_tenant, sales, stages, ff, api)

    assert task.source_automation_id is not None
    assert task.client_company_id is None
    assert task.is_client_visible is False
    assert task.assignee_id is None
    assert task.owner_id == ff.user.pk
    assert task.due_date is not None
    assert task.created_by_client is False


@pytest.mark.django_db
def test_the_rule_writes_the_created_update_like_every_other_path(
    seeded_tenant, sales, stages, ff, api
):
    """Until 2026-09-28 a rule's task opened on an empty history."""
    task = _fire_rule(seeded_tenant, sales, stages, ff, api)

    with tenant_context(seeded_tenant.pk):
        created = TaskUpdate.objects.filter(task=task, kind=TaskUpdate.Kind.CREATED)
        assert created.count() == 1
        row = created.get()
    assert row.to_value == "Follow up"
    assert row.actor_id == ff.user.pk           # who moved the contact
    assert row.source == TaskUpdate.Source.STAGE_AUTOMATION
    assert row.source_id == task.source_automation_id
    assert row.is_client_actor is False

    history = api.as_(ff).get(f"/api/tasks/{task.pk}/updates/").json()
    assert [entry["kind"] for entry in history] == ["created"]


@pytest.mark.django_db
def test_a_contact_at_a_client_company_gets_a_client_visible_task(
    seeded_tenant, sales, stages, ff, api
):
    """The same rule as a task made by hand (FR-3.11): filed under the client
    company, and visible to the client because it is."""
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, company=acme)

    assert task.client_company_id == acme.pk
    assert task.is_client_visible is True


@pytest.mark.django_db
def test_a_contact_at_a_prospect_company_gets_a_hidden_internal_task(
    seeded_tenant, sales, stages, ff, api
):
    """A company that is not a client is not a client company: a prospect's
    follow-up is internal work and is not filed under them."""
    prospect = CompanyFactory(tenant=seeded_tenant, name="Grime Fighters",
                              is_client_company=False)
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, company=prospect)

    assert task.client_company_id is None
    assert task.is_client_visible is False


@pytest.mark.django_db
def test_the_move_that_makes_a_client_files_the_task_under_them(
    seeded_tenant, sales, stages, ff, api
):
    """Reaching won flags the company in the same transaction, just before the
    rules run; the rule sees the company as a client company."""
    prospect = CompanyFactory(tenant=seeded_tenant, name="Grime Fighters",
                              is_client_company=False)
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, company=prospect,
                      stage="closed_won")

    prospect.refresh_from_db()
    assert prospect.is_client_company is True
    assert task.client_company_id == prospect.pk
    assert task.is_client_visible is True


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["ff", "va"])
def test_a_rule_made_task_is_on_the_board_and_opens(
    seeded_tenant, sales, stages, ff, va, api, role
):
    task = _fire_rule(seeded_tenant, sales, stages, ff, api)
    member = {"ff": ff, "va": va}[role]
    client = api.as_(member)

    board = client.get("/api/tasks/").json()
    card = next(row for row in board if row["id"] == str(task.pk))
    assert card["title"] == "Follow up"

    for path in _sheet_paths(task.pk):
        response = client.get(path)
        assert response.status_code == 200, (path, response.content[:300])

    # What the sheet reads without a guard: objects, never nulls.
    detail = client.get(f"/api/tasks/{task.pk}/").json()
    assert detail["id"] == str(task.pk)
    for person in ("owner", "assignee", "client_owner_contact"):
        assert isinstance(detail[person], dict), person
    assert detail["may_edit"] is True
