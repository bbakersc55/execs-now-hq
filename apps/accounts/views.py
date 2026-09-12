"""Auth surfaces: magic link request/consume, plus two small read endpoints."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from config.branding import PALETTE, PRODUCT_NAME

from .models import MagicLinkToken
from .ratelimit import RateLimit, too_many

# C3.4 — 5/hour per email, 20/hour per IP.
_EMAIL_LIMIT = RateLimit(limit=5, window_seconds=3600, prefix="magic-email")
_IP_LIMIT = RateLimit(limit=20, window_seconds=3600, prefix="magic-ip")

# C3.4 — the same response either way, so this cannot enumerate client users.
_OPAQUE = {"detail": "If that address has access, we've sent a link."}


def branding(request):
    """FR-0.6 / G5: one payload, so V1 white-labelling is a data change."""
    return JsonResponse({"product_name": PRODUCT_NAME, "palette": PALETTE})


def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    membership = getattr(request, "membership", None)
    return JsonResponse({
        "authenticated": True,
        "email": request.user.email,
        "full_name": request.user.full_name,
        "role": membership.role if membership else None,
        "tenant": str(membership.tenant_id) if membership else None,
        "client_company": (
            str(membership.client_company_id)
            if membership and membership.client_company_id else None
        ),
        # Whether this build offers the development-only controls (the digest
        # "Generate now", for instance). False anywhere that is not localhost,
        # so the control cannot appear in front of a client.
        "dev_tools": settings.IS_LOCAL,
    })


def login_refused(request):
    """C1 — where an uninvited Google account lands. No account was created."""
    return render(request, "accounts/login_refused.html", {
        "product_name": PRODUCT_NAME,
    }, status=403)


@csrf_protect
@require_http_methods(["POST"])
def request_magic_link(request):
    email = (request.POST.get("email") or "").strip().lower()
    ip = request.META.get("REMOTE_ADDR")

    if too_many(_IP_LIMIT, ip) or too_many(_EMAIL_LIMIT, email):
        return JsonResponse(_OPAQUE, status=429)

    from apps.tenancy.models import Membership

    membership = (
        Membership.all_objects.select_related("user", "tenant")
        .filter(user__email__iexact=email, revoked_at__isnull=True)
        .first()
    )
    if membership is not None and membership.user.is_active:
        token, raw = MagicLinkToken.issue(
            tenant=membership.tenant, user=membership.user, requested_ip=ip,
        )
        _send_magic_link(membership, raw)

    # Constant response whether or not the address exists.
    return JsonResponse(_OPAQUE)


def _send_magic_link(membership, raw_token):
    """Sent synchronously, not queued (assumption A2a).

    With one ORM-backed queue and no priority lanes, an enqueued magic link
    could sit behind a 40-minute transcription — a sign-in that looks broken.

    A direct-to-sent Outbox producer (FR-1.15b) through the configured
    transport, like every other app email. The link is delivered but never
    stored: the Outbox row is visible to tenant staff, and a stored link would
    let any of them sign in as the client (assumption C3).

    A send failure does NOT change the response: the request endpoint answers
    identically whether or not the address exists, and an error only for real
    addresses would undo that. The failure is audited for the FF instead.
    """
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.crm.services.transport import TransportUnavailable
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import AuditEvent

    url = f"{settings.PUBLIC_BASE_URL}/auth/magic/{raw_token}"

    def body(link):
        return (f"Click to sign in to {PRODUCT_NAME}:\n\n{link}\n\n"
                "This link expires in 20 minutes and can be used once.")

    try:
        # The requester is not signed in, so no tenant is bound (B1). Bind the
        # member's own, explicitly, as a background job would.
        with tenant_context(membership.tenant_id):
            outbox.create_message(
                tenant=membership.tenant, producer=OutboxMessage.Producer.MAGIC_LINK,
                to_address=membership.user.email, subject=f"Sign in to {PRODUCT_NAME}",
                body_text=body("[one-time link — sent to the recipient only, not stored]"),
                deliver_body_text=body(url),
            )
    except TransportUnavailable as exc:
        AuditEvent.all_objects.create(
            tenant=membership.tenant, verb="email.failed", target_type="user",
            target_id=membership.user_id,
            payload={"producer": "magic_link", "to": membership.user.email,
                     "reason": str(exc)[:500]},
        )


@require_http_methods(["GET", "POST"])
def magic_link_landing(request, token: str):
    """C3.3 — GET renders a button; only POST consumes the token.

    Corporate mail scanners and link-preview bots follow GET links and would
    otherwise burn the token before the client ever clicks it.
    """
    record = MagicLinkToken.resolve(token)

    if request.method == "GET":
        return render(request, "accounts/magic_link.html", {
            "product_name": PRODUCT_NAME,
            "valid": record is not None,
            "token": token,
        })

    if record is None:
        return render(request, "accounts/magic_link.html", {
            "product_name": PRODUCT_NAME, "valid": False, "token": token,
        }, status=400)

    record.consume()
    user = record.user
    user.last_login_at = timezone.now()
    user.save(update_fields=["last_login_at", "updated_at"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    membership = user.membership
    if membership and membership.is_client_user:
        # C3.5 — client users get a 30-day rolling session so they are not
        # re-requesting a link every week.
        request.session.set_expiry(settings.CLIENT_SESSION_AGE)

    redirect_to = record.redirect_to or "/"
    # The landing page is a plain HTML form, so a browser posting it expects a
    # page, not JSON: it used to show {"ok": true, ...} and stop there.
    # Callers that ask for JSON (or send no Accept header) still get it.
    if "text/html" in request.headers.get("Accept", ""):
        return HttpResponseRedirect(redirect_to)
    return JsonResponse({"ok": True, "redirect_to": redirect_to})
