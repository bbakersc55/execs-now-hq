"""The practice's own words in the task engine's sentences (2026-10-15):
read-only lines, refusals, Activity, a contact's timeline, the client mark's
blockers and the narrative prompt. With custom words the custom words show
and the defaults do not; with the defaults every sentence reads as before.
"""

from __future__ import annotations

import json

import pytest

from apps.tenancy import words
from apps.tenancy.models import Tenant

from . import registry_config  # noqa: F401
from .test_client_teams import make, patch, post, world  # noqa: F401

CUSTOM = {"goal": ["objective", "objectives"], "project": ["initiative", "initiatives"],
          "task": ["action", "actions"], "step": ["checkpoint", "checkpoints"]}
DEFAULT_WORDS = ("goal", "project", "task", "step")


def custom(tenant):
    Tenant.objects.filter(pk=tenant.pk).update(work_words=CUSTOM)
    tenant.refresh_from_db()


def no_defaults(text: str):
    lowered = text.lower()
    for word in DEFAULT_WORDS:
        assert word not in lowered, (word, text)


@pytest.mark.django_db
def test_the_read_only_lines_use_the_practices_words(world):
    from apps.work.permissions import (
        PRACTICES_PROJECT, PRACTICES_TASK, practices_project, practices_task,
    )

    assert practices_task(words.DEFAULT) == PRACTICES_TASK
    assert practices_project(words.DEFAULT) == PRACTICES_PROJECT
    custom(world["tenant"])
    manager = world["api"].as_(world["who"]["manager"])
    task = manager.get(f"/api/tasks/{world['tasks']['of the practice']}/").json()
    assert task["read_only_line"] == (
        "This action is the practice's to change. Add a comment and they will see it.")
    project = manager.get(f"/api/projects/{world['projects']['of the practice']}/").json()
    assert project["read_only_line"] == "This initiative belongs to the practice."
    # The refusal says the same.
    refused = patch(manager, f"/api/tasks/{world['tasks']['of the practice']}/",
                    {"status": "in_progress"})
    assert refused.status_code == 403
    no_defaults(refused.json()["detail"])
    step = post(manager, f"/api/tasks/{world['tasks']['of the practice']}/checklist/",
                {"text": "Check it"})
    assert step.json()["detail"] == "This action is the practice's to change."


@pytest.mark.django_db
def test_refusals_a_person_reads_use_the_practices_words(world):
    custom(world["tenant"])
    practice = world["api"].as_(world["ff"])
    for url, said in (("/api/goals/", "An objective needs a title."),
                      ("/api/projects/", "An initiative needs a title."),
                      ("/api/tasks/", "An action needs a title.")):
        response = post(practice, url, {"client_company": str(world["company"].pk)})
        assert response.status_code == 400
        assert response.json()["title"] == [said]
    both = post(practice, "/api/tasks/", {"title": "Both", "goal": world["goal"],
                                          "project": world["projects"]["of the practice"]})
    assert both.json()["project"] == [
        "File an action under an initiative or directly on an objective, not both — "
        "an initiative already belongs to its objective."]
    comment = post(practice, "/api/comments/", {"body": "Hello"})
    assert comment.json()["non_field_errors"] == ["A comment belongs to exactly one action, initiative or "
                              "objective."]
    step = post(practice, f"/api/tasks/{world['tasks']['sales']}/checklist/", {})
    assert step.json()["detail"] == "The checkpoint needs text."
    empty = post(practice, f"/api/tasks/{world['tasks']['sales']}/checklist/", {"text": ""})
    no_defaults(json.dumps(empty.json()))

    # A client user who may not add goals is told so in the practice's words.
    viewer = world["api"].as_(world["who"]["member"])
    refused = post(viewer, "/api/goals/", {"title": "Grow"})
    assert refused.status_code == 403
    assert "objectives" in refused.json()["detail"]
    no_defaults(refused.json()["detail"])


@pytest.mark.django_db
def test_defaults_read_exactly_as_before(world):
    practice = world["api"].as_(world["ff"])
    response = post(practice, "/api/tasks/", {})
    assert response.json()["title"] == ["A task needs a title."]
    step = post(practice, f"/api/tasks/{world['tasks']['sales']}/checklist/", {})
    assert step.json()["detail"] == "The step needs text."


@pytest.mark.django_db
def test_activity_is_told_in_the_practices_words(world):
    custom(world["tenant"])
    practice = world["api"].as_(world["ff"])
    task_id = world["tasks"]["sales"]
    item = post(practice, f"/api/tasks/{task_id}/checklist/", {"text": "Ring Ana"}).json()
    assert patch(practice, f"/api/checklist-items/{item['id']}/",
                 {"is_done": True}).status_code == 200
    assert practice.delete(f"/api/goals/{world['goal']}/").status_code == 200
    feed = practice.get("/api/activity/?category=work").json()
    texts = [e["text"] for e in feed]
    assert "deleted an objective" in texts
    assert any(t.startswith("completed the checkpoint “Ring Ana”") for t in texts), texts
    assert not any("deleted a goal" in t or "the step “" in t for t in texts)


def test_a_team_archived_counts_in_the_practices_words():
    from types import SimpleNamespace

    from apps.work.activity import _team_text

    row = SimpleNamespace(verb="client_team.archived",
                          payload={"name": "Ops", "projects": 2, "tasks": 1})
    assert _team_text(row, "", "") == (
        "archived the team “Ops”: 2 project(s) and 1 task(s) moved to the default team")
    w = words.of(SimpleNamespace(work_words={"project": ["activity", "activities"],
                                             "task": ["action", "actions"]}))
    assert _team_text(row, "", "", w) == (
        "archived the team “Ops”: 2 activities and 1 action(s) moved to the default team")


@pytest.mark.django_db
def test_services_say_the_practices_words(world):
    from apps.crm.models import Contact
    from apps.crm.services import clients, timeline
    from apps.work import goal_order, goal_proposals, narratives

    tenant, company = world["tenant"], world["company"]
    custom(tenant)
    company.refresh_from_db()
    company.tenant.refresh_from_db()

    blockers = " ".join(clients.blockers(company))
    assert "objective" in blockers and "initiatives" in blockers and "actions" in blockers
    no_defaults(blockers)

    with pytest.raises(goal_proposals.ProposalRefused) as said:
        goal_proposals.propose(company, title=" ", actor=world["ff"].user)
    assert str(said.value) == "Say what the objective is."

    with pytest.raises(goal_order.OrderRefused) as said:
        goal_order.set_order(company, "nope", actor=world["ff"].user)
    assert str(said.value) == "Send the order as a list of objective ids."

    from apps.crm.models import Task
    from apps.tenancy.context import tenant_context

    contact = Contact.all_objects.create(tenant=tenant, first_name="Ana", last_name="Ruiz",
                                         company=company)
    Task.all_objects.create(tenant=tenant, title="Call Ana", contact=contact)
    with tenant_context(tenant.pk):
        entries = timeline.for_contact(contact)
    assert any(e["text"] == "Action: Call Ana" for e in entries)

    assert narratives.system(words.DEFAULT) == narratives.SYSTEM
    told = narratives.system(words.of(tenant))
    assert 'a goal is "objective" (plural "objectives")' in told


@pytest.mark.django_db
def test_a_milestone_refusal_uses_the_practices_words(world):
    from apps.crm.models import Task
    from apps.work import milestones
    from apps.work.models import Goal

    custom(world["tenant"])
    goal = Goal.all_objects.get(pk=world["goal"])
    goal.tenant.refresh_from_db()
    stray = Task.all_objects.get(pk=world["tasks"]["sales"])
    with pytest.raises(milestones.MilestoneRefused) as said:
        milestones.check_eligible(stray, goal)
    assert str(said.value) == (
        "That action is not under this objective. An objective's timeline is that "
        "objective's own — an action from elsewhere cannot be a beat on it.")
