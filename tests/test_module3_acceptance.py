"""Module 3 — the task engine. Done-items 1-5 of Phase 3.

Covers AC-3.1 to AC-3.4, the FR-3.10 rollup, the FR-3.6 detach rule, and
FR-3.9a's client-edit rule at each of its four boundaries. Digests (AC-3.5
onwards) and the portal arrive in the next stretch.
"""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Task
from apps.tenancy.models import AuditEvent
from apps.work.models import Comment, Goal, Project, TaskUpdate
from apps.work.status import roll_up

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactFactory, MembershipFactory,
)

S = Task.Status
K = TaskUpdate.Kind


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def make(client, url, **data):
    response = post(client, url, data)
    assert response.status_code == 201, response.content
    return response.json()


@pytest.fixture
def client_company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods")


@pytest.fixture
def portal(seeded_tenant, client_company):
    """An FCC and an ECC at the same client company."""
    return {
        "fcc": MembershipFactory(tenant=seeded_tenant, role="FCC",
                                 client_company=client_company),
        "ecc": MembershipFactory(tenant=seeded_tenant, role="ECC",
                                 client_company=client_company),
    }


# ----------------------------------------------------------------- AC-3.1

@pytest.mark.django_db
def test_ac_3_1_three_levels_and_only_three(seeded_tenant, ff, api, client_company):
    client = api.as_(ff)
    goal = make(client, "/api/goals/", title="Cut order-to-cash to 20 days",
                client_company=str(client_company.pk))
    project = make(client, "/api/projects/", title="Invoice automation",
                   goal=goal["id"], client_company=str(client_company.pk))
    task = make(client, "/api/tasks/", title="Map the current process",
                project=project["id"], client_company=str(client_company.pk))

    assert task["project"] == project["id"]
    assert project["goal"] == goal["id"]

    # There is no column to parent a task to a task, so the API cannot accept
    # one: the cap is structural (FR-3.4).
    refused = patch(client, f"/api/tasks/{task['id']}/", {"project": task["id"]})
    assert refused.status_code == 400
    assert "parent_task" not in json.dumps(task)
    assert not any(f.name == "parent_task" for f in Task._meta.get_fields())

    # Sub-steps are checklist items instead.
    for text in ("Interview AP", "Export invoice log", "Draw the swimlane"):
        assert post(client, f"/api/tasks/{task['id']}/checklist/", {"text": text}
                    ).status_code == 201
    items = client.get(f"/api/tasks/{task['id']}/checklist/").json()
    assert [i["text"] for i in items] == ["Interview AP", "Export invoice log",
                                          "Draw the swimlane"]
    done = patch(client, f"/api/checklist-items/{items[0]['id']}/", {"is_done": True})
    assert done.status_code == 200 and done.json()["is_done"] is True
    assert TaskUpdate.all_objects.filter(task_id=task["id"],
                                         kind=K.CHECKLIST_COMPLETED).count() == 1


@pytest.mark.django_db
def test_ac_3_2_a_standalone_task_is_first_class(seeded_tenant, ff, api):
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="Renew the insurance certificate")
    assert task["project"] is None and task["goal"] is None
    listed = client.get("/api/tasks/").json()
    assert task["id"] in [t["id"] for t in listed]
    assert task["id"] in [t["id"] for t in client.get("/api/tasks/?unfiled=1").json()]


# ----------------------------------------------------------------- AC-3.3

@pytest.mark.django_db
def test_ac_3_3_the_client_facing_line_is_prompted_not_forced(seeded_tenant, ff, api,
                                                              client_company):
    client = api.as_(ff)
    skipped = make(client, "/api/tasks/", title="Skip the line",
                   client_company=str(client_company.pk))
    supplied = make(client, "/api/tasks/", title="Supply the line",
                    client_company=str(client_company.pk))

    # Skipped: the status change still saves.
    assert patch(client, f"/api/tasks/{skipped['id']}/",
                 {"status": S.IN_PROGRESS}).json()["status"] == S.IN_PROGRESS
    update = TaskUpdate.all_objects.get(task_id=skipped["id"], kind=K.STATUS_CHANGED)
    assert update.client_facing_line == ""
    assert update.from_value == S.NOT_STARTED and update.to_value == S.IN_PROGRESS

    # Supplied: stored on the update itself, and not as a comment.
    line = "We can now see where invoices stall; the fix lands next week."
    assert patch(client, f"/api/tasks/{supplied['id']}/",
                 {"status": S.IN_PROGRESS, "client_facing_line": line}).status_code == 200
    stored = TaskUpdate.all_objects.get(task_id=supplied["id"], kind=K.STATUS_CHANGED)
    assert stored.client_facing_line == line
    assert not Comment.all_objects.filter(task_id=supplied["id"]).exists()
    assert line in json.dumps(client.get(f"/api/tasks/{supplied['id']}/updates/").json())


@pytest.mark.django_db
def test_a_narrative_needs_no_status_change(seeded_tenant, ff, api, client_company):
    """FR-3.18 — a client-facing line at any time."""
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="Quiet progress",
                client_company=str(client_company.pk))
    line = "Nothing visible yet; the data pull is running."
    assert post(client, f"/api/tasks/{task['id']}/narrative/",
                {"client_facing_line": line}).status_code == 201
    update = TaskUpdate.all_objects.get(task_id=task["id"], kind=K.NARRATIVE)
    assert update.client_facing_line == line
    assert Task.all_objects.get(pk=task["id"]).status == S.NOT_STARTED


@pytest.mark.django_db
def test_completing_a_task_records_both_the_transition_and_the_completion(
    seeded_tenant, ff, api
):
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="Finish it")
    patch(client, f"/api/tasks/{task['id']}/", {"status": S.DONE})
    kinds = set(TaskUpdate.all_objects.filter(task_id=task["id"])
                .values_list("kind", flat=True))
    assert {K.CREATED, K.STATUS_CHANGED, K.COMPLETED} <= kinds


@pytest.mark.django_db
def test_an_unchanged_field_records_nothing(seeded_tenant, ff, api):
    """A digest assembled from no-op events would report work that never
    happened."""
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="No-op")
    patch(client, f"/api/tasks/{task['id']}/", {"status": S.NOT_STARTED})
    assert not TaskUpdate.all_objects.filter(task_id=task["id"],
                                             kind=K.STATUS_CHANGED).exists()


# ----------------------------------------------------------------- AC-3.4

@pytest.mark.django_db
def test_ac_3_4_internal_comments_never_leak(seeded_tenant, ff, api, client_company, portal):
    staff = api.as_(ff)
    task = make(staff, "/api/tasks/", title="Shared work",
                client_company=str(client_company.pk))
    assert task["is_client_visible"] is True    # FR-3.11

    internal = make(staff, "/api/comments/", task=task["id"],
                    body="Their AP clerk is the bottleneck, handle gently.")
    shared = make(staff, "/api/comments/", task=task["id"], visibility="shared",
                  body="We have mapped the invoice flow and found two delays.")
    assert internal["visibility"] == "internal", "FR-3.12a — internal is the default."

    for member in portal.values():
        viewer = api.as_(member)
        listed = viewer.get(f"/api/comments/?task={task['id']}")
        visible = [c["id"] for c in listed.json()]
        assert shared["id"] in visible and internal["id"] not in visible
        assert all(c["visibility"] == "shared" for c in listed.json())
        raw = listed.content.decode()
        assert "AP clerk is the bottleneck" not in raw

        # Not in the update feed either, where a comment also appears.
        feed = viewer.get(f"/api/tasks/{task['id']}/updates/")
        assert "bottleneck" not in feed.content.decode()
        shared_comments = Comment.all_objects.filter(task_id=task["id"],
                                                     visibility="shared").count()
        assert sum(1 for u in feed.json()
                   if u["kind"] == "comment_added") == shared_comments

        # A client's own comment is always shared; there is no choice to make.
        theirs = make(viewer, "/api/comments/", task=task["id"], body="Noted, thank you.")
        assert theirs["visibility"] == "shared"
        forced = post(viewer, "/api/comments/", {"task": task["id"], "body": "Try internal",
                                                  "visibility": "internal"})
        assert forced.status_code == 201 and forced.json()["visibility"] == "shared"


@pytest.mark.django_db
def test_a_client_never_sees_a_hidden_task_at_all(seeded_tenant, ff, api, client_company,
                                                  portal):
    staff = api.as_(ff)
    hidden = make(staff, "/api/tasks/", title="Fee review — internal",
                  client_company=str(client_company.pk), is_client_visible=False)
    viewer = api.as_(portal["fcc"])
    assert viewer.get("/api/tasks/").json() == []
    assert viewer.get(f"/api/tasks/{hidden['id']}/").status_code == 404
    assert post(viewer, "/api/comments/", {"task": hidden["id"], "body": "?"}
                ).status_code == 404
    assert "Fee review" not in viewer.get("/api/tasks/").content.decode()


@pytest.mark.django_db
def test_visibility_changes_are_audited_in_both_directions(seeded_tenant, ff, api,
                                                            client_company):
    """FR-3.14."""
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="Toggle me",
                client_company=str(client_company.pk))
    patch(client, f"/api/tasks/{task['id']}/", {"is_client_visible": False})
    patch(client, f"/api/tasks/{task['id']}/", {"is_client_visible": True})
    events = AuditEvent.all_objects.filter(verb="task.visibility_changed",
                                           target_id=task["id"]).order_by("created_at")
    assert [e.payload["is_client_visible"] for e in events] == [False, True]


# ------------------------------------------------- FR-3.10, the derived status

@pytest.mark.django_db
@pytest.mark.parametrize("children,expected", [
    ([], S.NOT_STARTED),
    ([S.NOT_STARTED, S.NOT_STARTED], S.NOT_STARTED),
    ([S.DONE, S.DONE], S.DONE),
    ([S.CANCELLED, S.CANCELLED], S.CANCELLED),
    ([S.DONE, S.CANCELLED], S.DONE),
    ([S.DONE, S.NOT_STARTED], S.IN_PROGRESS),
    ([S.IN_PROGRESS, S.DONE], S.IN_PROGRESS),
    ([S.BLOCKED, S.IN_PROGRESS], S.BLOCKED),
    # FR-3.8 — "you are the blocker" is the most useful thing to surface.
    ([S.WAITING_ON_CLIENT, S.BLOCKED, S.IN_PROGRESS], S.WAITING_ON_CLIENT),
])
def test_the_rollup_rule(children, expected):
    assert roll_up(children) == expected


@pytest.mark.django_db
def test_a_parents_status_is_derived_until_overridden_and_never_stored(
    seeded_tenant, ff, api, client_company
):
    client = api.as_(ff)
    goal = make(client, "/api/goals/", title="Goal", client_company=str(client_company.pk))
    project = make(client, "/api/projects/", title="Project", goal=goal["id"],
                   client_company=str(client_company.pk))
    task = make(client, "/api/tasks/", title="Task", project=project["id"],
                client_company=str(client_company.pk))

    assert client.get(f"/api/goals/{goal['id']}/").json()["status"] == S.NOT_STARTED
    patch(client, f"/api/tasks/{task['id']}/", {"status": S.WAITING_ON_CLIENT})

    shown = client.get(f"/api/goals/{goal['id']}/").json()
    assert shown["status"] == S.WAITING_ON_CLIENT     # up through the project
    assert shown["status_is_derived"] is True and shown["status_override"] is None
    assert Goal.all_objects.get(pk=goal["id"]).status_override is None, (
        "The derived value was stored; it will drift."
    )

    overridden = patch(client, f"/api/goals/{goal['id']}/", {"status_override": S.BLOCKED})
    assert overridden.json()["status"] == S.BLOCKED
    assert overridden.json()["status_is_derived"] is False

    cleared = patch(client, f"/api/goals/{goal['id']}/", {"status_override": None})
    assert cleared.json()["status"] == S.WAITING_ON_CLIENT
    assert cleared.json()["status_is_derived"] is True


@pytest.mark.django_db
def test_all_six_statuses_are_accepted_and_waiting_on_client_is_its_own(seeded_tenant, ff, api):
    """Done-item 2. `waiting_on_client` is not a flavour of `blocked`."""
    client = api.as_(ff)
    task = make(client, "/api/tasks/", title="Cycle through")
    for status in (S.IN_PROGRESS, S.BLOCKED, S.WAITING_ON_CLIENT, S.DONE, S.CANCELLED,
                   S.NOT_STARTED):
        assert patch(client, f"/api/tasks/{task['id']}/",
                     {"status": status}).json()["status"] == status
    assert patch(client, f"/api/tasks/{task['id']}/", {"status": "invented"}).status_code == 400
    assert S.WAITING_ON_CLIENT != S.BLOCKED


# --------------------------------------------------------- FR-3.6, detaching

@pytest.mark.django_db
def test_deleting_a_parent_detaches_its_children_and_reports_them(seeded_tenant, ff, api,
                                                                  client_company):
    client = api.as_(ff)
    goal = make(client, "/api/goals/", title="Goal", client_company=str(client_company.pk))
    project = make(client, "/api/projects/", title="Project", goal=goal["id"],
                   client_company=str(client_company.pk))
    task = make(client, "/api/tasks/", title="Task", project=project["id"],
                client_company=str(client_company.pk))
    direct = make(client, "/api/tasks/", title="Straight on the goal", goal=goal["id"],
                  client_company=str(client_company.pk))

    removed = client.delete(f"/api/goals/{goal['id']}/")
    assert removed.status_code == 200
    assert removed.json()["detached"] == {"projects": 1, "tasks": 1}

    assert Project.all_objects.get(pk=project["id"]).goal_id is None
    assert Task.all_objects.get(pk=direct["id"]).goal_id is None
    assert Task.all_objects.get(pk=task["id"]).deleted_at is None, "Work was deleted."
    assert AuditEvent.all_objects.filter(verb="goal.deleted").exists()

    detached = client.delete(f"/api/projects/{project['id']}/").json()["detached"]
    assert detached == {"tasks": 1}
    assert Task.all_objects.get(pk=task["id"]).project_id is None


# ------------------------------------- FR-3.9a, the client-edit rule's bounds

@pytest.mark.django_db
def test_fr_3_9a_boundary_1_a_task_assigned_to_a_fractional_is_read_only(
    seeded_tenant, ff, api, client_company, portal
):
    staff = api.as_(ff)
    task = make(staff, "/api/tasks/", title="Ours to do",
                client_company=str(client_company.pk), assignee=str(ff.user_id))
    viewer = api.as_(portal["fcc"])
    assert viewer.get(f"/api/tasks/{task['id']}/").json()["may_edit"] is False
    refused = patch(viewer, f"/api/tasks/{task['id']}/", {"status": S.DONE})
    assert refused.status_code == 403 and "practice" in refused.json()["detail"]
    assert Task.all_objects.get(pk=task["id"]).status == S.NOT_STARTED
    # ...but a shared comment is always open to them.
    assert post(viewer, "/api/comments/", {"task": task["id"], "body": "Any news?"}
                ).status_code == 201


@pytest.mark.django_db
def test_fr_3_9a_boundary_1b_a_task_assigned_to_a_client_user_is_theirs_to_edit(
    seeded_tenant, ff, api, client_company, portal
):
    staff = api.as_(ff)
    task = make(staff, "/api/tasks/", title="Yours to do",
                client_company=str(client_company.pk),
                assignee=str(portal["ecc"].user_id))
    viewer = api.as_(portal["fcc"])
    assert viewer.get(f"/api/tasks/{task['id']}/").json()["may_edit"] is True
    assert patch(viewer, f"/api/tasks/{task['id']}/",
                 {"status": S.DONE}).json()["status"] == S.DONE
    update = TaskUpdate.all_objects.filter(task_id=task["id"], kind=K.STATUS_CHANGED).first()
    assert update.is_client_actor is True


@pytest.mark.django_db
def test_fr_3_9a_boundary_2_a_client_can_only_assign_within_their_company(
    seeded_tenant, ff, cf, api, client_company, portal
):
    viewer = api.as_(portal["fcc"])
    task = make(viewer, "/api/tasks/", title="Mine")
    assert patch(viewer, f"/api/tasks/{task['id']}/",
                 {"assignee": str(portal["ecc"].user_id)}).status_code == 200
    for outsider in (ff.user_id, cf.user_id):
        refused = patch(viewer, f"/api/tasks/{task['id']}/", {"assignee": str(outsider)})
        assert refused.status_code == 400
        assert "your own company" in refused.content.decode()

    other_company = ClientCompanyFactory(tenant=seeded_tenant, name="Someone else")
    elsewhere = MembershipFactory(tenant=seeded_tenant, role="ECC",
                                  client_company=other_company)
    assert patch(viewer, f"/api/tasks/{task['id']}/",
                 {"assignee": str(elsewhere.user_id)}).status_code == 400


@pytest.mark.django_db
def test_fr_3_9a_boundary_3_a_client_deletes_only_what_they_created(
    seeded_tenant, ff, api, client_company, portal
):
    staff = api.as_(ff)
    theirs = make(api.as_(portal["fcc"]), "/api/tasks/", title="Client's own")
    assigned = make(staff, "/api/tasks/", title="Assigned to the client",
                    client_company=str(client_company.pk),
                    assignee=str(portal["fcc"].user_id))
    colleagues = make(api.as_(portal["ecc"]), "/api/tasks/", title="A colleague's")

    viewer = api.as_(portal["fcc"])
    assert viewer.delete(f"/api/tasks/{theirs['id']}/").status_code == 204
    # Editable, but not deletable: the fractional assigned it.
    assert viewer.get(f"/api/tasks/{assigned['id']}/").json()["may_edit"] is True
    assert viewer.delete(f"/api/tasks/{assigned['id']}/").status_code == 403
    assert viewer.delete(f"/api/tasks/{colleagues['id']}/").status_code == 403
    assert Task.all_objects.get(pk=assigned["id"]).deleted_at is None


@pytest.mark.django_db
def test_fr_3_9a_boundary_4_a_client_cannot_change_visibility(seeded_tenant, ff, api,
                                                               client_company, portal):
    """Matrix 7.7 — a client cannot hide work from their own company."""
    viewer = api.as_(portal["fcc"])
    task = make(viewer, "/api/tasks/", title="Mine")
    assert viewer.get(f"/api/tasks/{task['id']}/").json()["may_set_visibility"] is False
    refused = patch(viewer, f"/api/tasks/{task['id']}/", {"is_client_visible": False})
    assert refused.status_code == 400
    assert Task.all_objects.get(pk=task["id"]).is_client_visible is True


@pytest.mark.django_db
def test_a_client_created_task_belongs_to_their_company_and_is_visible(
    seeded_tenant, ff, api, client_company, portal
):
    """FR-3.36/3.37 — no review queue stands between a client and their own work."""
    created = make(api.as_(portal["fcc"]), "/api/tasks/", title="Chase the supplier")
    assert created["created_by_client"] is True
    assert created["client_company"] == str(client_company.pk)
    assert created["is_client_visible"] is True
    assert api.as_(ff).get(f"/api/tasks/{created['id']}/").status_code == 200


# ------------------------------------------------------------- CF assignment

@pytest.mark.django_db
def test_a_cf_sees_only_assigned_client_work(seeded_tenant, ff, cf, api):
    staff = api.as_(ff)
    assigned = ClientCompanyFactory(tenant=seeded_tenant, name="Assigned")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=assigned)
    other = ClientCompanyFactory(tenant=seeded_tenant, name="Not assigned")

    mine = make(staff, "/api/goals/", title="Assigned goal",
                client_company=str(assigned.pk))
    hidden = make(staff, "/api/goals/", title="Other goal", client_company=str(other.pk))
    task_hidden = make(staff, "/api/tasks/", title="Other task",
                       client_company=str(other.pk))

    viewer = api.as_(cf)
    assert [g["id"] for g in viewer.get("/api/goals/").json()] == [mine["id"]]
    assert viewer.get(f"/api/goals/{hidden['id']}/").status_code == 404
    assert viewer.get(f"/api/tasks/{task_hidden['id']}/").status_code == 404
    # Attaching work to a company they are not assigned to is refused.
    assert post(viewer, "/api/goals/", {"title": "Sneak", "client_company": str(other.pk)}
                ).status_code == 400


@pytest.mark.django_db
def test_client_owner_contact_is_carried_on_all_three_levels(seeded_tenant, ff, api,
                                                              client_company):
    """Done-item 3 / FR-3.3a — who on the client side is accountable, as a
    Contact, because both upstream sources name people without logins."""
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant, first_name="Maria", last_name="Diaz",
                             company=client_company)
    for url, extra in (("/api/goals/", {}), ("/api/projects/", {}), ("/api/tasks/", {})):
        created = make(client, url, title=f"With a client owner {url}",
                       client_company=str(client_company.pk),
                       client_owner_contact=str(contact.pk), **extra)
        assert created["client_owner_contact"]["name"] == "Maria Diaz"
