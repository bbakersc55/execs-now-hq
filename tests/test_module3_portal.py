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


# ======================================= the picker: who can be granted, and why not

@pytest.mark.django_db
def test_the_picker_lists_this_companys_people_without_any_typing(
    seeded_tenant, ff, api, company, in_tenant_a
):
    """The bug this replaces: the picker ran the global contact search, so it
    found nobody until a whole indexed word was typed and offered people at
    companies that are not clients. Three contacts at a client company must be
    offered with an empty box."""
    elsewhere = ClientCompanyFactory(tenant=seeded_tenant, name="Other Co", seat_count=1)
    for first in ("Ama", "Bene", "Chidi"):
        a_contact(seeded_tenant, company, first, f"{first.lower()}@northwind.invalid")
    a_contact(seeded_tenant, elsewhere, "Outsider", "outsider@other.invalid")

    body = api.as_(ff).get(f"/api/portal-access/candidates/?company={company.pk}").json()
    assert [p["name"] for p in body["people"]] == ["Ama Okafor", "Bene Okafor", "Chidi Okafor"]
    assert all(p["refusal"] is None for p in body["people"])
    assert body["is_client_company"] is True and body["seat_count"] == 2


@pytest.mark.django_db
def test_the_picker_narrows_on_a_fragment_of_a_name_or_an_email(
    seeded_tenant, ff, api, company, in_tenant_a
):
    """`q` is what someone half-types, not a full-text word."""
    a_contact(seeded_tenant, company, "Ama", "ama.nwosu@northwind.invalid")
    a_contact(seeded_tenant, company, "Bene", "bene@northwind.invalid")

    def names(term):
        return [p["name"] for p in api.as_(ff).get(
            f"/api/portal-access/candidates/?company={company.pk}&q={term}").json()["people"]]

    assert names("A") == ["Ama Okafor"]
    assert names("Am") == ["Ama Okafor"]
    assert names("ama.nw") == ["Ama Okafor"]
    assert names("northwind.invalid") == ["Ama Okafor", "Bene Okafor"]
    assert names("Zzz") == []


@pytest.mark.django_db
def test_the_picker_says_why_someone_cannot_be_granted(seeded_tenant, ff, api,
                                                        company, in_tenant_a):
    """Every reason is the sentence the grant itself would have refused with."""
    from apps.crm.models import Contact

    no_email = ContactFactory(tenant=seeded_tenant, first_name="Silent", last_name="Okafor",
                              company=company)
    already = a_contact(seeded_tenant, company, "Dana", "dana@northwind.invalid")
    make(api.as_(ff), "/api/portal-access/", contact=str(already.pk))

    rows = {p["contact"]: p for p in api.as_(ff).get(
        f"/api/portal-access/candidates/?company={company.pk}").json()["people"]}
    assert "no email address" in rows[str(no_email.pk)]["refusal"]
    assert "already has access" in rows[str(already.pk)]["refusal"]

    # The refusal the picker shows is the refusal the API gives.
    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(no_email.pk)})
    assert refused.status_code == 400
    assert refused.json()["detail"] == rows[str(no_email.pk)]["refusal"]
    assert Contact.objects.filter(pk=no_email.pk).exists()


@pytest.mark.django_db
def test_the_contact_page_can_grant_without_a_search_at_all(seeded_tenant, ff, api,
                                                             company, in_tenant_a):
    """`?contact=` is the contact page's own card: one row, no searching."""
    contact = a_contact(seeded_tenant, company, "Dana", "dana@northwind.invalid")
    body = api.as_(ff).get(f"/api/portal-access/candidates/?contact={contact.pk}").json()
    assert [p["name"] for p in body["people"]] == ["Dana Okafor"]
    assert body["people"][0]["refusal"] is None
    assert body["company_name"] == "Northwind Foods"
    make(api.as_(ff), "/api/portal-access/", contact=str(contact.pk))

    after = api.as_(ff).get(f"/api/portal-access/candidates/?contact={contact.pk}").json()
    assert "already has access" in after["people"][0]["refusal"]


@pytest.mark.django_db
def test_a_contact_at_a_company_that_is_not_a_client_is_refused_in_words(
    seeded_tenant, ff, api, in_tenant_a
):
    """FR-3.33c — nothing to give access to, said plainly rather than silently."""
    from apps.crm.models import Company

    prospect = Company.objects.create(tenant=seeded_tenant, name="Just A Prospect",
                                      is_client_company=False)
    contact = a_contact(seeded_tenant, prospect, "Hope", "hope@prospect.invalid")

    body = api.as_(ff).get(f"/api/portal-access/candidates/?contact={contact.pk}").json()
    assert body["is_client_company"] is False
    assert "not at a client company" in body["people"][0]["refusal"]

    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(contact.pk)})
    assert refused.status_code == 400
    assert "not at a client company" in refused.json()["detail"]


@pytest.mark.django_db
def test_a_client_company_with_no_seat_count_refuses_in_its_own_words(
    seeded_tenant, ff, api, dev_outbox, in_tenant_a
):
    """`seat_count` is null until the company is set up as a client (§data model),
    so null refuses — but it used to refuse saying "has None seats and 0 in use"."""
    from apps.accounts.models import User

    company = ClientCompanyFactory(tenant=seeded_tenant, name="Unallocated Ltd",
                                   seat_count=None)
    contact = a_contact(seeded_tenant, company, "Dana", "dana@unallocated.invalid")
    before = User.objects.count()
    dev_outbox.clear()

    body = api.as_(ff).get(f"/api/portal-access/candidates/?company={company.pk}").json()
    assert "No seats have been allocated" in body["seat_refusal"]
    assert "None seats" not in body["seat_refusal"]
    assert "No seats have been allocated" in body["people"][0]["refusal"]

    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(contact.pk)})
    assert refused.status_code == 409
    assert "No seats have been allocated to Unallocated Ltd" in refused.json()["detail"]
    assert User.objects.count() == before and dev_outbox == []
    assert not Membership.all_objects.filter(contact=contact).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_who_may_see_the_picker(role, expected, seeded_tenant, api, company, in_tenant_a):
    """Matrix §9 — the same scope as granting: a VA never grants, so a VA is
    never shown who could be granted."""
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    response = api.as_(member).get(f"/api/portal-access/candidates/?company={company.pk}")
    assert response.status_code == expected


@pytest.mark.django_db
def test_the_picker_is_blind_to_other_companies_and_other_tenants(
    seeded_tenant, tenant_b, cf, ff, api, company, in_tenant_a
):
    unassigned = ClientCompanyFactory(tenant=seeded_tenant, name="Not Mine", seat_count=2)
    theirs = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=2)
    mine = a_contact(seeded_tenant, unassigned, "Nope", "nope@notmine.invalid")

    # A CF sees only companies they are assigned.
    assert api.as_(cf).get(
        f"/api/portal-access/candidates/?company={unassigned.pk}").status_code == 404
    assert api.as_(cf).get(
        f"/api/portal-access/candidates/?contact={mine.pk}").status_code == 404
    # Nobody reaches another tenant's company, FF included.
    assert api.as_(ff).get(
        f"/api/portal-access/candidates/?company={theirs.pk}").status_code == 404


# =================================== matrix 9.2: choose FCC vs ECC on the grant

@pytest.mark.django_db
def test_9_2_the_grant_takes_the_role_chosen_over_the_default(
    seeded_tenant, ff, api, company, in_tenant_a
):
    founder = a_contact(seeded_tenant, company, "Dana")
    company.primary_contact = founder
    company.save()
    employee = a_contact(seeded_tenant, company, "Priya", "priya@northwind.invalid")

    # The picker offers each person's default, which is what the control preselects.
    rows = {p["contact"]: p["role"] for p in api.as_(ff).get(
        f"/api/portal-access/candidates/?company={company.pk}").json()["people"]}
    assert rows == {str(founder.pk): "FCC", str(employee.pk): "ECC"}

    # ...and the person granting may choose otherwise, either way round.
    assert make(api.as_(ff), "/api/portal-access/",
                contact=str(founder.pk), role="ECC")["role"] == "ECC"
    assert make(api.as_(ff), "/api/portal-access/",
                contact=str(employee.pk), role="FCC")["role"] == "FCC"
    audited = AuditEvent.all_objects.filter(verb="portal.access_granted")
    assert sorted(e.payload["role"] for e in audited) == ["ECC", "FCC"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "owner"])
def test_9_2_a_grant_never_makes_anything_but_a_client_user(role, seeded_tenant, ff, api,
                                                           company, dev_outbox, in_tenant_a):
    contact = a_contact(seeded_tenant, company, "Sneaky", "sneaky@northwind.invalid")
    dev_outbox.clear()
    refused = post(api.as_(ff), "/api/portal-access/", {"contact": str(contact.pk), "role": role})
    assert refused.status_code == 400 and "FCC or ECC" in refused.json()["detail"]
    assert not Membership.all_objects.filter(contact=contact).exists()
    assert dev_outbox == []


# ============================= matrix 9.2a: change an existing portal user's role

def role_change(client, membership, role):
    return patch(client, f"/api/portal-access/{membership.pk}/", {"role": role})


@pytest.mark.django_db
def test_9_2a_narrowing_ends_sessions_and_links_but_keeps_access(
    seeded_tenant, ff, api, company, fcc, in_tenant_a
):
    from apps.accounts.models import MagicLinkToken

    _, raw = MagicLinkToken.issue(tenant=seeded_tenant, user=fcc.user)
    theirs = Client()
    theirs.force_login(fcc.user)
    assert theirs.get("/api/me").json()["role"] == "FCC"

    response = role_change(api.as_(ff), fcc, "ECC")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["role"] == "ECC" and body["changed"] is True
    assert body["sessions_ended"] >= 1 and body["links_invalidated"] == 1

    assert theirs.get("/api/me").status_code == 401, "A founder session outlived the change."
    assert Client().post(f"/auth/magic/{raw}").status_code == 400, "An old link still worked."

    fcc.refresh_from_db()
    assert fcc.role == "ECC" and fcc.revoked_at is None, "A role change is not a revoke."
    assert company.seats_in_use == 1, "The seat is still theirs."
    event = AuditEvent.all_objects.get(verb="portal.role_changed", target_id=fcc.pk)
    assert event.actor == ff.user
    assert event.payload["from"] == "FCC" and event.payload["to"] == "ECC"
    assert event.payload["narrowed"] is True


@pytest.mark.django_db
def test_9_2a_widening_ends_nothing(seeded_tenant, ff, api, company, ecc, in_tenant_a):
    from apps.accounts.models import MagicLinkToken

    _, raw = MagicLinkToken.issue(tenant=seeded_tenant, user=ecc.user)
    theirs = Client()
    theirs.force_login(ecc.user)

    body = role_change(api.as_(ff), ecc, "FCC").json()
    assert body["role"] == "FCC" and body["sessions_ended"] == 0
    assert body["links_invalidated"] == 0
    # Takes effect on their very next request, in the session they already have.
    assert theirs.get("/api/me").json()["role"] == "FCC"
    assert MagicLinkToken.all_objects.filter(user=ecc.user, used_at__isnull=True).exists()
    event = AuditEvent.all_objects.get(verb="portal.role_changed", target_id=ecc.pk)
    assert event.payload["narrowed"] is False
    assert raw  # issued, and untouched


@pytest.mark.django_db
def test_9_2a_the_same_role_again_changes_and_audits_nothing(ff, api, fcc, in_tenant_a):
    theirs = Client()
    theirs.force_login(fcc.user)
    body = role_change(api.as_(ff), fcc, "FCC").json()
    assert body["changed"] is False and body["sessions_ended"] == 0
    assert theirs.get("/api/me").status_code == 200
    assert not AuditEvent.all_objects.filter(verb="portal.role_changed").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "", None])
def test_9_2a_a_role_change_never_makes_anything_but_a_client_user(role, ff, api, fcc,
                                                                  in_tenant_a):
    refused = role_change(api.as_(ff), fcc, role)
    assert refused.status_code == 400
    fcc.refresh_from_db()
    assert fcc.role == "FCC"


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_9_2a_who_may_change_a_portal_role(role, expected, seeded_tenant, api, company,
                                           ecc, in_tenant_a):
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    assert role_change(api.as_(member), ecc, "FCC").status_code == expected
    ecc.refresh_from_db()
    assert ecc.role == ("FCC" if expected == 200 else "ECC")


@pytest.mark.django_db
def test_9_2a_a_role_change_is_blind_to_other_companies_tenants_and_staff(
    seeded_tenant, tenant_b, ff, cf, api, ecc, in_tenant_a
):
    # A CF on a company they are not assigned: 404, not 403 (matrix §1).
    assert role_change(api.as_(cf), ecc, "FCC").status_code == 404

    # Another tenant's portal user is invisible to this FF.
    theirs_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=2)
    theirs = MembershipFactory(tenant=tenant_b, role="ECC", client_company=theirs_co)
    assert role_change(api.as_(ff), theirs, "FCC").status_code == 404
    theirs.refresh_from_db()
    assert theirs.role == "ECC"

    # Staff roles are not portal access (FR-0.8b).
    assert role_change(api.as_(ff), cf, "FCC").status_code == 404

    # Nor is someone whose access has been revoked.
    api.as_(ff).delete(f"/api/portal-access/{ecc.pk}/")
    assert role_change(api.as_(ff), ecc, "FCC").status_code == 404


# ================================= matrix 4.8 / FR-1.3a: the company's primary contact

def set_primary(client, company, contact):
    return patch(client, f"/api/companies/{company.pk}/",
                 {"primary_contact": str(contact.pk) if contact else None})


@pytest.mark.django_db
def test_4_8_the_primary_contact_sets_the_fcc_default_and_changes_no_existing_role(
    seeded_tenant, ff, api, company, fcc, ecc, in_tenant_a
):
    newcomer = a_contact(seeded_tenant, company, "Ola", "ola@northwind.invalid")
    assert set_primary(api.as_(ff), company, newcomer).status_code == 200

    candidates = api.as_(ff).get(
        f"/api/portal-access/candidates/?contact={newcomer.pk}").json()
    assert candidates["people"][0]["role"] == "FCC", "FR-3.33d is now exercisable."

    # Moving it onto the ECC, and away from the FCC, changes neither login.
    assert set_primary(api.as_(ff), company, ecc.contact).status_code == 200
    for member, role in ((fcc, "FCC"), (ecc, "ECC")):
        member.refresh_from_db()
        assert member.role == role, "Setting a primary contact changed a portal role."
    assert not AuditEvent.all_objects.filter(verb="portal.role_changed").exists()

    assert set_primary(api.as_(ff), company, None).status_code == 200
    company.refresh_from_db()
    assert company.primary_contact_id is None


@pytest.mark.django_db
def test_4_8_every_primary_contact_change_is_audited_with_who_old_and_new(
    seeded_tenant, ff, cf, va, api, company, in_tenant_a
):
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    dana = a_contact(seeded_tenant, company, "Dana")
    priya = a_contact(seeded_tenant, company, "Priya", "priya@northwind.invalid")

    def events():
        return list(AuditEvent.all_objects.filter(
            verb="company.primary_contact_changed", target_id=company.pk
        ).order_by("created_at"))

    assert set_primary(api.as_(ff), company, dana).status_code == 200
    assert set_primary(api.as_(cf), company, priya).status_code == 200
    assert set_primary(api.as_(ff), company, None).status_code == 200

    trail = [(e.actor, e.payload["from"], e.payload["to"]) for e in events()]
    assert trail == [
        (ff.user, None, {"id": str(dana.pk), "name": "Dana Okafor"}),
        (cf.user, {"id": str(dana.pk), "name": "Dana Okafor"},
         {"id": str(priya.pk), "name": "Priya Okafor"}),
        (ff.user, {"id": str(priya.pk), "name": "Priya Okafor"}, None),
    ]

    # Nothing changed, nothing recorded: an ordinary edit, resending the same
    # value, and a refused attempt.
    company.primary_contact = dana
    company.save()
    before = len(events())
    patch(api.as_(ff), f"/api/companies/{company.pk}/", {"industry": "Food"})
    set_primary(api.as_(ff), company, dana)
    assert set_primary(api.as_(va), company, priya).status_code == 403
    assert len(events()) == before


@pytest.mark.django_db
def test_4_8_the_primary_contact_must_be_one_of_this_companys_own_contacts(
    seeded_tenant, tenant_b, ff, api, company, in_tenant_a
):
    from apps.crm.models import Company

    elsewhere = ClientCompanyFactory(tenant=seeded_tenant, name="Other Co", seat_count=1)
    outsider = a_contact(seeded_tenant, elsewhere, "Outsider", "outsider@other.invalid")
    no_company = ContactFactory(tenant=seeded_tenant, first_name="Loose", company=None)
    gone = a_contact(seeded_tenant, company, "Gone", "gone@northwind.invalid")
    gone.deleted_at = timezone.now()
    gone.save()
    foreign_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    foreign = ContactFactory(tenant=tenant_b, first_name="Foreign", company=foreign_co)

    for contact in (outsider, no_company, gone, foreign):
        refused = set_primary(api.as_(ff), company, contact)
        assert refused.status_code == 400, (contact.first_name, refused.content)
    assert Company.objects.get(pk=company.pk).primary_contact_id is None

    # Nor on the way in: a new company has no contacts of its own yet.
    created = post(api.as_(ff), "/api/companies/",
                   {"name": "Brand New Co", "primary_contact": str(outsider.pk)})
    assert created.status_code == 400
    assert not Company.objects.filter(name="Brand New Co").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_4_8_who_may_set_the_primary_contact(role, expected, seeded_tenant, api, company,
                                             in_tenant_a):
    contact = a_contact(seeded_tenant, company, "Dana")
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    assert set_primary(api.as_(member), company, contact).status_code == expected
    company.refresh_from_db()
    assert company.primary_contact_id == (contact.pk if expected == 200 else None)


@pytest.mark.django_db
def test_4_8_a_va_cannot_clear_it_but_can_still_save_the_rest_of_the_company(
    seeded_tenant, ff, va, api, company, in_tenant_a
):
    founder = a_contact(seeded_tenant, company, "Dana")
    company.primary_contact = founder
    company.save()

    assert set_primary(api.as_(va), company, None).status_code == 403
    # Resending the current value alongside an ordinary edit is not setting it.
    saved = patch(api.as_(va), f"/api/companies/{company.pk}/",
                  {"industry": "Food", "primary_contact": str(founder.pk)})
    assert saved.status_code == 200, saved.content
    company.refresh_from_db()
    assert company.primary_contact_id == founder.pk and company.industry == "Food"


@pytest.mark.django_db
def test_4_8_a_cf_cannot_set_it_on_a_company_they_are_not_assigned(
    seeded_tenant, cf, api, company, in_tenant_a
):
    contact = a_contact(seeded_tenant, company, "Dana")
    assert set_primary(api.as_(cf), company, contact).status_code == 404
    company.refresh_from_db()
    assert company.primary_contact_id is None
