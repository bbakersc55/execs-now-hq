"""Assumption C1 — Google sign-in is invite-only, tested on the LIVE PATH.

An earlier version of these tests called `pre_social_login` directly. That
proved the rule and missed the bug: the adapter returned cleanly for an invited
user, but allauth then routed them to a closed signup and both the invited and
the uninvited saw "Sign Up Closed". Calling the hook directly could never catch
that, because the defect was in what allauth does AFTER the hook returns.

So these tests go through the real `/accounts/google/login/callback/` view with
the real state check, the real `complete_social_login`, and the real
connect-or-signup decision. The only stubbed thing is Google's network: the
token exchange and the id_token decode. Everything downstream is the live path.
"""

from __future__ import annotations

import re
import urllib.parse
from unittest import mock

import pytest
from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter

from apps.accounts.models import User
from apps.accounts.views import login_refused

from . import registry_config  # noqa: F401
from .factories import MembershipFactory, UserFactory

CALLBACK = "/accounts/google/login/callback/"
LOGIN = "/accounts/google/login/"


def _google_claims(email, *, verified=True, sub="google-uid-12345"):
    """The shape Google actually returns in the id_token."""
    return {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "given_name": "Bryan",
        "family_name": "Baker",
        "name": "Bryan Baker",
    }


def _begin_login(client):
    """Drive the real login view so allauth stores state in the session."""
    page = client.get(LOGIN)
    token = re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', page.content)
    response = client.post(
        LOGIN, {"csrfmiddlewaretoken": token.group(1).decode()} if token else {}
    )
    location = response["Location"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert "accounts.google.com" in location
    return query["state"][0]


def _callback(client, claims):
    """Hit the real callback view with Google's network stubbed out."""
    state = _begin_login(client)
    with mock.patch.object(
        GoogleOAuth2Adapter,
        "get_access_token_data",
        return_value={"access_token": "stub-access-token", "id_token": "stub.jwt"},
    ), mock.patch.object(
        GoogleOAuth2Adapter, "_decode_id_token", return_value=claims
    ):
        return client.get(CALLBACK, {"code": "stub-auth-code", "state": state})


def _is_signed_in(client):
    return client.get("/api/me").status_code == 200


# --------------------------------------------------------------------------
# The two paths that failed in the browser.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_invited_user_signs_in(tenant_a, client):
    """THE REGRESSION. An invited user must reach a session, not a signup page.

    This is the case that rendered "Sign Up Closed" in the browser even though
    the User row and a live FF membership both existed.
    """
    membership = MembershipFactory(tenant=tenant_a)
    response = _callback(client, _google_claims(membership.user.email))

    assert response.status_code == 302, (
        f"Expected a redirect into the app, got {response.status_code}. "
        "A 200 here means allauth rendered a page — most likely signup."
    )
    assert b"Sign Up" not in response.content
    assert _is_signed_in(client), "Callback succeeded but no session was created."

    # The identity was connected to the EXISTING user, not a new one.
    assert User.objects.count() == 1
    assert SocialAccount.objects.filter(user=membership.user, provider="google").count() == 1


@pytest.mark.django_db
def test_uninvited_user_is_refused_with_our_403_not_signup_closed(tenant_a, client):
    """The other browser failure: refusal must come from us, not from allauth.

    Both paths previously rendered allauth's stock "Sign Up Closed", which is
    the wrong page, the wrong status, and the wrong reason.
    """
    response = _callback(client, _google_claims("stranger@example.invalid"))

    assert response.status_code == 302
    assert response["Location"] == "/accounts/refused"

    page = client.get(response["Location"])
    assert page.status_code == 403
    assert b"No access to this workspace" in page.content
    assert b"Sign Up Closed" not in page.content
    assert not _is_signed_in(client)


# --------------------------------------------------------------------------
# Nothing is created for anyone we turn away.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_refusal_creates_no_rows(tenant_a, client):
    before = (User.objects.count(), SocialAccount.objects.count(), SocialToken.objects.count())
    _callback(client, _google_claims("stranger@example.invalid"))
    after = (User.objects.count(), SocialAccount.objects.count(), SocialToken.objects.count())
    assert before == after, f"Refusal left rows behind: {before} -> {after}"


@pytest.mark.django_db
def test_unverified_email_is_never_trusted(tenant_a, client):
    """An unverified address must not inherit a Membership's access."""
    membership = MembershipFactory(tenant=tenant_a)
    response = _callback(
        client, _google_claims(membership.user.email, verified=False)
    )
    assert response["Location"] == "/accounts/refused"
    assert not _is_signed_in(client)
    assert SocialAccount.objects.count() == 0


@pytest.mark.django_db
def test_revoked_member_is_refused(tenant_a, client):
    """FR-0.8c — removal must cut off sign-in, not merely kill sessions."""
    from django.utils import timezone

    membership = MembershipFactory(tenant=tenant_a)
    membership.revoked_at = timezone.now()
    membership.save()

    response = _callback(client, _google_claims(membership.user.email))
    assert response["Location"] == "/accounts/refused"
    assert not _is_signed_in(client)


@pytest.mark.django_db
def test_revoked_member_with_existing_social_account_is_refused(tenant_a, client):
    """A previously-linked user who is later revoked must still be turned away.

    The SocialAccount row survives revocation, so `is_existing` is True and the
    connect branch is skipped — the membership check has to happen before it.
    """
    from django.utils import timezone

    membership = MembershipFactory(tenant=tenant_a)
    assert _callback(client, _google_claims(membership.user.email)).status_code == 302
    assert _is_signed_in(client)
    client.logout()

    membership.revoked_at = timezone.now()
    membership.save()

    response = _callback(client, _google_claims(membership.user.email))
    assert response["Location"] == "/accounts/refused"
    assert not _is_signed_in(client)


@pytest.mark.django_db
def test_inactive_user_is_refused(tenant_a, client):
    membership = MembershipFactory(tenant=tenant_a)
    membership.user.is_active = False
    membership.user.save()

    response = _callback(client, _google_claims(membership.user.email))
    assert response["Location"] == "/accounts/refused"
    assert not _is_signed_in(client)


@pytest.mark.django_db
def test_email_match_is_case_insensitive(tenant_a, client):
    membership = MembershipFactory(tenant=tenant_a)
    response = _callback(client, _google_claims(membership.user.email.upper()))
    assert response.status_code == 302
    assert _is_signed_in(client)


@pytest.mark.django_db
def test_second_sign_in_reuses_the_same_social_account(tenant_a, client):
    membership = MembershipFactory(tenant=tenant_a)
    _callback(client, _google_claims(membership.user.email))
    client.logout()
    _callback(client, _google_claims(membership.user.email))

    assert User.objects.count() == 1
    assert SocialAccount.objects.count() == 1


@pytest.mark.django_db
def test_uninvited_user_cannot_reach_a_signup_route(client):
    """The signup routes and allauth's signup_closed template are unreachable."""
    from django.urls import resolve, reverse

    for name in ("account_signup", "socialaccount_signup"):
        # Resolve by NAME, not by a guessed path: allauth serves the social
        # signup at /accounts/3rdparty/signup/, and an override written against
        # a guessed path silently fails to shadow it.
        url = reverse(name)
        assert resolve(url).func is login_refused, (
            f"{name} ({url}) still resolves to {resolve(url).func!r}, so "
            "allauth's signup_closed page is reachable."
        )
        response = client.get(url)
        assert response.status_code == 403, f"{url} returned {response.status_code}"
        assert b"No access to this workspace" in response.content
        assert b"Sign Up" not in response.content


@pytest.mark.django_db
def test_signup_is_closed_by_configuration_too(client):
    """Belt and braces behind the routing above."""
    from apps.accounts.adapters import InviteOnlySocialAdapter, NoSignupAccountAdapter

    assert NoSignupAccountAdapter().is_open_for_signup(None) is False
    assert InviteOnlySocialAdapter().is_open_for_signup(None, None) is False


@pytest.mark.django_db
def test_tenant_binding_after_google_sign_in(tenant_a, client):
    """The signed-in user is bound to their tenant by the middleware."""
    membership = MembershipFactory(tenant=tenant_a)
    _callback(client, _google_claims(membership.user.email))

    payload = client.get("/api/me").json()
    assert payload["authenticated"] is True
    assert payload["role"] == membership.role
    assert payload["tenant"] == str(tenant_a.pk)
