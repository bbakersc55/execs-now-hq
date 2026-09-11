"""Tier 1 Gmail connect — the two mandatory test families (CLAUDE.md).

Role boundaries: FF and CF connect their own mailbox; a VA has no control at
all (H7); client users never reach the surface. Tenant isolation: "my
connection" never resolves to another tenant's row, and neither does a
disconnect.

Every test stubs Google's network. Nothing here reaches the internet.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.utils import timezone

from apps.crm.models import GmailConnection
from apps.crm.services import gmail_oauth
from apps.tenancy.models import Membership, Role, TenantSecret

from . import registry_config  # noqa: F401
from .factories import GmailConnectionFactory, MembershipFactory, TenantFactory

ALIAS = "info@getexecutivesnow.com"
STATUS = "/api/gmail-connection/"
START = "/api/gmail-connection/start/"
VERIFY = "/api/gmail-connection/verify/"
DISCONNECT = "/api/gmail-connection/disconnect/"
CALLBACK = "/accounts/gmail/callback"


def _response(ok=True, status=200, payload=None):
    stub = mock.Mock()
    stub.ok = ok
    stub.status_code = status
    stub.json.return_value = payload or {}
    stub.text = ""
    return stub


def _send_as(*addresses, status="accepted"):
    return {"sendAs": [
        {"sendAsEmail": a, "verificationStatus": status, "isPrimary": i == 0}
        for i, a in enumerate(addresses)
    ]}


@pytest.fixture
def gmail_net():
    """Token refresh + send-as list, both stubbed. Defaults to a healthy account."""
    with mock.patch("apps.crm.services.transport.requests") as req, \
            mock.patch("apps.crm.services.secrets.read_secret", return_value="refresh"):
        req.post.return_value = _response(payload={"access_token": "at"})
        req.get.return_value = _response(payload=_send_as("bryan@getexecutivesnow.com", ALIAS))
        yield req


@pytest.fixture
def connected_ff(seeded_tenant, ff):
    return GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user, email_address="bryan@getexecutivesnow.com",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
        send_as_address=ALIAS, send_as_verified_at=timezone.now(),
    )


# ------------------------------------------------------- role boundaries (H7)

@pytest.mark.django_db
@pytest.mark.parametrize("path", [STATUS, START, VERIFY, DISCONNECT])
def test_va_has_no_mailbox_control(path, va, api, gmail_net):
    """H7 — a VA gets no control here, not even read."""
    client = api.as_(va)
    response = client.get(path) if path == STATUS else client.post(path)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path", [STATUS, START, VERIFY, DISCONNECT])
def test_client_users_never_reach_it(path, fcc, api, gmail_net):
    """Matrix 4.18 — Module 1 has no client-facing surface."""
    client = api.as_(fcc)
    response = client.get(path) if path == STATUS else client.post(path)
    assert response.status_code == 403


@pytest.mark.django_db
def test_va_cannot_store_a_connection_through_the_callback(va, api, seeded_tenant):
    """The H7 boundary holds at the redirect target too, not only on the API."""
    client = api.as_(va)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "st"
    session.save()

    response = client.get(CALLBACK, {"code": "c", "state": "st"})

    assert response.status_code == 302
    assert "gmail_error" in response["Location"]
    assert not GmailConnection.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF"])
def test_ff_and_cf_may_read_their_own_status(role, seeded_tenant, api, gmail_net):
    membership = MembershipFactory(tenant=seeded_tenant, role=role)
    response = api.as_(membership).get(STATUS)
    assert response.status_code == 200
    assert response.json()["connected"] is False


@pytest.mark.django_db
def test_a_cf_does_not_see_the_ffs_connection_as_their_own(
    seeded_tenant, ff, cf, api, connected_ff, gmail_net
):
    """Same tenant, different person: per-user scoping, not just per-tenant."""
    body = api.as_(cf).get(STATUS).json()

    assert body["connected"] is False
    assert body["email_address"] == ""
    # But the practice-level fact is visible: a CF whose mail is blocked by the
    # FF's broken token needs to be able to see that without guessing.
    assert body["practice_sending"]["account"] == "bryan@getexecutivesnow.com"


@pytest.mark.django_db
def test_a_cf_cannot_disconnect_the_ffs_connection(
    seeded_tenant, ff, cf, api, connected_ff, gmail_net
):
    response = api.as_(cf).post(DISCONNECT)

    assert response.status_code == 400
    assert GmailConnection.all_objects.filter(pk=connected_ff.pk).exists()


# ---------------------------------------------------------- tenant isolation

@pytest.mark.django_db
def test_another_tenants_connection_is_invisible(seeded_tenant, ff, api, gmail_net):
    other_tenant = TenantFactory(name="Other practice", slug="other-practice")
    other_ff = MembershipFactory(tenant=other_tenant, role=Role.FF)
    GmailConnectionFactory(
        tenant=other_tenant, user=other_ff.user, email_address="someone@other.invalid",
        send_as_address=ALIAS, send_as_verified_at=timezone.now(),
    )

    body = api.as_(ff).get(STATUS).json()

    assert body["connected"] is False
    assert body["practice_sending"]["ok"] is False


@pytest.mark.django_db
def test_disconnect_cannot_reach_another_tenants_row(seeded_tenant, ff, api, gmail_net):
    other_tenant = TenantFactory(name="Other practice", slug="other-practice-2")
    other_ff = MembershipFactory(tenant=other_tenant, role=Role.FF)
    theirs = GmailConnectionFactory(
        tenant=other_tenant, user=other_ff.user, email_address="someone@other.invalid",
    )

    assert api.as_(ff).post(DISCONNECT).status_code == 400
    assert GmailConnection.all_objects.filter(pk=theirs.pk).exists()


# ------------------------------------------------------------------ behaviour

@pytest.mark.django_db
def test_status_reports_the_send_as_list_and_marks_the_alias(
    seeded_tenant, ff, api, connected_ff, gmail_net
):
    body = api.as_(ff).get(STATUS).json()

    assert body["connected"] is True
    assert body["alias"] == ALIAS
    assert body["alias_verified"] is True
    assert body["alias_listed"] is True
    assert [e["address"] for e in body["send_as"]] == ["bryan@getexecutivesnow.com", ALIAS]
    assert [e for e in body["send_as"] if e["is_alias"]][0]["address"] == ALIAS
    assert body["transport"] == "gmail"
    assert body["is_sending_connection"] is True


@pytest.mark.django_db
def test_status_marks_the_alias_missing_when_gmail_does_not_list_it(
    seeded_tenant, ff, api, gmail_net
):
    GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user, email_address="bryan@getexecutivesnow.com",
    )
    gmail_net.get.return_value = _response(payload=_send_as("bryan@getexecutivesnow.com"))

    body = api.as_(ff).get(STATUS).json()

    assert body["alias_listed"] is False
    assert body["alias_verified"] is False


@pytest.mark.django_db
def test_a_dead_token_does_not_break_the_settings_page(
    seeded_tenant, ff, api, connected_ff, gmail_net
):
    """This page is where you go to fix a revoked token — it must render."""
    gmail_net.post.return_value = _response(ok=False, status=400)

    response = api.as_(ff).get(STATUS)

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["send_as"] == []
    assert "Reconnect Gmail" in body["send_as_error"]


@pytest.mark.django_db
def test_start_returns_a_consent_url_scoped_to_tier_1(
    seeded_tenant, ff, api, gmail_net, settings
):
    settings.GOOGLE_OAUTH_CLIENT_ID = "cid"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "sec"

    from urllib.parse import parse_qs, urlparse

    url = api.as_(ff).post(START).json()["authorization_url"]
    scopes = parse_qs(urlparse(url).query)["scope"][0].split(" ")

    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/gmail.settings.basic" in scopes
    # Tier 2 is opt-in per user (FR-6.3g) and must not ride along here.
    assert not any("gmail.readonly" in s for s in scopes)
    assert "access_type=offline" in url
    # `consent` must survive alongside the account picker: without it Google
    # withholds the refresh token on a reconnect.
    assert "consent" in parse_qs(urlparse(url).query)["prompt"][0].split(" ")


@pytest.mark.django_db
def test_start_points_google_at_the_right_account(
    seeded_tenant, api, gmail_net, settings
):
    """Without these, Google offers whatever personal account the browser last
    used and the owner connects the wrong mailbox — which only surfaces later,
    as mail sent from the wrong address."""
    from urllib.parse import parse_qs, urlparse

    settings.GOOGLE_OAUTH_CLIENT_ID = "cid"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "sec"
    membership = MembershipFactory(tenant=seeded_tenant, role=Role.FF)
    membership.user.email = "bryan.baker@getexecutivesnow.com"
    membership.user.save(update_fields=["email"])

    url = api.as_(membership).post(START).json()["authorization_url"]
    query = parse_qs(urlparse(url).query)

    assert query["login_hint"] == ["bryan.baker@getexecutivesnow.com"]
    assert query["hd"] == ["getexecutivesnow.com"]
    # Both, in this order: the picker so the right account can be chosen, and
    # the consent screen so Google reissues a refresh token.
    assert query["prompt"] == ["select_account consent"]
    assert query["access_type"] == ["offline"]


@pytest.mark.django_db
def test_the_domain_hint_follows_the_user_not_a_hardcoded_domain(
    seeded_tenant, api, gmail_net, settings
):
    """V1: another practice on its own Workspace domain must not be sent to ours."""
    from urllib.parse import parse_qs, urlparse

    settings.GOOGLE_OAUTH_CLIENT_ID = "cid"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "sec"
    membership = MembershipFactory(tenant=seeded_tenant, role=Role.CF)
    membership.user.email = "dana@otherpractice.example"
    membership.user.save(update_fields=["email"])

    url = api.as_(membership).post(START).json()["authorization_url"]
    query = parse_qs(urlparse(url).query)

    assert query["hd"] == ["otherpractice.example"]
    assert query["login_hint"] == ["dana@otherpractice.example"]


@pytest.mark.django_db
def test_start_reports_the_redirect_uri_it_sends(seeded_tenant, ff, api, gmail_net, settings):
    """The value that must be registered on the OAuth client, character for
    character. A mismatch fails at Google before any permission list is shown."""
    from urllib.parse import parse_qs, urlparse

    settings.GOOGLE_OAUTH_CLIENT_ID = "cid"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "sec"

    body = api.as_(ff).post(START).json()
    sent = parse_qs(urlparse(body["authorization_url"]).query)["redirect_uri"][0]

    assert body["redirect_uri"] == sent
    assert sent == f"{settings.PUBLIC_BASE_URL.rstrip('/')}/accounts/gmail/callback"


@pytest.mark.django_db
def test_disconnect_deletes_the_stored_token_with_the_row(
    seeded_tenant, ff, api, gmail_net
):
    from apps.crm.services.secrets import write_secret

    secret = write_secret(tenant=seeded_tenant, kind="gmail_refresh",
                          value="refresh-token", user=ff.user)
    connection = GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user,
        email_address="bryan@getexecutivesnow.com", secret=secret,
    )

    assert api.as_(ff).post(DISCONNECT).status_code == 200
    assert not GmailConnection.all_objects.filter(pk=connection.pk).exists()
    assert not TenantSecret.all_objects.filter(pk=secret.pk).exists()


# ------------------------------------------------------------------- callback

@pytest.mark.django_db
def test_callback_refuses_a_state_this_browser_did_not_start(
    seeded_tenant, ff, api
):
    """CSRF on the consent round-trip."""
    client = api.as_(ff)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "expected"
    session.save()

    response = client.get(CALLBACK, {"code": "c", "state": "forged"})

    assert response.status_code == 302
    assert "gmail_error" in response["Location"]
    assert not GmailConnection.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
def test_callback_stores_nothing_without_a_refresh_token(seeded_tenant, ff, api):
    """An access token alone looks healthy for an hour and then stops."""
    client = api.as_(ff)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "st"
    session.save()

    with mock.patch("apps.crm.services.gmail_oauth.requests") as req:
        req.post.return_value = _response(payload={"access_token": "at"})
        response = client.get(CALLBACK, {"code": "c", "state": "st"})

    assert response.status_code == 302
    assert "gmail_error" in response["Location"]
    assert not GmailConnection.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
def test_callback_stores_nothing_when_a_scope_was_unticked(seeded_tenant, ff, api):
    client = api.as_(ff)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "st"
    session.save()

    with mock.patch("apps.crm.services.gmail_oauth.requests") as req:
        req.post.return_value = _response(payload={
            "access_token": "at", "refresh_token": "rt",
            "scope": "openid email https://www.googleapis.com/auth/gmail.send",
        })
        response = client.get(CALLBACK, {"code": "c", "state": "st"})

    assert "gmail_error" in response["Location"]
    assert not GmailConnection.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
def test_callback_connects_and_verifies_the_alias(seeded_tenant, ff, api, gmail_net):
    client = api.as_(ff)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "st"
    session.save()

    with mock.patch("apps.crm.services.gmail_oauth.requests") as req:
        req.post.return_value = _response(payload={
            "access_token": "at", "refresh_token": "rt",
            "scope": " ".join(gmail_oauth.TIER1_SCOPES),
        })
        req.get.return_value = _response(payload={"email": "bryan@getexecutivesnow.com"})
        response = client.get(CALLBACK, {"code": "c", "state": "st"})

    assert response.status_code == 302
    assert "gmail_connected=" in response["Location"]
    connection = GmailConnection.all_objects.get(tenant=seeded_tenant, user=ff.user)
    assert connection.email_address == "bryan@getexecutivesnow.com"
    assert connection.send_as_verified_at is not None
    assert connection.secret_id is not None


@pytest.mark.django_db
def test_a_reconnect_does_not_inherit_the_old_verification(
    seeded_tenant, ff, api, gmail_net, connected_ff
):
    """The alias could have been removed in Gmail since the last connect."""
    gmail_net.get.return_value = _response(payload=_send_as("bryan@getexecutivesnow.com"))
    client = api.as_(ff)
    session = client.session
    session[gmail_oauth.STATE_SESSION_KEY] = "st"
    session.save()

    with mock.patch("apps.crm.services.gmail_oauth.requests") as req:
        req.post.return_value = _response(payload={
            "access_token": "at", "refresh_token": "rt",
            "scope": " ".join(gmail_oauth.TIER1_SCOPES),
        })
        req.get.return_value = _response(payload={"email": "bryan@getexecutivesnow.com"})
        response = client.get(CALLBACK, {"code": "c", "state": "st"})

    connected_ff.refresh_from_db()
    assert connected_ff.send_as_verified_at is None
    assert "gmail_warning" in response["Location"]
