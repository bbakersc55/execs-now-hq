"""Assumption C1 — Google sign-in is invite-only, and refusal is real.

The refused case is tested at the adapter, because that is where the decision
is made and where a regression would land. A live Google round trip proves the
transport; these prove the rule.
"""

from __future__ import annotations

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialLogin
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from apps.accounts.adapters import InviteOnlySocialAdapter, NoSignupAccountAdapter
from apps.accounts.models import User

from . import registry_config  # noqa: F401
from .factories import MembershipFactory


def _request():
    request = RequestFactory().get("/accounts/google/login/callback/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    return request


def _social_login(email):
    return SocialLogin(user=User(email=email))


@pytest.mark.django_db
def test_uninvited_account_is_refused(tenant_a):
    """No Membership -> ImmediateHttpResponse, not a signup form."""
    adapter = InviteOnlySocialAdapter()
    with pytest.raises(ImmediateHttpResponse) as exc:
        adapter.pre_social_login(_request(), _social_login("stranger@example.invalid"))
    assert exc.value.response.status_code == 302
    assert exc.value.response["Location"] == "/accounts/refused"


@pytest.mark.django_db
def test_uninvited_account_creates_nothing(tenant_a):
    """The refusal happens before any User or SocialAccount row exists."""
    adapter = InviteOnlySocialAdapter()
    before = User.objects.count()
    with pytest.raises(ImmediateHttpResponse):
        adapter.pre_social_login(_request(), _social_login("stranger@example.invalid"))
    assert User.objects.count() == before
    assert not User.objects.filter(email="stranger@example.invalid").exists()


@pytest.mark.django_db
def test_invited_account_is_allowed(tenant_a):
    membership = MembershipFactory(tenant=tenant_a)
    adapter = InviteOnlySocialAdapter()
    # Returns without raising.
    adapter.pre_social_login(_request(), _social_login(membership.user.email))


@pytest.mark.django_db
def test_invited_account_match_is_case_insensitive(tenant_a):
    membership = MembershipFactory(tenant=tenant_a)
    adapter = InviteOnlySocialAdapter()
    adapter.pre_social_login(_request(), _social_login(membership.user.email.upper()))


@pytest.mark.django_db
def test_revoked_member_is_refused(tenant_a):
    """FR-0.8c — removal must actually cut off sign-in, not just sessions."""
    from django.utils import timezone

    membership = MembershipFactory(tenant=tenant_a)
    membership.revoked_at = timezone.now()
    membership.save()

    adapter = InviteOnlySocialAdapter()
    with pytest.raises(ImmediateHttpResponse):
        adapter.pre_social_login(_request(), _social_login(membership.user.email))


@pytest.mark.django_db
def test_no_self_serve_signup_by_any_route():
    """CLAUDE.md: no self-serve signup in Beta."""
    assert NoSignupAccountAdapter().is_open_for_signup(_request()) is False
    assert InviteOnlySocialAdapter().is_open_for_signup(_request(), None) is False


@pytest.mark.django_db
def test_refused_page_returns_403(client):
    response = client.get("/accounts/refused")
    assert response.status_code == 403
    assert b"invite-only" in response.content
