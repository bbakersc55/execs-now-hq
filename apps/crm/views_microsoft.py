"""Microsoft 365 connect, and the switch between it and Gmail
(docs/m365_transport.md).

The twin of `views_gmail`: status, consent, verify, disconnect, the practice
address, and the browser-redirect callback. Same rule on who (H7): the
practice owner and associates each connect **their own** work account; an
assistant has no control here. Every query is scoped by the fail-closed tenant
manager and then by `user=request.user`.

**One transport at a time** (D6). `MailProviderView` says which, and the
practice owner switches it. Switching deletes nothing: the other provider's
connections stay, so switching back needs no reconnect, but nothing sends or
reads through them while they are not the practice's.
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
from apps.crm.models import MicrosoftConnection
from apps.crm.services import graph, microsoft_oauth, outbox, secrets, transport
from apps.tenancy.models import AuditEvent, SecretKind, Tenant

PROVIDERS = dict(Tenant.MailProvider.choices)
ACTING = "While acting as someone, their mail connection isn't yours to change."


def _acting() -> bool:
    from apps.tenancy.context import get_acting

    return get_acting() is not None


def _demo_refusal(tenant) -> str:
    """The demo sends through its one Gmail connection, and a visitor's copy
    through that same one: neither becomes a Microsoft practice."""
    from apps.tenancy.demo import visitors
    from config import environment

    if visitors.is_copy(tenant):
        return visitors.NO_CONNECTIONS
    if environment.is_demo():
        return ("This is the demo. It sends through its own Gmail connection only, so "
                "Microsoft 365 can be seen here but not connected.")
    return ""


def _spa_url(where="email", **params):
    root = dj_settings.APP_ROOT_URL.rstrip("/")
    path = "/meetings" if where == "meetings" else "/settings/email"
    return f"{root}{path}" + (f"?{urlencode(params)}" if params else "")


def consent_url(request, *, inbound=False, files=False, where="email") -> str:
    """Start a consent: remember what was asked and where to come back to.
    Shared by Settings → Email and the meeting queue's "Allow OneDrive
    access" (`meetings.views`), which asks for collecting replies too when the
    connection already holds it, so allowing OneDrive does not drop it."""
    state = microsoft_oauth.new_state()
    request.session[microsoft_oauth.STATE_SESSION_KEY] = state
    request.session[microsoft_oauth.INBOUND_SESSION_KEY] = inbound
    request.session[microsoft_oauth.FILES_SESSION_KEY] = files
    request.session[microsoft_oauth.RETURN_SESSION_KEY] = where
    from apps.crm.services import gmail_oauth

    request.session.pop(gmail_oauth.MAILBOX_SESSION_KEY, None)
    return microsoft_oauth.authorization_url(state, login_hint=request.user.email,
                                             inbound=inbound, files=files)


def _my_connection(request):
    return MicrosoftConnection.objects.filter(user=request.user).first()


def _practice_sending(tenant):
    try:
        connection = graph.sending_connection_for(tenant)
    except transport.TransportUnavailable as exc:
        return {"ok": False, "detail": str(exc), "account": ""}
    return {"ok": True, "detail": "", "account": connection.email_address}


def _status_payload(request, **extra):
    tenant = request.tenant
    connection = _my_connection(request)
    practice_sending = _practice_sending(tenant)
    base = {
        "provider": tenant.mail_provider,
        "alias": tenant.from_address,
        "practice_sending": practice_sending,
        "configured": microsoft_oauth.is_configured(),
        "refusal": _demo_refusal(tenant),
        "is_local_build": dj_settings.IS_LOCAL,
    }
    if connection is None:
        return {**base, "connected": False, "email_address": "", "scopes": [],
                "connected_at": None, "reads_mail": False, "alias_verified": False,
                "alias_verified_at": None, "send_as_error": "",
                "is_sending_connection": False, **extra}
    return {
        **base,
        "connected": True,
        "email_address": connection.email_address,
        "scopes": connection.scopes or [],
        "connected_at": connection.created_at,
        "reads_mail": microsoft_oauth.inbound_granted(connection.scopes or []),
        "alias_verified": connection.send_as_verified_at is not None,
        "alias_verified_at": connection.send_as_verified_at,
        "send_as_error": connection.send_as_error,
        "is_sending_connection": (connection.send_as_verified_at is not None
                                  and practice_sending["account"] == connection.email_address),
        **extra,
    }


def _check(request, connection):
    """The practice-address check, as a response: refusals are said on the
    screen with the status, never as a 500."""
    try:
        graph.verify_send_as(connection, request.tenant.from_address)
    except transport.TransportUnavailable as exc:
        connection.refresh_from_db()
        return Response(_status_payload(request, verify_error=str(exc)))
    AuditEvent.all_objects.create(
        tenant=request.tenant, actor=request.user, verb="microsoft.alias_verified",
        target_type="microsoft_connection", target_id=connection.pk,
        payload={"alias": request.tenant.from_address},
    )
    connection.refresh_from_db()
    return Response(_status_payload(request))


class MailProviderView(viewsets.ViewSet):
    """Which transport carries the practice's mail. Everyone who reaches
    Settings → Email sees it; the practice owner switches it."""

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.CanConnectMailbox]

    def _payload(self, request):
        from apps.crm.services import gmail_oauth

        tenant = request.tenant
        return {
            "provider": tenant.mail_provider,
            "label": PROVIDERS.get(tenant.mail_provider, tenant.mail_provider),
            "choices": [{"value": v, "label": label} for v, label in PROVIDERS.items()],
            "can_switch": request.membership.role == "FF" and not _demo_refusal(tenant),
            "refusal": _demo_refusal(tenant),
            "google_configured": gmail_oauth.is_configured(tenant),
            "microsoft_configured": microsoft_oauth.is_configured(),
        }

    def list(self, request):
        return Response(self._payload(request))

    @action(detail=False, methods=["post"],
            permission_classes=[crm_perms.IsTenantStaff, crm_perms.IsFF])
    def switch(self, request):
        tenant = request.tenant
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _demo_refusal(tenant):
            return Response({"detail": refusal}, status=409)
        wanted = str(request.data.get("provider") or "")
        if wanted not in PROVIDERS:
            return Response({"provider": "Choose Gmail or Microsoft 365."}, status=400)
        previous = tenant.mail_provider
        if wanted != previous and (waiting := outbox.switch_refusal(tenant)):
            return Response({"detail": waiting}, status=409)
        if wanted != previous:
            tenant.mail_provider = wanted
            tenant.save(update_fields=["mail_provider", "updated_at"])
            AuditEvent.all_objects.create(
                tenant=tenant, actor=request.user, verb="practice.mail_provider_changed",
                target_type="tenant", target_id=tenant.pk,
                payload={"from": previous, "to": wanted},
            )
        return Response(self._payload(request))


class MicrosoftConnectionViewSet(viewsets.ViewSet):
    """The practice owner and associates, each for their own account (H7)."""

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.CanConnectMailbox]

    def list(self, request):
        return Response(_status_payload(request))

    @action(detail=False, methods=["post"])
    def start(self, request):
        """The consent URL. The browser navigates; we never proxy it."""
        tenant = request.tenant
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _demo_refusal(tenant):
            return Response({"detail": refusal}, status=409)
        if not transport.is_microsoft(tenant):
            return Response({"detail": (
                "This practice's mail goes through Gmail. The practice owner switches it "
                "to Microsoft 365 first, above.")}, status=409)
        if not microsoft_oauth.is_configured():
            return Response({"detail": (
                "Microsoft 365 isn't set up on this server yet, so there is nothing to "
                "connect to. Contact support.")}, status=400)
        mine = _my_connection(request)
        return Response({
            # A ticked box asks for it, an unticked one leaves it out; OneDrive,
            # granted from the meeting queue, is kept either way.
            "authorization_url": consent_url(
                request, inbound=bool(request.data.get("inbound")),
                files=bool(mine and microsoft_oauth.files_granted(mine.scopes or []))),
            "redirect_uri": microsoft_oauth.redirect_uri(),
        })

    @action(detail=False, methods=["post"])
    def verify(self, request):
        """Check the practice address again, by a test send (D3)."""
        if _acting():
            return Response({"detail": ACTING}, status=403)
        connection = _my_connection(request)
        if connection is None:
            return Response({"detail": "No Microsoft 365 account is connected."}, status=400)
        return _check(request, connection)

    @action(detail=False, methods=["post"], url_path="practice-address",
            permission_classes=[crm_perms.IsTenantStaff, crm_perms.IsFF])
    def practice_address(self, request):
        """The practice address, chosen as on Gmail's screen (beta feedback,
        2026-10-05), and checked again through Microsoft 365."""
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        tenant = request.tenant
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _demo_refusal(tenant):
            return Response({"detail": refusal}, status=409)
        address = str(request.data.get("address") or "").strip().lower()
        try:
            validate_email(address)
        except ValidationError:
            return Response({"address": "Enter an email address, like info@yourpractice.com."},
                            status=400)
        previous = tenant.from_address
        changed = address != previous.lower()
        if changed:
            tenant.from_address = address
            tenant.save(update_fields=["from_address", "updated_at"])
            AuditEvent.all_objects.create(
                tenant=tenant, actor=request.user, verb="practice.address_changed",
                target_type="tenant", target_id=tenant.pk,
                payload={"from": previous, "to": address},
            )
        connection = _my_connection(request)
        if connection is None:
            return Response(_status_payload(request))
        if changed:
            connection.send_as_verified_at = None
            connection.send_as_error = ""
            connection.save(update_fields=["send_as_verified_at", "send_as_error", "updated_at"])
        return _check(request, connection)

    @action(detail=False, methods=["post"])
    def disconnect(self, request):
        """The stored refresh token goes with the row."""
        if _acting():
            return Response({"detail": ACTING}, status=403)
        connection = _my_connection(request)
        if connection is None:
            return Response({"detail": "No Microsoft 365 account is connected."}, status=400)
        email_address = connection.email_address
        from apps.crm.services import mailboxes

        mailboxes.disconnected_own(connection)
        if connection.secret_id:
            connection.secret.delete()
        connection.delete()
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="microsoft.disconnected",
            target_type="microsoft_connection", target_id=None,
            payload={"email_address": email_address},
        )
        return Response(_status_payload(request))


def _consent_refusal(request) -> str:
    """Microsoft's own words when consent did not happen, with the admin link
    when the directory needs its administrator to approve the app."""
    error = request.GET.get("error", "")
    said = (request.GET.get("error_description") or "").split("\r\n")[0].split("\n")[0]
    text = f"Microsoft reported: {said or error}. Nothing was stored."
    needs_admin = ("admin" in said.lower() or "AADSTS65001" in said
                   or "AADSTS90094" in said or error == "consent_required")
    if needs_admin:
        text += (" Your Microsoft 365 administrator approves the app once, at "
                 f"{microsoft_oauth.admin_consent_url()} , then connect again.")
    return text


@require_http_methods(["GET"])
def microsoft_callback(request):
    """Microsoft's redirect target. Ends in the SPA, never in JSON.

    Three consents share it: connecting mail (Settings → Email), allowing
    OneDrive (the meeting queue) and signing in, which is handed on by its
    state to `apps.accounts.microsoft_signin`."""
    from apps.accounts import microsoft_signin

    from apps.calendars import views as calendar_views

    if microsoft_signin.is_sign_in(request):
        return microsoft_signin.callback(request)
    if calendar_views.is_calendar_consent(request):
        return calendar_views.callback(request)
    inbound_wanted = bool(request.session.pop(microsoft_oauth.INBOUND_SESSION_KEY, False))
    files_wanted = bool(request.session.pop(microsoft_oauth.FILES_SESSION_KEY, False))
    where = request.session.pop(microsoft_oauth.RETURN_SESSION_KEY, "email")
    from apps.crm.services import gmail_oauth

    mailbox_spec = request.session.pop(gmail_oauth.MAILBOX_SESSION_KEY, None)
    error_key = "drive_error" if where == "meetings" else "ms_error"

    def refused(text):
        return HttpResponseRedirect(_spa_url(where, **{error_key: text}))

    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in ("FF", "CF"):
        return refused("You are not signed in as the practice owner or an associate, so "
                       "this connection was not stored.")

    expected = request.session.pop(microsoft_oauth.STATE_SESSION_KEY, None)
    supplied = request.GET.get("state")
    if not expected or not supplied or expected != supplied:
        return refused("That consent did not match the request this browser started. "
                       "Nothing was stored. Start again.")
    if request.GET.get("error"):
        return refused(_consent_refusal(request))
    tenant = membership.tenant
    if refusal := _demo_refusal(tenant):
        return refused(refusal)
    code = request.GET.get("code", "")
    if not code:
        return refused("Microsoft returned no authorization code. Nothing was stored.")

    try:
        tokens = microsoft_oauth.exchange_code(code, inbound=inbound_wanted,
                                               files=files_wanted)
        missing = microsoft_oauth.missing_scopes(tokens)
        if missing:
            return refused(f"Consent was granted without {', '.join(missing)}. Nothing was "
                           "stored. Connect again and accept every permission.")
        email_address = microsoft_oauth.account(tokens["access_token"])
    except microsoft_oauth.MicrosoftOAuthError as exc:
        return refused(str(exc))

    claims = microsoft_oauth.id_claims(tokens)
    if mailbox_spec:
        # A shared or a client's mailbox, on its own row (2026-10-28).
        from apps.crm.views_mail import connected_mailbox

        return HttpResponseRedirect(_spa_url(**connected_mailbox(
            request, mailbox_spec, provider="microsoft", email_address=email_address,
            refresh_token=tokens["refresh_token"],
            scopes=microsoft_oauth.granted_scopes(tokens),
            reads=microsoft_oauth.inbound_granted(tokens),
            directory_id=str(claims.get("tid") or ""))))
    before = MicrosoftConnection.all_objects.filter(tenant=tenant, user=request.user).first()
    # Adding OneDrive to the same account and address changes nothing about
    # sending, so a check already passed stands; anything else earns it again,
    # as Gmail's reconnect does.
    keeps_check = (where == "meetings" and before is not None
                   and before.email_address.lower() == email_address.lower()
                   and before.send_as_verified_at is not None
                   and before.send_as_address.lower() == tenant.from_address.lower())
    secret = secrets.write_secret(tenant=tenant, kind=SecretKind.MICROSOFT_REFRESH,
                                  value=tokens["refresh_token"], user=request.user)
    connection, _ = MicrosoftConnection.all_objects.update_or_create(
        tenant=tenant, user=request.user,
        defaults={
            "email_address": email_address,
            "directory_id": str(claims.get("tid") or "")[:64],
            "scopes": microsoft_oauth.granted_scopes(tokens),
            "secret": secret,
            **({} if keeps_check else {"send_as_verified_at": None, "send_as_error": ""}),
        },
    )
    AuditEvent.all_objects.create(
        tenant=tenant, actor=request.user, verb="microsoft.connected",
        target_type="microsoft_connection", target_id=connection.pk,
        payload={"email_address": email_address,
                 **({"files": True} if files_wanted else {})},
    )

    warning = ""
    if not keeps_check:
        try:
            graph.verify_send_as(connection, tenant.from_address)
        except transport.TransportUnavailable as exc:
            warning = str(exc)
    if where == "meetings":
        if files_wanted and not microsoft_oauth.files_granted(tokens):
            return refused("Consent was granted without access to your files, so the notes "
                           "folder cannot be read. Sending mail still works. Allow OneDrive "
                           "access again and accept every permission.")
        params = {"drive_connected": email_address}
        if warning:
            params["drive_warning"] = warning
        return HttpResponseRedirect(_spa_url("meetings", **params))
    if inbound_wanted and not microsoft_oauth.inbound_granted(tokens):
        warning = " ".join(filter(None, [warning, (
            "Consent was granted without permission to read mail, so replies cannot be "
            "collected. Sending still works.")]))
    params = {"ms_connected": email_address}
    if warning:
        params["ms_warning"] = warning
    return HttpResponseRedirect(_spa_url(**params))
