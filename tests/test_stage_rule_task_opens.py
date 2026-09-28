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


def _fire_rule(tenant, sales, stages, ff, api, *, company=None, stage="qualified",
               visible=None):
    """Exactly what a drag on the board does, with a task rule on the stage.

    `visible=None` makes the rule the way the FF does, through the API with no
    choice sent, so the rule gets the server's default for that stage.
    """
    if visible is None:
        response = api.as_(ff).post("/api/stage-automations/", {
            "pipeline": str(sales.pk), "to_stage": str(stages[stage].pk),
            "action_type": "create_task", "task_title_template": "Follow up",
            "task_due_offset_days": 3,
        }, content_type="application/json")
        assert response.status_code == 201, response.content
    else:
        StageAutomationFactory(
            tenant=tenant, pipeline=sales, to_stage=stages[stage],
            action_type="create_task", task_title_template="Follow up",
            task_due_offset_days=3, task_client_visible=visible,
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


# ------------------------------------- whether the client sees it: per rule

def _new_rule(api, ff, sales, stages, stage, **extra):
    response = api.as_(ff).post("/api/stage-automations/", {
        "pipeline": str(sales.pk), "to_stage": str(stages[stage].pk),
        "action_type": "create_task", "task_title_template": "Follow up", **extra,
    }, content_type="application/json")
    assert response.status_code == 201, response.content
    return response.json()


@pytest.mark.django_db
def test_a_new_rule_is_internal_by_default(seeded_tenant, sales, stages, ff, api):
    rule = _new_rule(api, ff, sales, stages, "qualified")
    assert rule["task_client_visible"] is False
    assert "internal, hidden from the client" in rule["summary"]


@pytest.mark.django_db
def test_a_new_rule_on_the_won_stage_defaults_to_visible(seeded_tenant, sales, stages, ff, api):
    """Its task is for the new client."""
    rule = _new_rule(api, ff, sales, stages, "closed_won")
    assert rule["task_client_visible"] is True
    assert "the client can see it" in rule["summary"]


@pytest.mark.django_db
@pytest.mark.parametrize("stage,chosen", [("qualified", True), ("closed_won", False)])
def test_the_ffs_choice_overrides_either_default(
    seeded_tenant, sales, stages, ff, api, stage, chosen
):
    rule = _new_rule(api, ff, sales, stages, stage, task_client_visible=chosen)
    assert rule["task_client_visible"] is chosen


@pytest.mark.django_db
def test_the_setting_can_be_changed_on_an_existing_rule(seeded_tenant, sales, stages, ff, api):
    rule = _new_rule(api, ff, sales, stages, "qualified")
    response = api.as_(ff).patch(f"/api/stage-automations/{rule['id']}/",
                                 {"task_client_visible": True},
                                 content_type="application/json")
    assert response.status_code == 200
    assert response.json()["task_client_visible"] is True


@pytest.mark.django_db
def test_a_referral_won_stage_is_not_a_sale_and_stays_internal(
    seeded_tenant, referrals, referral_stages, ff, api
):
    """A `won` stage outside a sales pipeline is not a sale (FR-1.6a rule 5), so
    its task is not for a new client. The seeded referral pipeline has no won
    stage; a practice may mark one, so the test does."""
    won = referral_stages["active_referrer"]
    won.semantic = "won"
    won.save(update_fields=["semantic"])
    response = api.as_(ff).post("/api/stage-automations/", {
        "pipeline": str(referrals.pk), "to_stage": str(won.pk),
        "action_type": "create_task", "task_title_template": "Thank them",
    }, content_type="application/json")
    assert response.status_code == 201
    assert response.json()["task_client_visible"] is False


@pytest.mark.django_db
def test_a_default_rule_files_a_client_contacts_task_under_them_but_hidden(
    seeded_tenant, sales, stages, ff, api
):
    """Filed under the client company, so it is on their page for the practice;
    not visible to them, because the rule says internal."""
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, company=acme)

    assert task.client_company_id == acme.pk
    assert task.is_client_visible is False


@pytest.mark.django_db
def test_a_rule_set_to_visible_shows_a_client_contacts_task_to_them(
    seeded_tenant, sales, stages, ff, api
):
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, company=acme, visible=True)

    assert task.client_company_id == acme.pk
    assert task.is_client_visible is True


@pytest.mark.django_db
def test_a_visible_rule_cannot_show_a_task_with_no_client_to_see_it(
    seeded_tenant, sales, stages, ff, api
):
    task = _fire_rule(seeded_tenant, sales, stages, ff, api, visible=True)

    assert task.client_company_id is None
    assert task.is_client_visible is False


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
    rules run; the rule sees the company as a client company. A won rule made
    with no choice sent is visible by default, so the new client sees it."""
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
