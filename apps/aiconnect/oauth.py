"""The OAuth 2.1 authorization server AI apps sign in through (P7,
docs/p7_mcp.md, "Sign-in"). Served by web at PUBLIC_BASE_URL:

- `/.well-known/oauth-authorization-server` (RFC 8414) — the metadata the
  MCP server's protected-resource metadata points at;
- `/oauth/register` — dynamic client registration (RFC 7591), public clients
  only (no secret; PKCE is the proof);
- `/oauth/authorize` — authorization code, **PKCE S256 only**, behind the
  normal practice sign-in; the page names the practice, the role and the
  provider line, and refuses client users outright;
- `/oauth/token` — the code, and refresh tokens (thirty days, rotated);
- `/oauth/revoke` (RFC 7009) — revokes the whole connection.

Resource indicators (RFC 8707): a `resource` other than the MCP server's own
is refused (`invalid_target`); every token is bound to it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared
from apps.aiconnect.models import AiAppClient, AiAppCode, AiAppConnection, AiAppToken, digest

SCOPE = "practice"
CODE_TTL = timedelta(minutes=10)
#: Where the authorize page waits while someone signs in; the app shell sends
#: them back (`resume_url`).
RESUME_KEY = "ai_app_authorize_resume"
RESUME_TTL_SECONDS = 15 * 60
REGISTER_LIMIT = RateLimit(limit=30, window_seconds=3600, prefix="ai-app-register")
TOKEN_LIMIT = RateLimit(limit=120, window_seconds=3600, prefix="ai-app-token")
STAFF = ("FF", "CF", "VA")


def issuer() -> str:
    return settings.OAUTH_ISSUER_URL


def _json(body: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "no-store"
    response["Access-Control-Allow-Origin"] = "*"
    return response


def _error(code: str, description: str, status: int = 400) -> JsonResponse:
    return _json({"error": code, "error_description": description}, status)


def _preflight() -> HttpResponse:
    response = HttpResponse(status=204)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, MCP-Protocol-Version"
    response["Access-Control-Max-Age"] = "600"
    return response


# ------------------------------------------------------------------ metadata

@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def metadata(request):
    if request.method == "OPTIONS":
        return _preflight()
    base = issuer()
    return _json({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "authorization_response_iss_parameter_supported": True,
    })


# ------------------------------------------------------------- registration

def _redirect_ok(uri: str) -> bool:
    """https anywhere; http only to this machine (a desktop app's loopback)."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def register(request):
    if request.method == "OPTIONS":
        return _preflight()
    if too_many_shared(REGISTER_LIMIT, client_ip(request)):
        return _error("slow_down", "Too many registrations from here; try again later.", 429)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return _error("invalid_client_metadata", "The body must be JSON.")
    if not isinstance(data, dict):
        return _error("invalid_client_metadata", "The body must be a JSON object.")
    uris = data.get("redirect_uris")
    if (not isinstance(uris, list) or not uris or len(uris) > 10
            or not all(isinstance(u, str) and len(u) <= 500 and _redirect_ok(u) for u in uris)):
        return _error("invalid_redirect_uri",
                      "redirect_uris must list https addresses (or http to localhost).")
    method = data.get("token_endpoint_auth_method") or "none"
    if method != "none":
        return _error("invalid_client_metadata",
                      "Only public clients are registered here: token_endpoint_auth_method "
                      "must be none, with PKCE.")
    grants = data.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
        return _error("invalid_client_metadata", "Only authorization_code and refresh_token.")
    if data.get("response_types") not in (None, ["code"]):
        return _error("invalid_client_metadata", "Only the code response type.")
    name = str(data.get("client_name") or "")[:200]
    client_uri = str(data.get("client_uri") or "")[:500]
    if client_uri and not client_uri.startswith("https://"):
        client_uri = ""
    client = AiAppClient.objects.create(
        client_id=secrets.token_urlsafe(24), client_name=name, client_uri=client_uri,
        redirect_uris=uris, registration={k: data[k] for k in list(data)[:30]
                                          if isinstance(k, str)})
    return _json({
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": grants,
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }, 201)


# ----------------------------------------------------------------- authorize

def resource_ok(resource: str | None) -> bool:
    """The MCP server itself, however a client writes it."""
    if not resource:
        return True
    allowed = {settings.MCP_RESOURCE_URL, settings.MCP_PUBLIC_URL}
    return resource.rstrip("/") in allowed


def _redirect(uri: str, **params) -> HttpResponseRedirect:
    joiner = "&" if urlsplit(uri).query else "?"
    params = {k: v for k, v in params.items() if v}
    return HttpResponseRedirect(f"{uri}{joiner}{urlencode(params)}")


def _page(request, template: str, status: int = 200, **context):
    from config.branding import PRODUCT_NAME

    return render(request, f"aiconnect/{template}",
                  {"product": PRODUCT_NAME, **context}, status=status)


def _params(source) -> dict:
    keys = ("response_type", "client_id", "redirect_uri", "code_challenge",
            "code_challenge_method", "state", "scope", "resource")
    return {k: (source.get(k) or "") for k in keys}


def _membership(request):
    """The person's own membership, never one they are acting as."""
    real = getattr(request, "real_membership", None) or getattr(request, "membership", None)
    if getattr(request, "acting_as", None):
        return None, "You are acting as someone else. Stop acting as them, then connect."
    if real is None or real.revoked_at is not None:
        return None, "This account isn't a member of a practice."
    return real, ""


@require_http_methods(["GET", "POST"])
def authorize(request):
    p = _params(request.POST if request.method == "POST" else request.GET)
    client = AiAppClient.objects.filter(client_id=p["client_id"]).first()
    # Nothing is redirected until the client and its address are known good.
    if client is None:
        return _page(request, "refused.html", 400,
                     why="This AI app isn't registered here. Start the connection again from "
                         "the AI app.")
    if p["redirect_uri"] not in client.redirect_uris:
        return _page(request, "refused.html", 400,
                     why="This AI app asked to return somewhere it didn't register.")
    back = p["redirect_uri"]
    if p["response_type"] != "code":
        return _redirect(back, error="unsupported_response_type", state=p["state"])
    if not p["code_challenge"] or p["code_challenge_method"] != "S256":
        return _redirect(back, error="invalid_request", state=p["state"],
                         error_description="PKCE with S256 is required.")
    if not resource_ok(p["resource"]):
        return _redirect(back, error="invalid_target", state=p["state"],
                         error_description="That resource isn't served here.")

    if not request.user.is_authenticated:
        request.session[RESUME_KEY] = {"url": request.get_full_path(),
                                       "at": int(timezone.now().timestamp())}
        return _page(request, "authorize.html", app=client.display_name, signed_in=False)

    membership, why = _membership(request)
    if membership is None:
        return _page(request, "refused.html", 403, why=why)
    if membership.role not in STAFF:
        # Client users never connect an AI app (owner, 2026-11-10).
        return _page(request, "refused.html", 403,
                     why="AI apps connect for a practice's own team. A client's sign-in "
                         "can't be used to connect one.")

    from apps.tenancy.roles import role_label

    if request.method == "GET":
        return _page(request, "authorize.html", app=client.display_name, signed_in=True,
                     practice=membership.tenant.name, role=role_label(membership.role),
                     email=request.user.email, params=p)

    if request.POST.get("decision") != "allow":
        return _redirect(back, error="access_denied", state=p["state"], iss=issuer())
    code = secrets.token_urlsafe(32)
    with transaction.atomic():
        connection = _connection_for(client, membership, request.user)
        AiAppCode.all_objects.create(
            tenant=membership.tenant, connection=connection, code_hash=digest(code),
            redirect_uri=back, code_challenge=p["code_challenge"], scope=SCOPE,
            resource=settings.MCP_RESOURCE_URL, expires_at=timezone.now() + CODE_TTL)
    return _redirect(back, code=code, state=p["state"], iss=issuer())


def _connection_for(client, membership, user):
    """One active connection per person, practice and AI app: connecting again
    renews it rather than listing the app twice."""
    from apps.tenancy.models import AuditEvent

    connection = AiAppConnection.all_objects.filter(
        tenant=membership.tenant, client=client, user=user, revoked_at__isnull=True).first()
    if connection is not None:
        if connection.role != membership.role or connection.membership_id != membership.pk:
            connection.role = membership.role
            connection.membership = membership
            connection.save(update_fields=["role", "membership", "updated_at"])
        return connection
    connection = AiAppConnection.all_objects.create(
        tenant=membership.tenant, client=client, user=user, membership=membership,
        role=membership.role, app_name=client.display_name)
    AuditEvent.all_objects.create(
        tenant=membership.tenant, actor=user, verb="ai_app.connected",
        target_type="ai_app_connection", target_id=connection.pk,
        payload={"app": connection.app_name})
    return connection


def resume_url(request) -> str | None:
    """The authorize page to return to after signing in, if one is waiting."""
    pending = request.session.get(RESUME_KEY)
    if not pending or not request.user.is_authenticated:
        return None
    request.session.pop(RESUME_KEY, None)
    if timezone.now().timestamp() - pending.get("at", 0) > RESUME_TTL_SECONDS:
        return None
    url = str(pending.get("url") or "")
    return url if url.startswith("/oauth/authorize") else None


# --------------------------------------------------------------------- token

def _pair(connection, resource: str) -> dict:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = timezone.now()
    ttl = settings.AI_APP_ACCESS_TTL_SECONDS
    AiAppToken.all_objects.bulk_create([
        AiAppToken(tenant_id=connection.tenant_id, connection=connection,
                   kind=AiAppToken.Kind.ACCESS, token_hash=digest(access), scope=SCOPE,
                   resource=resource, expires_at=now + timedelta(seconds=ttl)),
        AiAppToken(tenant_id=connection.tenant_id, connection=connection,
                   kind=AiAppToken.Kind.REFRESH, token_hash=digest(refresh), scope=SCOPE,
                   resource=resource,
                   expires_at=now + timedelta(days=settings.AI_APP_REFRESH_TTL_DAYS)),
    ])
    return {"access_token": access, "token_type": "Bearer", "expires_in": ttl,
            "refresh_token": refresh, "scope": SCOPE}


def connection_usable(connection) -> bool:
    """Still connected, still a member, still the role it was granted as."""
    membership = connection.membership
    return (connection.revoked_at is None and membership.revoked_at is None
            and membership.role == connection.role and membership.role in STAFF
            and membership.tenant.status != "archived")


def revoke_connection(connection, *, by=None, reason: str = "revoked") -> None:
    from apps.tenancy.models import AuditEvent

    if connection.revoked_at is not None:
        return
    connection.revoked_at = timezone.now()
    connection.revoked_by = by
    connection.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=connection.tenant_id, actor=by, verb="ai_app.revoked",
        target_type="ai_app_connection", target_id=connection.pk,
        payload={"app": connection.app_name, "reason": reason})


def _verifier_ok(verifier: str, challenge: str) -> bool:
    if not verifier or not 43 <= len(verifier) <= 128:
        return False
    hashed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return secrets.compare_digest(hashed.rstrip(b"=").decode(), challenge)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def token(request):
    if request.method == "OPTIONS":
        return _preflight()
    if too_many_shared(TOKEN_LIMIT, client_ip(request)):
        return _error("slow_down", "Too many token requests from here; try again later.", 429)
    form = request.POST
    client = AiAppClient.objects.filter(client_id=form.get("client_id") or "").first()
    if client is None:
        return _error("invalid_client", "Unknown client.", 401)
    if not resource_ok(form.get("resource")):
        return _error("invalid_target", "That resource isn't served here.")
    grant = form.get("grant_type")
    if grant == "authorization_code":
        return _from_code(client, form)
    if grant == "refresh_token":
        return _from_refresh(client, form)
    return _error("unsupported_grant_type", "Only authorization_code and refresh_token.")


def _from_code(client, form):
    with transaction.atomic():
        code = (AiAppCode.all_objects.select_for_update()
                .select_related("connection__membership__tenant", "connection__client")
                .filter(code_hash=digest(form.get("code") or "")).first())
        if code is None or code.connection.client_id != client.pk:
            return _error("invalid_grant", "That code isn't valid.")
        if code.used_at is not None:
            # A code used twice: whoever holds it now may not be the app.
            revoke_connection(code.connection, reason="code reused")
            return _error("invalid_grant", "That code was already used.")
        code.used_at = timezone.now()
        code.save(update_fields=["used_at", "updated_at"])
        if code.expires_at < timezone.now():
            return _error("invalid_grant", "That code has expired.")
        if form.get("redirect_uri") != code.redirect_uri:
            return _error("invalid_grant", "redirect_uri doesn't match the authorization.")
        if not _verifier_ok(form.get("code_verifier") or "", code.code_challenge):
            return _error("invalid_grant", "The PKCE code_verifier doesn't match.")
        if not connection_usable(code.connection):
            return _error("invalid_grant", "This connection is no longer allowed.")
        return _json(_pair(code.connection, code.resource))


def _from_refresh(client, form):
    with transaction.atomic():
        row = (AiAppToken.all_objects.select_for_update()
               .select_related("connection__membership__tenant")
               .filter(token_hash=digest(form.get("refresh_token") or ""),
                       kind=AiAppToken.Kind.REFRESH).first())
        if row is None or row.connection.client_id != client.pk:
            return _error("invalid_grant", "That refresh token isn't valid.")
        if row.used_at is not None:
            revoke_connection(row.connection, reason="refresh token reused")
            return _error("invalid_grant", "That refresh token was already used.")
        if row.expires_at < timezone.now():
            return _error("invalid_grant", "That refresh token has expired. Connect again.")
        if not connection_usable(row.connection):
            return _error("invalid_grant", "This connection is no longer allowed.")
        row.used_at = timezone.now()
        row.save(update_fields=["used_at", "updated_at"])
        return _json(_pair(row.connection, row.resource))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def revoke(request):
    """RFC 7009. Revoking either token disconnects the AI app; an unknown
    token is answered the same way, as the RFC asks."""
    if request.method == "OPTIONS":
        return _preflight()
    row = (AiAppToken.all_objects.select_related("connection")
           .filter(token_hash=digest(request.POST.get("token") or "")).first())
    if row is not None:
        client = AiAppClient.objects.filter(client_id=request.POST.get("client_id") or "").first()
        if client is None or client.pk == row.connection.client_id:
            revoke_connection(row.connection, reason="revoked by the AI app")
    return _json({})


# ------------------------------------------------------- the bearer, for MCP

def principal_for(access_token: str):
    """The connection an access token stands for, or None. Used by the MCP
    server's token verifier; refuses an expired token, a revoked connection,
    and a membership no longer what it was granted as."""
    row = (AiAppToken.all_objects
           .select_related("connection__membership__tenant", "connection__user",
                           "connection__client")
           .filter(token_hash=digest(access_token or ""), kind=AiAppToken.Kind.ACCESS).first())
    if row is None or row.expires_at < timezone.now():
        return None, None
    if not connection_usable(row.connection):
        return None, None
    return row.connection, row
