"""The OAuth flow an AI app goes through, driven the way Claude drives it:
register, authorize behind the practice sign-in with PKCE S256, exchange the
code. Shared by the AI-app tests (P7)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import Client

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def register(client: Client | None = None, **over) -> dict:
    client = client or Client()
    body = {"client_name": "Claude", "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], **over}
    response = client.post("/oauth/register", json.dumps(body), content_type="application/json")
    assert response.status_code == 201, response.content
    return response.json()


def authorize_params(client_id: str, challenge: str, **over) -> dict:
    return {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": "st8",
            "scope": "practice", "resource": settings.MCP_RESOURCE_URL, **over}


def code_from(response) -> str:
    assert response.status_code == 302, response.content
    query = parse_qs(urlsplit(response["Location"]).query)
    assert query.get("state") == ["st8"]
    return query["code"][0]


def connect(membership, *, app=None) -> dict:
    """The whole flow for one person; returns the token response, plus
    `client_id`."""
    app = app or register()
    verifier, challenge = pkce()
    browser = Client()
    browser.force_login(membership.user)
    params = authorize_params(app["client_id"], challenge)
    assert browser.get("/oauth/authorize", params).status_code == 200
    code = code_from(browser.post("/oauth/authorize", {**params, "decision": "allow"}))
    tokens = Client().post("/oauth/token", {
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": app["client_id"], "code_verifier": verifier,
        "resource": settings.MCP_RESOURCE_URL})
    assert tokens.status_code == 200, tokens.content
    return {**tokens.json(), "client_id": app["client_id"]}
