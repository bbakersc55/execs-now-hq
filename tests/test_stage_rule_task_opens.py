"""A task made by a Phase 1 stage rule opens in the task sheet (2026-09-28).

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

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, StageAutomationFactory


def _fire_rule(tenant, sales, stages, ff, api):
    StageAutomationFactory(
        tenant=tenant, pipeline=sales, to_stage=stages["qualified"],
        action_type="create_task", task_title_template="Follow up",
        task_due_offset_days=3,
    )
    contact = ContactFactory(tenant=tenant, owner=ff.user)
    ContactEmailFactory(tenant=tenant, contact=contact)
    response = api.as_(ff).post(
        f"/api/contacts/{contact.pk}/change-stage/",
        {"stage": str(stages["qualified"].pk)}, content_type="application/json",
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
def test_the_rule_still_makes_the_task_it_always_made(
    seeded_tenant, sales, stages, ff, api
):
    """The shape these tests are about — recorded, so a change to it is noticed."""
    task = _fire_rule(seeded_tenant, sales, stages, ff, api)

    assert task.source_automation_id is not None
    assert task.client_company_id is None
    assert task.assignee_id is None
    assert task.owner_id == ff.user.pk
    assert task.due_date is not None


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
