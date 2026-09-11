"""Adding a contact or a company by hand (FR-1.1, FR-1.2, FR-1.3).

Check 2 found there was no way to do it at all: every contact in the system had
arrived through the CSV importer.
"""

from __future__ import annotations

import pytest

from apps.crm.models import Company, CompanyDomain, Contact, OutboxMessage
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, ContactFactory

CONTACTS = "/api/contacts/"
COMPANIES = "/api/companies/"


def _contact_body(**overrides):
    return dict({
        "first_name": "Dana", "last_name": "Reyes", "title": "COO",
        "source": "Referral", "background": "Met at the roundtable",
        "tags": ["vip", "warm"],
        "emails": [
            {"address": "dana@acme.invalid", "is_primary": True},
            {"address": "d.reyes@personal.invalid", "is_primary": False},
        ],
        "phones": [{"number": "555-0100", "is_primary": True}],
        "types": ["prospect"],
    }, **overrides)


# ------------------------------------------------------------------ contact

@pytest.mark.django_db
def test_creating_a_contact_writes_every_part_in_one_request(
    seeded_tenant, sales, stages, ff, api
):
    body = _contact_body(
        company_name="Acme Holdings",
        placement={"pipeline": "Sales", "stage": "qualified"},
    )
    response = api.as_(ff).post(CONTACTS, body, content_type="application/json")

    assert response.status_code == 201, response.content
    with tenant_context(seeded_tenant.pk):
        contact = Contact.objects.get(first_name="Dana")
        assert contact.title == "COO"
        assert contact.tags == ["vip", "warm"]
        assert contact.background == "Met at the roundtable"
        assert {e.address: e.is_primary for e in contact.emails.all()} == {
            "dana@acme.invalid": True, "d.reyes@personal.invalid": False,
        }
        assert {p.number: p.is_primary for p in contact.phones.all()} == {"555-0100": True}
        assert [t.code for t in contact.types.all()] == ["prospect"]
        assert contact.company.name == "Acme Holdings"
        assert contact.pipeline_positions.get().stage.code == "qualified"


@pytest.mark.django_db
def test_owner_defaults_to_whoever_is_adding_the_contact(seeded_tenant, cf, api):
    """FR-1.1 — and it is what drives a CF's own visibility (FR-1.9c)."""
    response = api.as_(cf).post(CONTACTS, _contact_body(), content_type="application/json")

    assert response.status_code == 201
    with tenant_context(seeded_tenant.pk):
        assert Contact.objects.get(first_name="Dana").owner_id == cf.user_id


@pytest.mark.django_db
def test_an_explicit_owner_still_wins(seeded_tenant, ff, cf, api):
    response = api.as_(ff).post(
        CONTACTS, _contact_body(owner=str(cf.user_id)), content_type="application/json",
    )
    assert response.status_code == 201
    with tenant_context(seeded_tenant.pk):
        assert Contact.objects.get(first_name="Dana").owner_id == cf.user_id


@pytest.mark.django_db
def test_the_first_email_is_primary_when_none_is_marked(seeded_tenant, ff, api):
    body = _contact_body(emails=[
        {"address": "first@x.invalid"}, {"address": "second@x.invalid"},
    ])
    api.as_(ff).post(CONTACTS, body, content_type="application/json")

    with tenant_context(seeded_tenant.pk):
        contact = Contact.objects.get(first_name="Dana")
        assert {e.address: e.is_primary for e in contact.emails.all()} == {
            "first@x.invalid": True, "second@x.invalid": False,
        }


@pytest.mark.django_db
def test_two_primary_emails_are_refused(seeded_tenant, ff, api):
    """The partial unique index would refuse it anyway; saying so in the form is
    better than a 500."""
    body = _contact_body(emails=[
        {"address": "a@x.invalid", "is_primary": True},
        {"address": "b@x.invalid", "is_primary": True},
    ])
    response = api.as_(ff).post(CONTACTS, body, content_type="application/json")

    assert response.status_code == 400
    assert "primary" in str(response.json()).lower()


@pytest.mark.django_db
def test_a_contact_needs_a_name(seeded_tenant, ff, api):
    response = api.as_(ff).post(
        CONTACTS, _contact_body(first_name="", last_name=""),
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_an_inline_company_matches_an_existing_one_case_insensitively(
    seeded_tenant, ff, api
):
    """Typing "acme" for the second person at Acme must not create a second
    company — that is the duplicate the merge screen exists to clean up."""
    existing = CompanyFactory(tenant=seeded_tenant, name="Acme Holdings")

    api.as_(ff).post(CONTACTS, _contact_body(company_name="  acme holdings "),
                     content_type="application/json")

    with tenant_context(seeded_tenant.pk):
        assert Company.objects.filter(name__iexact="acme holdings").count() == 1
        assert Contact.objects.get(first_name="Dana").company_id == existing.pk


@pytest.mark.django_db
def test_picking_an_existing_company_wins_over_a_typed_name(seeded_tenant, ff, api):
    chosen = CompanyFactory(tenant=seeded_tenant, name="Chosen Co")
    api.as_(ff).post(
        CONTACTS, _contact_body(company=str(chosen.pk), company_name="Typed Co"),
        content_type="application/json",
    )
    with tenant_context(seeded_tenant.pk):
        assert Contact.objects.get(first_name="Dana").company_id == chosen.pk
        assert not Company.objects.filter(name="Typed Co").exists()


@pytest.mark.django_db
def test_adding_a_referral_partner_by_hand_fires_onboarding(
    seeded_tenant, referrals, ff, api, dev_outbox
):
    """FR-1.23a — the same path the contact page uses, not a second one that
    quietly skips the first touch."""
    response = api.as_(ff).post(
        CONTACTS, _contact_body(types=["referral_partner"]),
        content_type="application/json",
    )
    assert response.status_code == 201

    with tenant_context(seeded_tenant.pk):
        contact = Contact.objects.get(first_name="Dana")
        assert contact.referral_onboarded_at is not None
        assert contact.pipeline_positions.get().stage.code == "new_partner"
        assert OutboxMessage.objects.filter(
            producer="referral_onboarding", state="pending_approval"
        ).count() == 1
    assert dev_outbox == [], "Adding a referral partner sent mail. It must only queue."


@pytest.mark.django_db
def test_an_unresolvable_placement_does_not_cost_you_the_contact(
    seeded_tenant, sales, ff, api
):
    response = api.as_(ff).post(
        CONTACTS, _contact_body(placement={"pipeline": "Sales", "stage": "nonsense"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    with tenant_context(seeded_tenant.pk):
        assert Contact.objects.get(first_name="Dana").pipeline_positions.count() == 0


# ------------------------------------------------------------------ company

@pytest.mark.django_db
def test_creating_a_company_with_domains(seeded_tenant, ff, api):
    response = api.as_(ff).post(COMPANIES, {
        "name": "Acme Holdings", "industry": "Manufacturing",
        "domains": ["Acme.invalid", "@acme.co", "acme.invalid"],
    }, content_type="application/json")

    assert response.status_code == 201, response.content
    assert response.json()["domains"] == ["acme.co", "acme.invalid"]
    with tenant_context(seeded_tenant.pk):
        company = Company.objects.get(name="Acme Holdings")
        assert CompanyDomain.objects.filter(company=company).count() == 2


@pytest.mark.django_db
def test_a_duplicate_company_name_is_refused(seeded_tenant, ff, api):
    CompanyFactory(tenant=seeded_tenant, name="Acme Holdings")
    response = api.as_(ff).post(
        COMPANIES, {"name": "  acme holdings "}, content_type="application/json",
    )
    assert response.status_code == 400
    assert "already exists" in str(response.json())


@pytest.mark.django_db
def test_is_client_company_cannot_be_set_by_hand(seeded_tenant, ff, api):
    """FR-1.6a — it is derived from a `won` stage in a sales pipeline, one way."""
    response = api.as_(ff).post(
        COMPANIES, {"name": "Acme", "is_client_company": True},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.json()["is_client_company"] is False


# -------------------------------------------------------------- permissions

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "VA"])
def test_ff_and_va_may_add_contacts_and_companies(role, seeded_tenant, api):
    """Matrix 4.3 — create is exactly as permitted as edit."""
    from .factories import MembershipFactory

    member = MembershipFactory(tenant=seeded_tenant, role=role)
    assert api.as_(member).post(
        CONTACTS, _contact_body(), content_type="application/json"
    ).status_code == 201
    assert api.as_(member).post(
        COMPANIES, {"name": f"Co {role}"}, content_type="application/json"
    ).status_code == 201


@pytest.mark.django_db
def test_a_cf_may_add_a_contact(seeded_tenant, cf, api):
    """Matrix 4.3 CF 🔸 — they may create; the owner default is what scopes it."""
    assert api.as_(cf).post(
        CONTACTS, _contact_body(), content_type="application/json"
    ).status_code == 201


@pytest.mark.django_db
def test_client_users_cannot_add_anything(seeded_tenant, fcc, api):
    assert api.as_(fcc).post(
        CONTACTS, _contact_body(), content_type="application/json"
    ).status_code == 403
    assert api.as_(fcc).post(
        COMPANIES, {"name": "Nope"}, content_type="application/json"
    ).status_code == 403


@pytest.mark.django_db
def test_a_va_cannot_set_a_seat_count_on_the_way_in(seeded_tenant, va, ff, api):
    """Matrix 4.12 — seat_count is FF-only, on create as well as on edit."""
    assert api.as_(va).post(
        COMPANIES, {"name": "Seated", "seat_count": 5}, content_type="application/json"
    ).status_code == 403
    assert api.as_(ff).post(
        COMPANIES, {"name": "Seated", "seat_count": 5}, content_type="application/json"
    ).status_code == 201


@pytest.mark.django_db
def test_a_contact_added_in_one_tenant_is_invisible_in_another(seeded_tenant, ff, api):
    from .factories import MembershipFactory, TenantFactory
    from apps.crm.seed import seed_tenant

    other = TenantFactory(name="Other practice", slug="other-add")
    seed_tenant(other)
    other_ff = MembershipFactory(tenant=other, role="FF")

    api.as_(ff).post(CONTACTS, _contact_body(), content_type="application/json")

    names = [c["first_name"] for c in api.as_(other_ff).get(CONTACTS).json()]
    assert "Dana" not in names
