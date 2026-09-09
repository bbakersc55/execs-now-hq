"""Assumption C3 — the magic-link guarantees, one test per clause."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.accounts.models import MAGIC_LINK_TTL, MagicLinkToken

from . import registry_config  # noqa: F401
from .factories import MembershipFactory


@pytest.fixture
def client_membership(tenant_a):
    from apps.tenancy.models import Role

    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=tenant_a)
    return MembershipFactory(
        tenant=tenant_a, role=Role.FCC, client_company=company
    )


@pytest.mark.django_db
def test_raw_token_is_never_stored(tenant_a, client_membership):
    """C3.1 — a database read must never yield a working credential."""
    token, raw = MagicLinkToken.issue(
        tenant=tenant_a, user=client_membership.user
    )
    assert token.token_hash != raw
    assert len(token.token_hash) == 64
    assert raw not in token.token_hash


@pytest.mark.django_db
def test_token_is_single_use(tenant_a, client_membership):
    """C3.2."""
    _, raw = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    record = MagicLinkToken.resolve(raw)
    assert record is not None
    record.consume()
    assert MagicLinkToken.resolve(raw) is None


@pytest.mark.django_db
def test_issuing_invalidates_outstanding_tokens(tenant_a, client_membership):
    """C3.2 — consuming or reissuing invalidates every other outstanding token."""
    _, first = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    _, second = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    assert MagicLinkToken.resolve(first) is None
    assert MagicLinkToken.resolve(second) is not None


@pytest.mark.django_db
def test_token_expires_after_twenty_minutes(tenant_a, client_membership):
    """C3.2."""
    token, raw = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    assert MAGIC_LINK_TTL.total_seconds() == 20 * 60
    token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    token.save()
    assert MagicLinkToken.resolve(raw) is None


@pytest.mark.django_db
def test_get_does_not_consume_the_token(client, tenant_a, client_membership):
    """C3.3 — mail scanners follow GET links and would burn the token."""
    _, raw = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    response = client.get(f"/auth/magic/{raw}")
    assert response.status_code == 200
    assert MagicLinkToken.resolve(raw) is not None, (
        "A GET consumed the token. Mail scanners and link-preview bots would "
        "sign the user out before they ever clicked."
    )


@pytest.mark.django_db
def test_request_response_is_identical_for_unknown_addresses(client, tenant_a):
    """C3.4 — the endpoint must not enumerate client users."""
    known = MembershipFactory(tenant=tenant_a)
    hit = client.post("/auth/magic/request", {"email": known.user.email})
    miss = client.post("/auth/magic/request", {"email": "nobody@example.invalid"})
    assert hit.status_code == miss.status_code == 200
    assert hit.json() == miss.json()


@pytest.mark.django_db
def test_post_completes_login_end_to_end(client, tenant_a, client_membership):
    """The POST half of C3.3, which nothing previously exercised.

    `User.membership` runs here BEFORE any tenant is bound — it is what
    determines the tenant — so a fail-closed reverse manager raised. Found by
    the Phase 1 property audit.
    """
    _, raw = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)

    landing = client.get(f"/auth/magic/{raw}")
    assert landing.status_code == 200

    response = client.post(f"/auth/magic/{raw}")
    assert response.status_code == 200, response.content[:300]
    assert response.json()["ok"] is True

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["role"] == "FCC"
    assert me.json()["client_company"] is not None


@pytest.mark.django_db
def test_client_session_is_thirty_days(client, tenant_a, client_membership, settings):
    """C3.5 — client users get a 30-day rolling session."""
    _, raw = MagicLinkToken.issue(tenant=tenant_a, user=client_membership.user)
    client.post(f"/auth/magic/{raw}")
    assert client.session.get_expiry_age() > 60 * 60 * 24 * 29
