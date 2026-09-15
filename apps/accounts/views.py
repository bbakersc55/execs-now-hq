"""Auth surfaces: magic link request/consume, plus two small read endpoints."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
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


#: Roles whose screens may name the product. A client's never do.
STAFF_ROLES = ("FF", "CF", "VA")


def _branding_tenant(request):
    """Whose branding a surface wears.

    Signed in: that person's own practice. Otherwise the hostname decides —
    V1 gives each practice its own portal domain, and Beta's single tenant on
    app.getexecutivesnow.com is that same rule with one row.
    """
    from apps.tenancy.models import Tenant

    membership = getattr(request, "membership", None)
    if membership is not None:
        return membership.tenant
    tenants = list(Tenant.objects.all()[:2])
    return tenants[0] if len(tenants) == 1 else None


def tenant_branding(tenant):
    """Name, colours and logo for a page — the same values the email layout uses."""
    from apps.crm.services import email_layout

    brand = email_layout.branding(tenant) if tenant is not None else None
    return {
        "display_name": brand.display_name if brand else "",
        "header_color": brand.header_color if brand else email_layout.DEFAULT_HEADER_COLOR,
        "accent_color": brand.accent_color if brand else email_layout.DEFAULT_ACCENT_COLOR,
        "logo_url": ("/api/branding/logo"
                     if tenant is not None and tenant.email_logo_id else ""),
    }


def branding(request):
    """FR-0.6 / G5: one payload, so white-labelling is a data change.

    **White-label (owner ruling, 2026-09-15).** A client never sees the product.
    This returns the practice's own name, colours and logo; `product_name` is
    filled in only for signed-in staff, whose screens may name the product.
    """
    membership = getattr(request, "membership", None)
    staff = membership is not None and membership.role in STAFF_ROLES
    brand = tenant_branding(_branding_tenant(request))
    return JsonResponse({
        "display_name": brand["display_name"],
        "logo_url": brand["logo_url"],
        "palette": {
            "header": brand["header_color"],
            "accent": brand["accent_color"],
            "gray_dark": PALETTE["gray_dark"],
            "gray_light": PALETTE["gray_light"],
        },
        "product_name": PRODUCT_NAME if staff else None,
    })


def branding_logo(request):
    """The practice's logo, for the portal and the sign-in page.

    Always this request's own tenant — the logo is addressed by whose page it
    is, never by an id in the URL, so no practice can fetch another's.
    """
    from apps.tenancy import storage

    tenant = _branding_tenant(request)
    if tenant is None or not tenant.email_logo_id:
        raise Http404
    try:
        content = storage.read(tenant.email_logo)
    except storage.StorageError as exc:
        raise Http404 from exc
    return HttpResponse(content,
                        content_type=tenant.email_logo.content_type or "image/png")


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
        # FR-3.42 — while acting as, everything above describes the acted-as
        # user; this names both people, for the banner that never goes away.
        "acting": _acting(request),
    })


def _tenant_of(record):
    """The practice a sign-in link belongs to, so its page wears their brand."""
    from apps.tenancy.models import Membership

    if record is None:
        return None
    membership = Membership.all_objects.filter(
        user=record.user, revoked_at__isnull=True).select_related("tenant").first()
    return membership.tenant if membership else None


def _acting(request):
    from apps.tenancy.acting import describe

    target = getattr(request, "acting_as", None)
    if target is None:
        return None
    return describe(request.real_user, request.real_membership.role, target)


def login_refused(request):
    """C1 — where an uninvited Google account lands. No account was created.

    Anyone can reach this, a client included, so it wears the practice's name.
    """
    return render(request, "accounts/login_refused.html",
                  tenant_branding(_branding_tenant(request)), status=403)


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


MAGIC_LINK_REDACTED = "[one-time link — sent to the recipient only, not stored]"


def magic_link_subject(tenant):
    """A client signs in to their fractional's portal, not to our product: the
    practice's display name, never PRODUCT_NAME."""
    from apps.crm.services import email_layout

    return f"Sign in to {email_layout.branding(tenant).display_name}"


def magic_link_email(tenant, *, url):
    """`(html, text)` for a sign-in link. `url=None` is the stored copy, which
    never holds the link (assumption C3)."""
    from apps.crm.services import email_layout

    name = email_layout.branding(tenant).display_name
    return email_layout.action_link_email(
        tenant, subject=magic_link_subject(tenant), heading=magic_link_subject(tenant),
        paragraphs=[f"Use the button below to sign in to {name}. You'll see "
                    "your company's work, and nothing else."],
        button_label="Sign in", url=url,
        expiry="This link expires in 20 minutes and can be used once.",
        closing="If you didn't ask to sign in, you can ignore this email.",
        redacted_note=MAGIC_LINK_REDACTED,
    )


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
    stored_html, stored_text = magic_link_email(membership.tenant, url=None)
    html, text = magic_link_email(membership.tenant, url=url)

    try:
        # The requester is not signed in, so no tenant is bound (B1). Bind the
        # member's own, explicitly, as a background job would.
        with tenant_context(membership.tenant_id):
            outbox.create_message(
                tenant=membership.tenant, producer=OutboxMessage.Producer.MAGIC_LINK,
                to_address=membership.user.email, subject=magic_link_subject(membership.tenant),
                body_text=stored_text, body_html=stored_html,
                deliver_body_text=text, deliver_body_html=html,
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

    brand = tenant_branding(_tenant_of(record) or _branding_tenant(request))

    if request.method == "GET":
        return render(request, "accounts/magic_link.html",
                      {**brand, "valid": record is not None, "token": token})

    if record is None:
        return render(request, "accounts/magic_link.html",
                      {**brand, "valid": False, "token": token}, status=400)

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

    # Same landing as Google sign-in. A bare "/" is Django's own root, which
    # serves nothing in development (the app is on the Vite port), so every
    # portal grant and self-serve link — neither sets `redirect_to` — ended on
    # a 404 after a successful sign-in.
    redirect_to = record.redirect_to or settings.LOGIN_REDIRECT_URL
    # The landing page is a plain HTML form, so a browser posting it expects a
    # page, not JSON: it used to show {"ok": true, ...} and stop there.
    # Callers that ask for JSON (or send no Accept header) still get it.
    if "text/html" in request.headers.get("Accept", ""):
        return HttpResponseRedirect(redirect_to)
    return JsonResponse({"ok": True, "redirect_to": redirect_to})
