"""Mandatory test family 2 — role boundaries (CLAUDE.md, assumption B3).

Source of truth is `03_access_matrix.md`. Every row there becomes a case here.
Phase 0.5 covers the matrix rows that exist in the foundation: §2 and §3, plus
the membership invariants every later module's rows depend on.
"""

from __future__ import annotations

import pytest
from django.db.utils import IntegrityError

from apps.tenancy.context import tenant_context
from apps.tenancy.models import CLIENT_ROLES, TENANT_ROLES, Membership, Role

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(TENANT_ROLES))
def test_tenant_roles_must_not_carry_a_client_company(role, tenant_a):
    """Matrix §2: a tenant user is scoped by tenant, never by company."""
    company = ClientCompanyFactory(tenant=tenant_a)
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, role=role, client_company=company)


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_client_roles_require_a_client_company(role, tenant_a):
    """FR-0.2: a client user without a company is an unbounded client user."""
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, role=role, client_company=None)


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_client_roles_bind_a_second_scope_layer(role, tenant_a):
    company = ClientCompanyFactory(tenant=tenant_a)
    membership = MembershipFactory(tenant=tenant_a, role=role, client_company=company)
    assert membership.is_client_user
    assert membership.client_company_id == company.pk


@pytest.mark.django_db
def test_one_membership_per_user_per_tenant(tenant_a):
    """Assumption B4 — enforced now, modelled as a table for V1."""
    user = UserFactory()
    MembershipFactory(tenant=tenant_a, user=user, role=Role.FF)
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, user=user, role=Role.VA)


@pytest.mark.django_db
def test_seats_are_counted_not_stored(tenant_a):
    """Data model §12.3 — a counter would drift; a count cannot."""
    company = ClientCompanyFactory(tenant=tenant_a, seat_count=2)
    assert company.seats_in_use == 0
    assert company.seats_available == 2

    MembershipFactory(tenant=tenant_a, role=Role.FCC, client_company=company)
    assert company.seats_in_use == 1

    revoked = MembershipFactory(tenant=tenant_a, role=Role.ECC, client_company=company)
    assert company.seats_in_use == 2
    assert company.seats_available == 0

    from django.utils import timezone
    revoked.revoked_at = timezone.now()
    revoked.save()
    # FR-3.33g: revoking frees the seat immediately, with no reconciliation step.
    assert company.seats_in_use == 1
    assert company.seats_available == 1


@pytest.mark.django_db
def test_only_one_anthropic_key_per_tenant(tenant_a):
    """Data model review item 5 — the NULL-distinct trap.

    U(tenant, kind, user) does not constrain rows where user IS NULL, because
    Postgres treats NULLs as distinct. The partial index does.
    """
    from .factories import TenantSecretFactory

    TenantSecretFactory(tenant=tenant_a, kind="anthropic_api_key", user=None)
    with pytest.raises(IntegrityError):
        TenantSecretFactory(tenant=tenant_a, kind="anthropic_api_key", user=None)


@pytest.mark.django_db
def test_tenant_secret_ciphertext_is_never_serialised(tenant_a):
    """E1.3 — write-only across the entire API, for every role including FF."""
    from apps.tenancy.models import TenantSecret

    with tenant_context(tenant_a.pk):
        from .factories import TenantSecretFactory

        secret = TenantSecretFactory(tenant=tenant_a)
        assert "ciphertext" not in str(secret)
        assert secret.last4 in str(secret)
        # Nothing in the codebase may expose the field; enforced by review plus
        # this assertion once a serializer exists in Phase 1.
        assert TenantSecret._meta.get_field("ciphertext") is not None


# =========================================================== Module 1 (§4, §5)
# Matrix rows 3.12-3.19, 4.1-4.18, 5.1-5.9. Every denied-send case also asserts
# the dev outbox is empty and no OutboxMessage reached `sent` (matrix §14.3).

MODULE1_ENDPOINTS = [
    ("/api/contacts/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/companies/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/outbox/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/imports/", {"FF": 200, "CF": 403, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/pipeline-stages/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/contact-types/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/service-categories/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/stage-automations/", {"FF": 200, "CF": 403, "VA": 403, "FCC": 403, "ECC": 403}),
    ("/api/tasks/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,expected", MODULE1_ENDPOINTS, ids=[u for u, _ in MODULE1_ENDPOINTS])
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC", "ECC"])
def test_module1_endpoint_role_matrix(url, expected, role, seeded_tenant, api):
    """Every Module 1 endpoint x every role, straight from `03_access_matrix.md`."""
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    membership = MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
    response = api.as_(membership).get(url)
    assert response.status_code == expected[role], (
        f"{url} as {role}: expected {expected[role]}, got {response.status_code}"
    )


@pytest.mark.django_db
def test_va_denied_send_leaves_the_outbox_untouched(seeded_tenant, va, api, dev_outbox):
    """Matrix §14.3 — a 403 alone is not a sufficient assertion."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox as outbox_service
    from apps.tenancy.context import tenant_context

    from .factories import ContactEmailFactory, ContactFactory

    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact)
        message = outbox_service.create_message(
            tenant=seeded_tenant, producer="referral_touch", to_contact=contact,
            to_address=contact.primary_email, subject="s", body_text="b",
        )

    assert api.as_(va).post(f"/api/outbox/{message.pk}/approve/").status_code == 403

    message.refresh_from_db()
    assert message.state != OutboxMessage.State.SENT
    assert message.sent_at is None
    assert dev_outbox == [], "A denied send still delivered mail."


@pytest.mark.django_db
def test_cf_cannot_approve_for_an_unassigned_company(seeded_tenant, ff, cf, api, dev_outbox):
    """Matrix 8.6 / 5.3 — CF approval is bounded by assignment."""
    from apps.crm.services import outbox as outbox_service
    from apps.tenancy.context import tenant_context

    from .factories import ClientCompanyFactory, ContactEmailFactory, ContactFactory

    unassigned = ClientCompanyFactory(tenant=seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant, company=unassigned)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact)
        message = outbox_service.create_message(
            tenant=seeded_tenant, producer="referral_touch", to_contact=contact,
            to_address=contact.primary_email, subject="s", body_text="b",
        )

    # 404, not 403: a 403 would confirm the row exists (matrix §1 rule 1).
    assert api.as_(cf).post(f"/api/outbox/{message.pk}/approve/").status_code == 404
    message.refresh_from_db()
    assert message.state != "sent"
    assert dev_outbox == []
