"""Tier 1 Gmail connect — status, consent, verify, disconnect.

Split out of `views.py` because the OAuth callback is not a DRF endpoint:
Google redirects the **browser** to it, so it is a plain Django view that ends
in a redirect back into the SPA, not a JSON response.

Scope of what a role may do here (`03_access_matrix.md`, assumption H7):
FF and CF each connect **their own** mailbox; a VA has no control at all. Every
query is filtered by `user=request.user` on top of the fail-closed tenant
manager, so "my connection" cannot resolve to a colleague's — or to another
tenant's — row.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings as dj_settings
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import GmailConnection
from apps.crm.services import gmail_oauth, secrets, transport
from apps.tenancy.models import AuditEvent, SecretKind

TRANSPORT_LABELS = {
    "gmail": "Your connected Gmail, sending as the practice alias",
    "postmark": "Postmark (a V1 option — not configured in Beta)",
}


def _spa_url(**params):
    root = dj_settings.APP_ROOT_URL.rstrip("/")
    query = f"?{urlencode(params)}" if params else ""
    return f"{root}/settings/email{query}"


def _my_connection(request):
    """Scoped twice: fail-closed tenant manager, then this user."""
    return GmailConnection.objects.filter(user=request.user).first()


def _practice_sending_state(tenant):
    """Whether the practice can send at all — the thing a CF cannot fix but
    should still be able to see, because a broken FF token stops *their* mail
    too (and every client magic link with it)."""
    try:
        connection = transport.sending_connection_for(tenant)
    except transport.TransportUnavailable as exc:
        return {"ok": False, "detail": str(exc), "account": ""}
    return {"ok": True, "detail": "", "account": connection.email_address}


def _status_payload(request, *, send_as=None, send_as_error=""):
    tenant = request.tenant
    connection = _my_connection(request)
    alias = tenant.from_address

    if connection is None:
        return {
            "connected": False,
            "email_address": "",
            "scopes": [],
            "connected_at": None,
            "tier2_enabled": False,
            "alias": alias,
            "alias_verified": False,
            "alias_verified_at": None,
            "alias_listed": False,
            "send_as": [],
            "send_as_error": "",
            "is_sending_connection": False,
            "transport": dj_settings.APP_MAIL_TRANSPORT,
            "transport_label": TRANSPORT_LABELS.get(
                dj_settings.APP_MAIL_TRANSPORT, dj_settings.APP_MAIL_TRANSPORT
            ),
            "practice_sending": _practice_sending_state(tenant),
            "oauth_configured": gmail_oauth.is_configured(),
            # FR-0.7 — gates the dev-only allow-list section in the UI.
            "is_local_build": dj_settings.IS_LOCAL,
        }

    if send_as is None:
        try:
            send_as = transport.list_send_as(connection)
        except transport.TransportUnavailable as exc:
            # A dead token must not 500 the settings page — that page is where
            # you go to fix it.
            send_as, send_as_error = [], str(exc)

    listed = {e["address"].lower() for e in send_as}
    return {
        "connected": True,
        "email_address": connection.email_address,
        "scopes": connection.scopes or [],
        "connected_at": connection.created_at,
        "tier2_enabled": connection.tier2_enabled,
        "alias": alias,
        "alias_verified": connection.send_as_verified_at is not None,
        "alias_verified_at": connection.send_as_verified_at,
        "alias_listed": alias.lower() in listed,
        "send_as": [dict(e, is_alias=e["address"].lower() == alias.lower()) for e in send_as],
        "send_as_error": send_as_error or connection.send_as_error,
        "is_sending_connection": (
            connection.send_as_verified_at is not None
            and _practice_sending_state(tenant).get("account") == connection.email_address
        ),
        "transport": dj_settings.APP_MAIL_TRANSPORT,
        "transport_label": TRANSPORT_LABELS.get(
            dj_settings.APP_MAIL_TRANSPORT, dj_settings.APP_MAIL_TRANSPORT
        ),
        "practice_sending": _practice_sending_state(tenant),
        "oauth_configured": gmail_oauth.is_configured(),
        "is_local_build": dj_settings.IS_LOCAL,
    }


class GmailConnectionViewSet(viewsets.ViewSet):
    """FR-6.3b. FF and CF, each for their own account only (H7)."""

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.CanConnectMailbox]

    def list(self, request):
        return Response(_status_payload(request))

    @action(detail=False, methods=["post"])
    def start(self, request):
        """Hand back the consent URL. The browser navigates; we never proxy it."""
        if not gmail_oauth.is_configured():
            return Response({"detail": (
                "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set, "
                "so there is nothing to connect to. See docs/05_dev_environment.md §5a."
            )}, status=400)
        state = gmail_oauth.new_state()
        request.session[gmail_oauth.STATE_SESSION_KEY] = state
        email = request.user.email
        return Response({
            "authorization_url": gmail_oauth.authorization_url(
                state, login_hint=email, hd=gmail_oauth.workspace_domain(email),
            ),
            "redirect_uri": gmail_oauth.redirect_uri(),
        })

    @action(detail=False, methods=["post"])
    def verify(self, request):
        """Re-check the alias against Gmail's live send-as list."""
        connection = _my_connection(request)
        if connection is None:
            return Response({"detail": "No Gmail account is connected."}, status=400)
        try:
            transport.verify_send_as(connection, request.tenant.from_address)
        except transport.TransportUnavailable as exc:
            connection.refresh_from_db()
            return Response(dict(_status_payload(request), verify_error=str(exc)), status=200)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="gmail.alias_verified",
            target_type="gmail_connection", target_id=connection.pk,
            payload={"alias": request.tenant.from_address},
        )
        connection.refresh_from_db()
        return Response(_status_payload(request))

    @action(detail=False, methods=["post"])
    def disconnect(self, request):
        """Deletes the stored refresh token with the row — same cascade
        `remove_member` applies, for the same reason."""
        connection = _my_connection(request)
        if connection is None:
            return Response({"detail": "No Gmail account is connected."}, status=400)
        email_address = connection.email_address
        if connection.secret_id:
            connection.secret.delete()
        connection.delete()
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="gmail.disconnected",
            target_type="gmail_connection", target_id=None,
            payload={"email_address": email_address},
        )
        return Response(_status_payload(request))


@require_http_methods(["GET"])
def gmail_callback(request):
    """Google's redirect target. Ends in the SPA, never in JSON."""
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in ("FF", "CF"):
        # Covers signed-out (session expired mid-consent) and the H7 boundary.
        return HttpResponseRedirect(_spa_url(gmail_error=(
            "You are not signed in as a fractional, so this connection was not stored."
        )))

    expected = request.session.pop(gmail_oauth.STATE_SESSION_KEY, None)
    supplied = request.GET.get("state")
    if not expected or not supplied or expected != supplied:
        return HttpResponseRedirect(_spa_url(gmail_error=(
            "That consent did not match the request this browser started. "
            "Nothing was stored — click Connect Gmail again."
        )))

    if request.GET.get("error"):
        return HttpResponseRedirect(_spa_url(gmail_error=(
            f"Google reported: {request.GET['error']}. Nothing was stored."
        )))

    code = request.GET.get("code", "")
    if not code:
        return HttpResponseRedirect(_spa_url(
            gmail_error="Google returned no authorisation code. Nothing was stored."
        ))

    try:
        tokens = gmail_oauth.exchange_code(code)
        missing = gmail_oauth.missing_scopes(tokens)
        if missing:
            return HttpResponseRedirect(_spa_url(gmail_error=(
                "Consent was granted without "
                f"{', '.join(s.rsplit('/', 1)[-1] for s in missing)}. "
                "Nothing was stored — connect again and leave every box ticked."
            )))
        email_address = gmail_oauth.account_email(tokens["access_token"])
    except gmail_oauth.GmailOAuthError as exc:
        return HttpResponseRedirect(_spa_url(gmail_error=str(exc)))

    tenant = membership.tenant
    secret = secrets.write_secret(
        tenant=tenant, kind=SecretKind.GMAIL_REFRESH,
        value=tokens["refresh_token"], user=request.user,
    )
    connection, _ = GmailConnection.all_objects.update_or_create(
        tenant=tenant, user=request.user,
        defaults={
            "email_address": email_address,
            "scopes": gmail_oauth.granted_scopes(tokens),
            "secret": secret,
            # A reconnect re-earns verification; it does not inherit it. The
            # alias could have been removed in Gmail since the last connect.
            "send_as_verified_at": None,
            "send_as_error": "",
        },
    )
    AuditEvent.all_objects.create(
        tenant=tenant, actor=request.user, verb="gmail.connected",
        target_type="gmail_connection", target_id=connection.pk,
        payload={"email_address": email_address},
    )

    # Verify the alias immediately: connecting and *then* discovering the alias
    # is missing is the same two-step the owner already has to do in Gmail.
    try:
        transport.verify_send_as(connection, tenant.from_address)
    except transport.TransportUnavailable as exc:
        return HttpResponseRedirect(_spa_url(gmail_connected=email_address,
                                             gmail_warning=str(exc)))
    return HttpResponseRedirect(_spa_url(gmail_connected=email_address))
