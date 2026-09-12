"""Module 3 — the client portal, seats and isolation.

AC-3.13 to AC-3.18, AC-3.27 to AC-3.31, AC-3.37 to AC-3.39, and the
client-company isolation family (FR-0.2): two companies in the SAME tenant must
be as invisible to each other as two tenants are.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.crm.models import Task
from apps.tenancy.models import AuditEvent, Membership
from apps.work.models import Goal, Project, Stakeholder

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    GoalFactory, MembershipFactory, ProjectFactory,
)

S = Task.Status


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def make(client, url, **data):
    response = post(client, url, data)
    assert response.status_code == 201, response.content
    return response.json()


def a_contact(tenant, company, first="Dana", email=None):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address=email or f"{first.lower()}@northwind.invalid")
    return contact


@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=2)


@pytest.fixture
def fcc(seeded_tenant, company):
    contact = a_contact(seeded_tenant, company, "Dana")
    return MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company,
                             contact=contact)


@pytest.fixture
def ecc(seeded_tenant, company):
    contact = a_contact(seeded_tenant, company, "Priya", "priya@northwind.invalid")
    return MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=company,
                             contact=contact)


# ---------------------------------------------------------------- AC-3.13

@pytest.mark.django_db
def test_ac_3_13_client_creation_is_immediate_and_notifies_the_practice(
    seeded_tenant, ff, api, company, fcc, ecc, dev_outbox, in_tenant_a
):
    from apps.work.tasks import notify_client_activity

    client = api.as_(fcc)
    task = make(client, "/api/tasks/", title="Chase the supplier")
    assert patch(client, f"/api/tasks/{task['id']}/",
                 {"assignee": str(ecc.user_id)}).status_code == 200
    assert make(client, "/api/comments/", task=task["id"], body="Booked for Thursday.")

    # No review queue anywhere in that path (FR-3.36).
    from apps.crm.models import OutboxMessage

    assert not OutboxMessage.all_objects.filter(state="pending_approval").exists()

    # The practice hears about it, once, after the quiet window.
    assert notify_client_activity(seeded_tenant) == 0          # still inside it
    later = timezone.now() + timezone.timedelta(minutes=31)
    assert notify_client_activity(seeded_tenant, now=later) == 1
    notice = [m for m in dev_outbox if "Client activity" in m.subject]
    assert len(notice) == 1
    assert "Chase the supplier" in notice[0].body
    assert notice[0].to == [ff.user.email]
    # And not again on the next run.
    assert notify_client_activity(seeded_tenant, now=later) == 0


# ---------------------------------------------------------------- AC-3.14

@pytest.mark.django_db
def test_ac_3_14_the_assignee_picker_lists_only_their_own_company(
    seeded_tenant, ff, cf, api, company, fcc, ecc, in_tenant_a
):
    other_company = ClientCompanyFactory(tenant=seeded_tenant, name="Elsewhere")
    outsider = MembershipFactory(tenant=seeded_tenant, role="ECC",
                                 client_company=other_company)
    client = api.as_(fcc)
    people = client.get("/api/portal-people/").json()
    assert {p["id"] for p in people} == {str(fcc.user_id), str(ecc.user_id)}

    task = make(client, "/api/tasks/", title="Mine")
    for stranger in (ff.user_id, cf.user_id, outsider.user_id):
        refused = patch(client, f"/api/tasks/{task['id']}/", {"assignee": str(stranger)})
        assert refused.status_code == 400, stranger
    assert patch(client, f"/api/tasks/{task['id']}/",
                 {"assignee": str(ecc.user_id)}).status_code == 200


# --------------------------------------------------------- AC-3.15, AC-3.16

@pytest.mark.django_db
def test_ac_3_15_the_on_demand_report_renders_without_email_or_approval(
    seeded_tenant, ff, api, company, fcc, dev_outbox, in_tenant_a
):
    from apps.work.services import apply_task_changes, create_task

    task = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                       title="Invoice automation", client_company=company)
    apply_task_changes(task, actor=ff.user, role="FF",
                       changes={"status": S.WAITING_ON_CLIENT},
                       client_facing_line="We need your AP login to finish.")

    report = api.as_(fcc).get("/api/progress-report/?days=30")
    assert report.status_code == 200
    body = report.json()["body_text"]
    assert "We need your AP login to finish." in body
    assert "waiting_on_client" in body, "AC-3.16 — the distinction survives into the text."
    assert "blocked" not in body
    assert dev_outbox == [], "A pulled report must send nothing."


@pytest.mark.django_db
def test_the_report_shows_only_client_visible_work(seeded_tenant, ff, api, company, fcc,
                                                    in_tenant_a):
    from apps.work.services import apply_task_changes, create_task

    hidden = create_task(tenant=seeded_tenant, actor=ff.user, role="FF", title="Fee review",
                         client_company=company, is_client_visible=False)
    apply_task_changes(hidden, actor=ff.user, role="FF", changes={"status": S.IN_PROGRESS},
                       client_facing_line="Internal only.")
    body = api.as_(fcc).get("/api/progress-report/?days=30").json()["body_text"]
    assert "Fee review" not in body and "Internal only." not in body


# ---------------------------------------------------------------- AC-3.17

@pytest.mark.django_db
def test_ac_3_17_client_company_isolation_inside_one_tenant(seeded_tenant, ff, api,
                                                             company, fcc, in_tenant_a):
    """FR-0.2 — the separate family. Two companies in the SAME tenant."""
    from apps.work.services import add_comment, create_task

    other = ClientCompanyFactory(tenant=seeded_tenant, name="Company B")
    b_goal = GoalFactory(tenant=seeded_tenant, title="B's goal", client_company=other)
    b_project = ProjectFactory(tenant=seeded_tenant, title="B's project", client_company=other)
    b_task = create_task(tenant=seeded_tenant, actor=ff.user, role="FF", title="B's task",
                         client_company=other)
    b_comment = add_comment(b_task, author=ff.user, role="FF", body="B's shared note",
                            visibility="shared")
    b_contact = a_contact(seeded_tenant, other, "Bea", "bea@companyb.invalid")

    viewer = api.as_(fcc)
    for path in (f"/api/goals/{b_goal.pk}/", f"/api/projects/{b_project.pk}/",
                 f"/api/tasks/{b_task.pk}/", f"/api/comments/?task={b_task.pk}",
                 f"/api/progress-report/?contact={b_contact.pk}"):
        response = viewer.get(path)
        assert response.status_code in (400, 403, 404), path
        assert "B's" not in response.content.decode(), path

    # Nor by listing.
    assert viewer.get("/api/goals/").json() == []
    assert viewer.get("/api/tasks/").json() == []
    # A report for their own company shows nothing of B's.
    assert "B's" not in viewer.get("/api/progress-report/?days=30").content.decode()


@pytest.mark.django_db
def test_client_company_isolation_across_tenants(tenant_a, tenant_b, api):
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_a)
    seed_tenant(tenant_b)
    b_company = ClientCompanyFactory(tenant=tenant_b, name="Bravo Ltd")
    b_goal = GoalFactory(tenant=tenant_b, title="Bravo goal", client_company=b_company)
    a_company = ClientCompanyFactory(tenant=tenant_a, name="Alpha Ltd")
    a_fcc = MembershipFactory(tenant=tenant_a, role="FCC", client_company=a_company)

    viewer = api.as_(a_fcc)
    assert viewer.get(f"/api/goals/{b_goal.pk}/").status_code == 404
    assert viewer.get("/api/goals/").json() == []


# ---------------------------------------------------------- AC-3.37, 3.38

@pytest.mark.django_db
def test_ac_3_37_the_client_edit_rule_at_all_four_boundaries(seeded_tenant, ff, api,
                                                              company, fcc, ecc, in_tenant_a):
    from apps.work.services import create_task

    created_by_client = make(api.as_(fcc), "/api/tasks/", title="(i) client created")
    to_client = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                            title="(ii) assigned to a client", client_company=company,
                            assignee=ecc.user, is_client_visible=True)
    to_tenant = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                            title="(iii) assigned to a fractional", client_company=company,
                            assignee=ff.user, is_client_visible=True)
    elsewhere = ClientCompanyFactory(tenant=seeded_tenant, name="Another company")
    other_fcc = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=elsewhere)
    theirs = make(api.as_(other_fcc), "/api/tasks/", title="(iv) another company's")

    viewer = api.as_(ecc)
    for task_id in (created_by_client["id"], str(to_client.pk)):
        assert patch(viewer, f"/api/tasks/{task_id}/",
                     {"status": S.IN_PROGRESS}).status_code == 200
    assert patch(viewer, f"/api/tasks/{to_tenant.pk}/",
                 {"status": S.DONE}).status_code == 403
    assert post(viewer, "/api/comments/",
                {"task": str(to_tenant.pk), "body": "Any news?"}).status_code == 201
    assert viewer.get(f"/api/tasks/{theirs['id']}/").status_code == 404

    # Reassignment: a colleague yes, a fractional or another company no.
    assert patch(viewer, f"/api/tasks/{created_by_client['id']}/",
                 {"assignee": str(fcc.user_id)}).status_code == 200
    for stranger in (ff.user_id, other_fcc.user_id):
        assert patch(viewer, f"/api/tasks/{created_by_client['id']}/",
                     {"assignee": str(stranger)}).status_code == 400


@pytest.mark.django_db
def test_ac_3_38_clients_delete_only_what_they_created(seeded_tenant, ff, api, company,
                                                       fcc, ecc, in_tenant_a):
    from apps.work.services import create_task

    mine = make(api.as_(fcc), "/api/tasks/", title="Mine to delete")
    assigned = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                           title="Editable, not deletable", client_company=company,
                           assignee=fcc.user, is_client_visible=True)
    viewer = api.as_(fcc)
    assert viewer.delete(f"/api/tasks/{mine['id']}/").status_code == 204
    assert patch(viewer, f"/api/tasks/{assigned.pk}/", {"status": S.DONE}).status_code == 200
    assert viewer.delete(f"/api/tasks/{assigned.pk}/").status_code == 403
    assigned.refresh_from_db()
    assert assigned.deleted_at is None


@pytest.mark.django_db
def test_ac_3_39_clients_create_projects_but_never_goals(seeded_tenant, api, company, fcc,
                                                          in_tenant_a):
    client = api.as_(fcc)
    assert post(client, "/api/goals/", {"title": "Our strategy"}).status_code == 403

    project = make(client, "/api/projects/", title="Our own tidy-up")
    assert project["created_by_client"] is True and project["goal"] is None
    assert project["client_company"] == str(company.pk)

    for title in ("First", "Second"):
        task = make(client, "/api/tasks/", title=title, project=project["id"])
        assert task["is_client_visible"] is True and task["created_by_client"] is True
    listed = client.get(f"/api/tasks/?project={project['id']}").json()
    assert len(listed) == 2


# ------------------------------------------------- AC-3.27 to AC-3.31, seats

@pytest.mark.django_db
def test_ac_3_27_a_grant_creates_the_login_consumes_a_seat_and_sends_a_link(
    seeded_tenant, ff, api, company, dev_outbox, in_tenant_a
):
    from apps.accounts.models import User

    founder = a_contact(seeded_tenant, company, "Dana")
    company.primary_contact = founder
    company.save()
    employee = a_contact(seeded_tenant, company, "Priya", "priya@northwind.invalid")

    first = make(api.as_(ff), "/api/portal-access/", contact=str(founder.pk))
    assert first["role"] == "FCC", "The primary contact is the founder by default."
    assert User.objects.filter(email="dana@northwind.invalid").exists()
    assert any("Sign in to" in m.subject for m in dev_outbox)

    second = make(api.as_(ff), "/api/portal-access/", contact=str(employee.pk))
    assert second["role"] == "ECC"

    seats = api.as_(ff).get(f"/api/portal-access/?company={company.pk}").json()
    assert seats["seats_in_use"] == 2 and seats["seats_available"] == 0
    assert len(seats["people"]) == 2


@pytest.mark.django_db
def test_ac_3_28_seat_exhaustion_fails_clearly_and_creates_nothing(
    seeded_tenant, ff, api, company, fcc, ecc, dev_outbox, in_tenant_a
):
    from apps.accounts.models import User

    third = a_contact(seeded_tenant, company, "Sam", "sam@northwind.invalid")
    before = User.objects.count()
    dev_outbox.clear()

    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(third.pk)})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "2 seats" in detail and "2 in use" in detail
    assert User.objects.count() == before, "A refused grant created a login."
    assert dev_outbox == [], "A refused grant sent a link."
    assert not Membership.all_objects.filter(contact=third).exists()


@pytest.mark.django_db
def test_ac_3_29_revoking_frees_the_seat_and_cuts_access_but_deletes_nothing(
    seeded_tenant, ff, api, company, fcc, ecc, in_tenant_a
):
    from apps.accounts.models import MagicLinkToken
    from apps.work.services import add_comment, create_task

    task = create_task(tenant=seeded_tenant, actor=ecc.user, role="ECC",
                       title="Priya's task", client_company=company)
    comment = add_comment(task, author=ecc.user, role="ECC", body="Mine.")
    stakeholder = Stakeholder.all_objects.create(tenant=seeded_tenant, contact=ecc.contact,
                                                 task=task, cadence="weekly")
    _, raw = MagicLinkToken.issue(tenant=seeded_tenant, user=ecc.user)

    theirs = Client()
    theirs.force_login(ecc.user)
    assert theirs.get("/api/me").json()["role"] == "ECC"

    revoked = api.as_(ff).delete(f"/api/portal-access/{ecc.pk}/")
    assert revoked.status_code == 200 and revoked.json()["sessions_ended"] >= 1

    assert theirs.get("/api/tasks/").status_code in (401, 403)
    assert theirs.get("/api/me").status_code == 401
    assert Client().post(f"/auth/magic/{raw}").status_code == 400, "An old link still worked."

    assert company.seats_in_use == 1, "The seat was not freed."
    task.refresh_from_db()
    assert task.deleted_at is None
    assert type(comment).all_objects.filter(pk=comment.pk).exists()
    assert Stakeholder.all_objects.filter(pk=stakeholder.pk).exists(), (
        "Revocation is not deletion: they still receive digests (FR-3.33g)."
    )
    assert AuditEvent.all_objects.filter(verb="portal.access_revoked").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 201), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_ac_3_30_only_ff_and_assigned_cf_grant_access(role, expected, seeded_tenant, api,
                                                       company, in_tenant_a):
    contact = a_contact(seeded_tenant, company, "Newbie", "newbie@northwind.invalid")
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    response = post(api.as_(member), "/api/portal-access/", {"contact": str(contact.pk)})
    assert response.status_code == expected


@pytest.mark.django_db
def test_a_cf_cannot_grant_on_a_company_they_are_not_assigned(seeded_tenant, cf, api,
                                                               company, in_tenant_a):
    contact = a_contact(seeded_tenant, company, "Nope", "nope@northwind.invalid")
    assert post(api.as_(cf), "/api/portal-access/",
                {"contact": str(contact.pk)}).status_code == 404


@pytest.mark.django_db
def test_ac_3_31_lowering_the_seat_count_revokes_nobody_and_blocks_the_next_grant(
    seeded_tenant, ff, va, api, company, fcc, ecc, in_tenant_a
):
    assert api.as_(ff).patch(f"/api/companies/{company.pk}/",
                             json.dumps({"seat_count": 1}),
                             content_type="application/json").status_code == 200
    company.refresh_from_db()
    assert company.seats_in_use == 2 and company.seat_count == 1
    for member in (fcc, ecc):
        member.refresh_from_db()
        assert member.revoked_at is None, "Lowering the count revoked someone."

    third = a_contact(seeded_tenant, company, "Sam", "sam2@northwind.invalid")
    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(third.pk)})
    assert refused.status_code == 409 and "1 seat" in refused.json()["detail"]

    # Matrix 4.12 — seat count is the FF's.
    assert api.as_(va).patch(f"/api/companies/{company.pk}/",
                             json.dumps({"seat_count": 5}),
                             content_type="application/json").status_code == 403
