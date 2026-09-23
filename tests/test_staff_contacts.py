"""A staff login attaches to a contact row (assumption F1, FR-0.8a).

**Client users have always arrived that way round** — portal access is granted
*on* a contact, so the membership carries one from the moment it exists. A
staff invite starts from an email address instead, and nothing closed the gap:
the owner's own membership had no contact, so meeting ingestion's practice rule
(FR-5.9e) had to find him by matching an address and then a name against a CRM
that held two rows with his name on them.

These pin the link, and pin what it must not do: it never overwrites a
membership that already points somewhere, and it never modifies a contact it
did not create.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.crm.models import Contact, ContactEmail
from apps.meetings import practice
from apps.tenancy import services
from apps.tenancy.models import AuditEvent, Membership

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, MembershipFactory


@pytest.mark.django_db
def test_an_invite_links_the_contact_that_already_holds_the_address(
    seeded_tenant, ff, api, in_tenant_a
):
    """**Email first.** The practice's own people are usually in the CRM
    already — often as something else entirely."""
    existing = ContactFactory(tenant=seeded_tenant, first_name="Casey",
                              last_name="Fields")
    ContactEmailFactory(tenant=seeded_tenant, contact=existing,
                        address="casey@getexecutivesnow.test")

    response = api.as_(ff).post("/api/staff/", {
        "email": "Casey@GetExecutivesNow.test", "role": "CF",
        "full_name": "Casey Fields"})

    assert response.status_code == 201, response.json()
    membership = Membership.objects.get(pk=response.json()["id"])
    assert membership.contact_id == existing.pk
    # Linked, not retyped: it was somebody before it was staff.
    assert list(existing.types.all()) == []
    assert Contact.objects.filter(first_name="Casey").count() == 1


@pytest.mark.django_db
def test_an_invite_links_by_name_when_there_is_no_address_to_go_on(
    seeded_tenant, ff, api, in_tenant_a
):
    """Then name — the same order as every other match in this product."""
    existing = ContactFactory(tenant=seeded_tenant, first_name="Dana",
                              last_name="Okafor")

    response = api.as_(ff).post("/api/staff/", {
        "email": "dana@getexecutivesnow.test", "role": "VA",
        "full_name": "Dana Okafor"})

    membership = Membership.objects.get(pk=response.json()["id"])
    assert membership.contact_id == existing.pk


@pytest.mark.django_db
def test_an_invite_creates_the_contact_when_there_is_none(
    seeded_tenant, ff, api, in_tenant_a
):
    """"Create **or** link": a new fractional is nobody in the CRM yet, and the
    row we make is the one their meetings will be recorded against."""
    response = api.as_(ff).post("/api/staff/", {
        "email": "new.hire@getexecutivesnow.test", "role": "CF",
        "full_name": "Ada Nwosu"})

    membership = Membership.objects.get(pk=response.json()["id"])
    contact = membership.contact
    assert contact is not None
    assert (contact.first_name, contact.last_name) == ("Ada", "Nwosu")
    assert contact.source == "staff invite"
    # The address comes with them, so the *next* lookup is unambiguous.
    assert ContactEmail.objects.filter(
        contact=contact, address="new.hire@getexecutivesnow.test").exists()
    # A row we made may be typed. One we merely found may not.
    assert [t.code for t in contact.types.all()] == ["coworker"]


@pytest.mark.django_db
def test_an_ambiguous_name_makes_a_new_row_rather_than_guessing(
    seeded_tenant, ff, api, in_tenant_a
):
    """Two contacts with the practice owner's name is a real thing in a real
    CRM. Picking either would attach a login to a stranger."""
    ContactFactory(tenant=seeded_tenant, first_name="Bryan", last_name="Baker")
    ContactFactory(tenant=seeded_tenant, first_name="Bryan", last_name="Baker")

    response = api.as_(ff).post("/api/staff/", {
        "email": "bryan@getexecutivesnow.test", "role": "CF",
        "full_name": "Bryan Baker"})

    membership = Membership.objects.get(pk=response.json()["id"])
    assert Contact.objects.filter(first_name="Bryan", last_name="Baker").count() == 3
    assert membership.contact.primary_email == "bryan@getexecutivesnow.test"


@pytest.mark.django_db
def test_a_membership_that_already_points_somewhere_is_left_alone(
    seeded_tenant, ff, in_tenant_a
):
    """Re-inviting somebody is not a reason to re-decide who they are."""
    chosen = ContactFactory(tenant=seeded_tenant, first_name="Casey",
                            last_name="Fields")
    other = ContactFactory(tenant=seeded_tenant, first_name="Casey",
                           last_name="Fields")
    ContactEmailFactory(tenant=seeded_tenant, contact=other,
                        address="casey@getexecutivesnow.test")
    membership = MembershipFactory(tenant=seeded_tenant, role="CF", contact=chosen)
    membership.user.email = "casey@getexecutivesnow.test"
    membership.user.save(update_fields=["email"])

    again = services.invite_member(tenant=seeded_tenant,
                                   email="casey@getexecutivesnow.test", role="CF")

    assert again.pk == membership.pk
    assert again.contact_id == chosen.pk


@pytest.mark.django_db
def test_the_invite_records_which_contact_and_whether_it_was_made(
    seeded_tenant, ff, api, in_tenant_a
):
    api.as_(ff).post("/api/staff/", {"email": "ada@getexecutivesnow.test",
                                     "role": "CF", "full_name": "Ada Nwosu"})

    event = AuditEvent.all_objects.filter(verb="member.invited").latest("created_at")
    assert event.payload["contact_created"] is True
    assert event.payload["contact"]


@pytest.mark.django_db
def test_a_client_invite_is_still_refused_and_creates_nothing(
    seeded_tenant, ff, api, in_tenant_a
):
    """The refusal comes first: no contact is created on the way to it."""
    before = Contact.objects.count()

    response = api.as_(ff).post("/api/staff/", {
        "email": "founder@acme.invalid", "role": "FCC", "full_name": "Pat Lee"})

    assert response.status_code == 400
    assert Contact.objects.count() == before


@pytest.mark.django_db
def test_the_link_is_what_meeting_ingestion_now_uses(
    seeded_tenant, ff, api, in_tenant_a
):
    """The point of all this (FR-5.9e). With the membership linked, the
    practice rule resolves by the link rather than by guessing at names."""
    api.as_(ff).post("/api/staff/", {"email": "ada@getexecutivesnow.test",
                                     "role": "CF", "full_name": "Ada Nwosu"})
    # A decoy with the same name, which is what used to make this ambiguous.
    ContactFactory(tenant=seeded_tenant, first_name="Ada", last_name="Nwosu")

    found = practice.recognise(seeded_tenant, name="Ada Nwosu",
                               email="ada@getexecutivesnow.test")

    assert found is not None
    linked = Membership.objects.get(user__email="ada@getexecutivesnow.test")
    assert found.contact == linked.contact


# ----------------------------------------------------- the existing memberships


@pytest.mark.django_db
def test_the_backfill_command_writes_nothing_without_apply(
    seeded_tenant, in_tenant_a
):
    membership = MembershipFactory(tenant=seeded_tenant, role="FF", contact=None)
    membership.user.email = "owner@getexecutivesnow.test"
    membership.user.full_name = "Bryan Baker"
    membership.user.save(update_fields=["email", "full_name"])
    existing = ContactFactory(tenant=seeded_tenant, first_name="Bryan",
                              last_name="Baker")
    ContactEmailFactory(tenant=seeded_tenant, contact=existing,
                        address="owner@getexecutivesnow.test")
    before = Contact.objects.count()

    out = StringIO()
    call_command("link_staff_contacts", tenant=seeded_tenant.slug, stdout=out)

    assert "Dry run" in out.getvalue()
    assert "would link Bryan Baker" in out.getvalue()
    membership.refresh_from_db()
    assert membership.contact_id is None
    # A dry run that had to invent a contact to answer the question rolls that
    # back too.
    assert Contact.objects.count() == before

    call_command("link_staff_contacts", tenant=seeded_tenant.slug, apply=True,
                 stdout=StringIO())
    membership.refresh_from_db()
    assert membership.contact_id == existing.pk
    assert AuditEvent.all_objects.filter(verb="member.contact_linked").exists()


@pytest.mark.django_db
def test_the_backfill_leaves_client_memberships_and_linked_staff_alone(
    seeded_tenant, in_tenant_a
):
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant)
    client_contact = ContactFactory(tenant=seeded_tenant, company=company)
    client_member = MembershipFactory(tenant=seeded_tenant, role="FCC",
                                      client_company=company,
                                      contact=client_contact)
    linked = MembershipFactory(tenant=seeded_tenant, role="CF",
                               contact=ContactFactory(tenant=seeded_tenant))
    was = linked.contact_id

    call_command("link_staff_contacts", tenant=seeded_tenant.slug, apply=True,
                 stdout=StringIO())

    linked.refresh_from_db()
    client_member.refresh_from_db()
    assert linked.contact_id == was
    assert client_member.contact_id == client_contact.pk
