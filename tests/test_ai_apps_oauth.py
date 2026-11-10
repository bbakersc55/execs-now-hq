"""Signing an AI app in (P7, docs/p7_mcp.md, "Sign-in"): the app's own OAuth
2.1 authorization server. Dynamic registration, authorization code with PKCE
S256 only behind the practice sign-in, client users refused outright, access
tokens an hour and refresh tokens thirty days with rotation, resource
indicators honored, and revocation ending access."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.aiconnect.models import AiAppCode, AiAppConnection, AiAppToken, digest
from apps.aiconnect.oauth import principal_for
from apps.tenancy.models import AuditEvent

from .ai_app_flow import REDIRECT, authorize_params, code_from, connect, pkce, register
from .factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _token(client_id, **form):
    return Client().post("/oauth/token", {"client_id": client_id, **form})


# ------------------------------------------------------------------ metadata

def test_the_metadata_names_the_endpoints_and_s256_only(client):
    data = client.get("/.well-known/oauth-authorization-server").json()
    base = settings.OAUTH_ISSUER_URL
    assert data["issuer"] == base
    assert data["authorization_endpoint"] == f"{base}/oauth/authorize"
    assert data["token_endpoint"] == f"{base}/oauth/token"
    assert data["registration_endpoint"] == f"{base}/oauth/register"
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["token_endpoint_auth_methods_supported"] == ["none"]


# -------------------------------------------------------------- registration

def test_dynamic_registration_gives_a_public_client(client):
    app = register(client)
    assert app["client_id"] and app["token_endpoint_auth_method"] == "none"
    assert app["redirect_uris"] == [REDIRECT]


@pytest.mark.parametrize("body,why", [
    ({"redirect_uris": ["http://evil.example/cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": []}, "invalid_redirect_uri"),
    ({"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_post"},
     "invalid_client_metadata"),
])
def test_registration_refuses_what_it_should(client, body, why):
    import json

    response = client.post("/oauth/register", json.dumps(body), content_type="application/json")
    assert response.status_code == 400 and response.json()["error"] == why


def test_a_desktop_loopback_redirect_is_allowed(client):
    assert register(client, redirect_uris=["http://127.0.0.1:33418/callback"])["client_id"]


# ------------------------------------------------------------------ authorize

def test_the_authorize_page_names_practice_role_and_the_provider_line(seeded_tenant, cf):
    app = register()
    _, challenge = pkce()
    browser = Client()
    browser.force_login(cf.user)
    page = browser.get("/oauth/authorize", authorize_params(app["client_id"], challenge))
    text = page.content.decode()
    assert page.status_code == 200
    assert seeded_tenant.name in text and "Associate" in text and "Claude" in text
    assert ("provider will receive the data of " + seeded_tenant.name) in " ".join(text.split())
    assert "never" in text.lower() and "Send mail" in text


@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_user_is_refused_outright(seeded_tenant, role):
    from .factories import ClientCompanyFactory

    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=ClientCompanyFactory(tenant=seeded_tenant))
    app = register()
    _, challenge = pkce()
    browser = Client()
    browser.force_login(member.user)
    params = authorize_params(app["client_id"], challenge)
    page = browser.get("/oauth/authorize", params)
    assert page.status_code == 403 and "client" in page.content.decode().lower()
    refused = browser.post("/oauth/authorize", {**params, "decision": "allow"})
    assert refused.status_code == 403
    assert not AiAppConnection.all_objects.exists() and not AiAppCode.all_objects.exists()


def test_signed_out_it_asks_for_sign_in_and_comes_back_after(seeded_tenant, ff, settings):
    settings.APP_ROOT_URL = "/"            # production's: the shell serves "/"
    app = register()
    _, challenge = pkce()
    browser = Client()
    params = authorize_params(app["client_id"], challenge)
    page = browser.get("/oauth/authorize", params)
    assert page.status_code == 200 and "Sign in" in page.content.decode()
    browser.force_login(ff.user)
    back = browser.get("/")
    assert back.status_code == 302 and back["Location"].startswith("/oauth/authorize?")
    assert browser.get(back["Location"]).status_code == 200


def test_pkce_s256_is_required(seeded_tenant, ff):
    app = register()
    browser = Client()
    browser.force_login(ff.user)
    for over in ({"code_challenge_method": "plain"}, {"code_challenge": ""}):
        response = browser.get("/oauth/authorize", authorize_params(app["client_id"], "x" * 43,
                                                                    **over))
        assert response.status_code == 302
        assert parse_qs(urlsplit(response["Location"]).query)["error"] == ["invalid_request"]


def test_an_unregistered_redirect_is_never_followed(seeded_tenant, ff):
    app = register()
    browser = Client()
    browser.force_login(ff.user)
    response = browser.get("/oauth/authorize", authorize_params(
        app["client_id"], "x" * 43, redirect_uri="https://evil.example/cb"))
    assert response.status_code == 400


def test_another_resource_is_refused(seeded_tenant, ff):
    app = register()
    browser = Client()
    browser.force_login(ff.user)
    response = browser.get("/oauth/authorize", authorize_params(
        app["client_id"], "x" * 43, resource="https://other.example/mcp"))
    assert parse_qs(urlsplit(response["Location"]).query)["error"] == ["invalid_target"]


def test_cancel_returns_access_denied(seeded_tenant, ff):
    app = register()
    _, challenge = pkce()
    browser = Client()
    browser.force_login(ff.user)
    params = authorize_params(app["client_id"], challenge)
    response = browser.post("/oauth/authorize", {**params, "decision": "deny"})
    assert parse_qs(urlsplit(response["Location"]).query)["error"] == ["access_denied"]
    assert not AiAppConnection.all_objects.exists()


# --------------------------------------------------------------------- token

def test_the_pkce_flow_issues_an_hour_and_thirty_days_bound_to_the_resource(seeded_tenant, ff):
    tokens = connect(ff)
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
    access = AiAppToken.all_objects.get(token_hash=digest(tokens["access_token"]))
    refresh = AiAppToken.all_objects.get(token_hash=digest(tokens["refresh_token"]))
    assert access.kind == "access" and refresh.kind == "refresh"
    assert access.resource == refresh.resource == settings.MCP_RESOURCE_URL
    assert abs((access.expires_at - timezone.now()) - timedelta(hours=1)) < timedelta(minutes=1)
    assert abs((refresh.expires_at - timezone.now()) - timedelta(days=30)) < timedelta(minutes=1)
    connection = access.connection
    assert (connection.user_id, connection.tenant_id, connection.role) == (
        ff.user_id, seeded_tenant.pk, "FF")
    # Nothing secret is stored as itself.
    assert tokens["access_token"] not in {t.token_hash for t in AiAppToken.all_objects.all()}
    assert AuditEvent.all_objects.filter(verb="ai_app.connected").count() == 1


def test_a_wrong_verifier_is_refused(seeded_tenant, ff):
    app = register()
    _, challenge = pkce()
    browser = Client()
    browser.force_login(ff.user)
    params = authorize_params(app["client_id"], challenge)
    code = code_from(browser.post("/oauth/authorize", {**params, "decision": "allow"}))
    response = _token(app["client_id"], grant_type="authorization_code", code=code,
                      redirect_uri=REDIRECT, code_verifier=pkce()[0])
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"


def test_a_code_used_twice_revokes_the_connection(seeded_tenant, ff):
    app = register()
    verifier, challenge = pkce()
    browser = Client()
    browser.force_login(ff.user)
    params = authorize_params(app["client_id"], challenge)
    code = code_from(browser.post("/oauth/authorize", {**params, "decision": "allow"}))
    form = dict(grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                code_verifier=verifier)
    first = _token(app["client_id"], **form).json()
    assert _token(app["client_id"], **form).json()["error"] == "invalid_grant"
    assert principal_for(first["access_token"]) == (None, None)


def test_a_token_for_another_resource_is_refused(seeded_tenant, ff):
    tokens = connect(ff)
    response = _token(tokens["client_id"], grant_type="refresh_token",
                      refresh_token=tokens["refresh_token"], resource="https://other.example/")
    assert response.json()["error"] == "invalid_target"


def test_refresh_rotates_and_a_reused_refresh_token_revokes(seeded_tenant, ff):
    tokens = connect(ff)
    fresh = _token(tokens["client_id"], grant_type="refresh_token",
                   refresh_token=tokens["refresh_token"]).json()
    assert fresh["access_token"] != tokens["access_token"]
    assert fresh["refresh_token"] != tokens["refresh_token"]
    again = _token(tokens["client_id"], grant_type="refresh_token",
                   refresh_token=tokens["refresh_token"])
    assert again.json()["error"] == "invalid_grant"
    assert principal_for(fresh["access_token"]) == (None, None)


def test_an_expired_access_token_stops(seeded_tenant, ff):
    tokens = connect(ff)
    AiAppToken.all_objects.filter(kind="access").update(
        expires_at=timezone.now() - timedelta(seconds=1))
    assert principal_for(tokens["access_token"]) == (None, None)


def test_a_role_change_or_a_revoked_membership_stops_the_token(seeded_tenant, cf):
    tokens = connect(cf)
    assert principal_for(tokens["access_token"])[0] is not None
    cf.role = "VA"
    cf.save(update_fields=["role"])
    assert principal_for(tokens["access_token"]) == (None, None)


# ------------------------------------------------- Connected AI apps, Revoke

def test_profile_lists_my_connected_apps_and_revoke_ends_access(seeded_tenant, ff, api):
    tokens = connect(ff)
    mine = api.as_(ff).get("/api/ai/connections/").json()
    assert [(c["app"], c["role"]) for c in mine] == [("Claude", "Practice owner")]
    assert mine[0]["connected_at"] and "last_used_at" in mine[0]
    assert api.as_(ff).post(f"/api/ai/connections/{mine[0]['id']}/revoke").status_code == 200
    assert principal_for(tokens["access_token"]) == (None, None)
    assert api.as_(ff).get("/api/ai/connections/").json() == []
    assert _token(tokens["client_id"], grant_type="refresh_token",
                  refresh_token=tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_the_practice_owner_sees_and_revokes_everyones_an_assistant_only_their_own(
        seeded_tenant, ff, va, api):
    connect(va)
    connect(ff)
    owner = api.as_(ff).get("/api/ai/apps/").json()
    assert owner["connector_url"] == settings.MCP_RESOURCE_URL
    assert len(owner["connections"]) == 2 and owner["everyone"] is True
    assistant = api.as_(va).get("/api/ai/apps/").json()
    assert len(assistant["connections"]) == 1 and assistant["everyone"] is False
    theirs = next(c for c in owner["connections"] if c["role"] == "Practice owner")
    assert api.as_(va).post(f"/api/ai/connections/{theirs['id']}/revoke").status_code == 404
    vas = next(c for c in owner["connections"] if c["role"] == "Assistant")
    assert api.as_(ff).post(f"/api/ai/connections/{vas['id']}/revoke").status_code == 200


def test_tenant_isolation_another_practice_sees_none_of_it(seeded_tenant, ff, tenant_b, api):
    connect(ff)
    owner_b = MembershipFactory(tenant=tenant_b, role="FF")
    assert api.as_(owner_b).get("/api/ai/apps/").json()["connections"] == []
    theirs = AiAppConnection.all_objects.get()
    assert api.as_(owner_b).post(f"/api/ai/connections/{theirs.pk}/revoke").status_code == 404
    assert AiAppConnection.all_objects.get().revoked_at is None


def test_a_client_user_cannot_reach_the_endpoints(seeded_tenant, fcc, api):
    for url in ("/api/ai/connections/", "/api/ai/apps/", "/api/ai/actions/"):
        assert api.as_(fcc).get(url).status_code == 403


def test_rfc7009_revoke_disconnects(seeded_tenant, ff):
    tokens = connect(ff)
    assert Client().post("/oauth/revoke", {"token": tokens["refresh_token"],
                                           "client_id": tokens["client_id"]}).status_code == 200
    assert principal_for(tokens["access_token"]) == (None, None)
