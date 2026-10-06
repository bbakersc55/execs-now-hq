"""Marking a company as a client by hand, and undoing it (beta feedback,
2026-10-05, item D; apps/crm/services/clients.py).

The two things that must hold: it sets the company flag and **nothing else**
(above all, no stage automation fires), and the undo is refused while anything
has been built on the mark."""

from __future__ import annotations

import json

import pytest

from apps.crm.models import (
    Company, ContactPipelinePosition, ContactTypeLink, OutboxMessage, StageChange, Task,
)
from apps.crm.services import pipeline
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, CompanyFactory, ContactFactory,
    MembershipFactory, StageAutomationFactory, TaskFactory,
)


def url(company, action):
    return f"/api/companies/{company.pk}/{action}/"


def post(client, company, action):
    return client.post(url(company, action), "{}", content_type="application/json")


@pytest.fixture
def referred(seeded_tenant):
    """A company with a contact who never went near the pipeline."""
    company = CompanyFactory(tenant=seeded_tenant, name="Referred Co", is_client_company=False)
    contact = ContactFactory(tenant=seeded_tenant, company=company, first_name="Rae",
                             last_name="Ferral")
    return company, contact


# ---------------------------------------------------------------- who may

@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 403), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
@pytest.mark.parametrize("action", ["mark-client", "unmark-client"])
def test_only_the_practice_owner_marks_or_unmarks(role, expected, action, seeded_tenant, api):
    company = CompanyFactory(tenant=seeded_tenant, is_client_company=(action == "unmark-client"))
    theirs = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = MembershipFactory(tenant=seeded_tenant, role=role, client_company=theirs)
    if role == "CF":
        # Even assigned to it, an associate does not decide who is a client.
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    before = company.is_client_company

    response = post(api.as_(member), company, action)

    company.refresh_from_db()
    if role == "CF" and action == "unmark-client":
        assert response.status_code == 403 and company.is_client_company == before
        return
    assert response.status_code == expected
    assert (company.is_client_company != before) == (expected == 200)


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("VA", 200), ("FCC", 403), ("ECC", 403)])
def test_who_reads_a_companys_client_status(role, expected, seeded_tenant, api):
    company = CompanyFactory(tenant=seeded_tenant)
    theirs = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = MembershipFactory(tenant=seeded_tenant, role=role, client_company=theirs)
    assert api.as_(member).get(url(company, "client-status")).status_code == expected


@pytest.mark.django_db
def test_the_signed_out_do_nothing(client, seeded_tenant):
    company = CompanyFactory(tenant=seeded_tenant)
    assert post(client, company, "mark-client").status_code in (401, 403)
    assert client.get(url(company, "client-status")).status_code in (401, 403)
    company.refresh_from_db()
    assert company.is_client_company is False


@pytest.mark.django_db
def test_another_practices_company_is_not_found(tenant_a, tenant_b, api):
    a_owner = MembershipFactory(tenant=tenant_a, role="FF")
    theirs = CompanyFactory(tenant=tenant_b, is_client_company=False)
    marked = CompanyFactory(tenant=tenant_b, is_client_company=True)
    client = api.as_(a_owner)

    assert post(client, theirs, "mark-client").status_code == 404
    assert post(client, marked, "unmark-client").status_code == 404
    assert client.get(url(theirs, "client-status")).status_code == 404
    theirs.refresh_from_db()
    marked.refresh_from_db()
    assert (theirs.is_client_company, marked.is_client_company) == (False, True)


# ------------------------------------------------------------ what it sets

@pytest.mark.django_db
def test_marking_sets_the_company_flag_and_nothing_else(
    seeded_tenant, ff, api, referred, sales, stages, dev_outbox
):
    """Compared with Closed Won: no stage change, no automation, no contact
    type. A rule on the won stage is armed here to prove it stays quiet."""
    company, contact = referred
    StageAutomationFactory(tenant=seeded_tenant, pipeline=sales, to_stage=stages["closed_won"],
                           action_type="create_task", task_title_template="Onboard {FirstName}")
    tasks_before = Task.all_objects.filter(tenant=seeded_tenant).count()

    body = post(api.as_(ff), company, "mark-client").json()

    assert body == {"id": str(company.pk), "is_client_company": True, "undo_blockers": []}
    company.refresh_from_db()
    assert company.is_client_company is True
    # Nothing a stage change would have done:
    assert Task.all_objects.filter(tenant=seeded_tenant).count() == tasks_before
    assert not OutboxMessage.all_objects.filter(tenant=seeded_tenant).exists()
    assert not StageChange.all_objects.filter(contact=contact).exists()
    assert not ContactPipelinePosition.all_objects.filter(contact=contact).exists()
    assert not ContactTypeLink.all_objects.filter(
        contact=contact, contact_type__code="client").exists()
    assert dev_outbox == []


@pytest.mark.django_db
def test_marking_is_recorded_with_who_and_why(seeded_tenant, ff, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    post(api.as_(ff), company, "mark-client")      # again: nothing more to record

    events = AuditEvent.all_objects.filter(tenant=seeded_tenant, verb="company.flagged",
                                           target_id=company.pk)
    assert events.count() == 1
    assert events[0].actor_id == ff.user.pk
    assert events[0].payload == {"is_client_company": True,
                                 "because": "marked by the practice owner"}


@pytest.mark.django_db
def test_a_marked_company_is_offered_wherever_clients_are(seeded_tenant, ff, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    listed = {c["id"]: c for c in api.as_(ff).get("/api/companies/").json()}
    assert listed[str(company.pk)]["is_client_company"] is True


# ------------------------------------------------------------------- undo

@pytest.mark.django_db
def test_a_company_marked_by_mistake_can_be_unmarked_and_it_is_recorded(
    seeded_tenant, ff, api, referred
):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")

    body = post(api.as_(ff), company, "unmark-client").json()

    assert body["is_client_company"] is False
    company.refresh_from_db()
    assert company.is_client_company is False
    event = AuditEvent.all_objects.get(tenant=seeded_tenant, verb="company.unflagged")
    assert event.actor_id == ff.user.pk and event.target_id == company.pk


def _refused(api, ff, company, fragment):
    response = post(api.as_(ff), company, "unmark-client")
    assert response.status_code == 409, response.content
    body = response.json()
    assert any(fragment in line for line in body["undo_blockers"]), body
    company.refresh_from_db()
    assert company.is_client_company is True
    assert not AuditEvent.all_objects.filter(verb="company.unflagged").exists()
    # The page is told the same thing before anyone presses the button.
    assert api.as_(ff).get(url(company, "client-status")).json()["undo_blockers"] \
        == body["undo_blockers"]


@pytest.mark.django_db
def test_undo_is_refused_once_a_contact_has_reached_closed_won(
    seeded_tenant, ff, api, referred, stages
):
    """Then it is a client by the pipeline's rule, not by a mistaken click."""
    company, contact = referred
    with tenant_context(seeded_tenant.pk):
        pipeline.change_stage(contact, stages["closed_won"], actor=ff.user)
    _refused(api, ff, company, "Rae Ferral reached Closed Won")


@pytest.mark.django_db
def test_undo_is_refused_while_someone_has_portal_access(seeded_tenant, ff, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    _refused(api, ff, company, "1 person has portal access")


@pytest.mark.django_db
def test_undo_is_refused_while_work_is_filed_under_it(seeded_tenant, ff, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    TaskFactory(tenant=seeded_tenant, client_company=company)
    _refused(api, ff, company, "1 task filed under it")


@pytest.mark.django_db
def test_undo_is_refused_while_an_associate_is_assigned(seeded_tenant, ff, cf, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    _refused(api, ff, company, "1 associate is assigned")


@pytest.mark.django_db
def test_undo_deletes_nothing_to_make_itself_possible(seeded_tenant, ff, api, referred):
    company, _ = referred
    post(api.as_(ff), company, "mark-client")
    task = TaskFactory(tenant=seeded_tenant, client_company=company)

    post(api.as_(ff), company, "unmark-client")

    task.refresh_from_db()
    assert task.client_company_id == company.pk and task.deleted_at is None
    assert Company.all_objects.filter(pk=company.pk, deleted_at__isnull=True).exists()


@pytest.mark.django_db
def test_closed_won_still_does_everything_it_did(seeded_tenant, ff, referred, stages):
    """The pipeline's own route is untouched by the new one."""
    company, contact = referred
    with tenant_context(seeded_tenant.pk):
        pipeline.change_stage(contact, stages["closed_won"], actor=ff.user)
    company.refresh_from_db()
    assert company.is_client_company is True
    assert ContactTypeLink.all_objects.filter(
        contact=contact, contact_type__code="client").exists()
    event = AuditEvent.all_objects.get(tenant=seeded_tenant, verb="company.flagged")
    assert "won" in event.payload["because"]
