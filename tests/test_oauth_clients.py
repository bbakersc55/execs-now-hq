"""P2 D1: two OAuth clients. Executives Now's Workspace keeps its Internal
client; every other practice signs in and connects Gmail through the External
one. Google is mocked; what is tested is which client each step uses, and who
the External sign-in admits."""

from __future__ import annotations

from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client

from apps.accounts import google_external
from apps.crm.services import gmail_oauth, transport
from apps.tenancy.models import Tenant

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, TenantFactory


@pytest.fixture(autouse=True)
def two_clients(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = "internal-id", "i-s"
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID = "external-id"
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_SECRET = "e-s"


@pytest.fixture
def outside(db):
    return TenantFactory(name="Blue Sky", slug="blue-sky",
                         oauth_client=Tenant.OAuthClient.EXTERNAL)


def query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ------------------------------------------------------------------ which client

@pytest.mark.django_db
def test_each_practice_uses_its_own_client(seeded_tenant, outside):
    assert gmail_oauth.client_for(seeded_tenant) == ("internal-id", "i-s")
    assert gmail_oauth.client_for(outside) == ("external-id", "e-s")
    assert query(gmail_oauth.authorization_url("s", tenant=outside))["client_id"] == "external-id"
    assert query(gmail_oauth.authorization_url("s", tenant=seeded_tenant))["client_id"] == \
        "internal-id"


@pytest.mark.django_db
def test_an_external_practice_without_the_second_client_is_not_configured(settings, outside):
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID = ""
    assert gmail_oauth.is_configured(outside) is False


@pytest.mark.django_db
def test_exchange_and_refresh_use_the_client_that_issued_the_token(outside):
    response = mock.Mock(ok=True)
    response.json.return_value = {"refresh_token": "r", "access_token": "a", "scope": ""}
    with mock.patch("apps.crm.services.gmail_oauth.requests.post",
                    return_value=response) as posted:
        gmail_oauth.exchange_code("code", tenant=outside)
    assert posted.call_args.kwargs["data"]["client_id"] == "external-id"

    connection = mock.Mock(tenant=outside, email_address="shawn@bluesky.invalid", secret=None)
    with mock.patch("apps.crm.services.secrets.read_secret", return_value="refresh"), \
         mock.patch("apps.crm.services.transport.requests.post",
                    return_value=response) as refreshed:
        assert transport.access_token_for(connection) == "a"
    assert refreshed.call_args.kwargs["data"]["client_id"] == "external-id"


# ------------------------------------------------------------------ the sign-in

@pytest.mark.django_db
def test_executives_now_staff_and_unknown_addresses_go_to_the_workspace_sign_in(seeded_tenant):
    staff = _member(seeded_tenant, "VA")
    for email in (staff.user.email, "nobody@nowhere.invalid"):
        response = Client().get("/accounts/google/start", {"email": email})
        assert response.status_code == 302 and response.url == "/accounts/google/login/"


@pytest.mark.django_db
def test_outside_staff_go_to_the_external_client(outside):
    staff = _member(outside, "FF")
    response = Client().get("/accounts/google/start", {"email": staff.user.email})
    params = query(response.url)
    assert response.url.startswith(gmail_oauth.AUTH_URL)
    assert params["client_id"] == "external-id"
    assert params["login_hint"] == staff.user.email
    assert params["scope"] == "openid email profile"
    assert params["redirect_uri"].endswith("/accounts/google/external/callback")


@pytest.mark.django_db
def test_an_outside_client_user_is_never_sent_to_google(outside):
    client_user = _member(outside, "FCC", ClientCompanyFactory(tenant=outside))
    response = Client().get("/accounts/google/start", {"email": client_user.user.email})
    assert response.url == "/accounts/google/login/"   # and allauth refuses them there


def _callback(browser, *, email, verified=True, state="s1"):
    session = browser.session
    session[google_external.STATE_KEY] = "s1"
    session.save()
    token = mock.Mock(ok=True)
    token.raise_for_status.return_value = None
    token.json.return_value = {"access_token": "a"}
    info = mock.Mock()
    info.raise_for_status.return_value = None
    info.json.return_value = {"email": email, "email_verified": verified}
    with mock.patch("apps.accounts.google_external.requests.post", return_value=token), \
         mock.patch("apps.accounts.google_external.requests.get", return_value=info):
        return browser.get("/accounts/google/external/callback", {"code": "c", "state": state})


@pytest.mark.django_db
def test_the_callback_signs_in_outside_staff(outside):
    staff = _member(outside, "CF")
    browser = Client()
    response = _callback(browser, email=staff.user.email)
    assert response.status_code == 302 and "refused" not in response.url
    assert browser.get("/api/me").json()["tenant"] == str(outside.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["unverified", "wrong_state", "unknown", "workspace",
                                  "archived", "client"])
def test_the_callback_admits_nobody_else(case, outside, seeded_tenant):
    staff = _member(outside, "FF")
    email = staff.user.email
    if case == "unknown":
        email = "stranger@bluesky.invalid"
    if case == "workspace":
        email = _member(seeded_tenant, "FF").user.email
    if case == "archived":
        Tenant.objects.filter(pk=outside.pk).update(status="archived")
    if case == "client":
        email = _member(outside, "ECC", ClientCompanyFactory(tenant=outside)).user.email
    browser = Client()
    response = _callback(browser, email=email, verified=case != "unverified",
                         state="forged" if case == "wrong_state" else "s1")
    assert "refused" in response.url
    assert browser.get("/api/me").status_code == 401
