"""Auth surfaces: magic link request/consume, plus two small read endpoints."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from config.branding import PALETTE, PRODUCT_NAME

from apps.tenancy.roles import role_label
from .models import SIGN_IN_PURPOSES, MagicLinkPurpose, MagicLinkToken
from .ratelimit import RateLimit, too_many

# C3.4 — 5/hour per email, 20/hour per IP.
_EMAIL_LIMIT = RateLimit(limit=5, window_seconds=3600, prefix="magic-email")
_IP_LIMIT = RateLimit(limit=20, window_seconds=3600, prefix="magic-ip")

# C3.4 — the same response either way, so this cannot enumerate client users.
_OPAQUE = {"detail": "If that address has access, we've sent a link."}


#: Roles whose screens may name the product. A client's never do.
STAFF_ROLES = ("FF", "CF", "VA")


def _branding_tenant(request):
    """Whose branding a surface wears (P2, owner 2026-10-02).

    - Signed in: that person's own practice.
    - The Practices area: none.
    - Signed out: **only a practice an emailed link names.** The app's token
      pages pass their token as `?via=<kind>:<token>` (cadence, pre-call,
      unsubscribe); the token resolves to its practice, exactly as the page's
      own endpoint does. Nothing else names one: the client sign-in page needs
      no practice, because the email entered finds it. *(Until P2 a signed-out
      visitor got "the one practice", which a second practice would break.)*
    """
    if getattr(request, "area", None) == "platform":
        return None
    membership = getattr(request, "membership", None)
    if membership is not None:
        return membership.tenant
    return tenant_from_link(request.GET.get("via", ""))


def tenant_from_link(via: str):
    """The practice an emailed link names, or None. `via` is `<kind>:<token>`."""
    kind, _, token = (via or "").partition(":")
    if not token:
        return None
    if kind == "cadence":
        from apps.work.models import StakeholderToken

        record = StakeholderToken.resolve(token)
        return record.tenant if record else None
    if kind == "precall":
        from apps.strategy.services import session_for_precall_token

        session = session_for_precall_token(token)
        return session.tenant if session else None
    if kind == "unsubscribe":
        from apps.crm.services import unsubscribe
        from apps.tenancy.models import Tenant

        data = unsubscribe.read_token(token)
        return Tenant.objects.filter(pk=data["t"]).first() if data else None
    return None


def _logo_is_there(tenant) -> bool:
    """Whether the logo's file can actually be served. The row can exist and
    the file not: a laptop's copy of production has the row and no bucket."""
    from apps.tenancy import storage

    try:
        return storage.exists(tenant.email_logo)
    except storage.StorageError:
        return False


def tenant_branding(tenant, *, via: str = "", check_logo: bool = False):
    """Name, colours and logo for a page — the same values the email layout uses.

    `check_logo` is for a page Django renders itself (sign-in link, refusal):
    with no script to catch a failed image, it asks storage first and shows the
    practice's name as text when the file is not there. The app's own screens
    do that in the browser instead, so every page load is not a storage call.
    """
    from apps.crm.services import email_layout
    from apps.tenancy import contrast

    brand = email_layout.branding(tenant) if tenant is not None else None
    has_logo = tenant is not None and bool(tenant.email_logo_id) and (
        not check_logo or _logo_is_there(tenant))
    return {
        "display_name": brand.display_name if brand else "",
        "header_color": brand.header_color if brand else email_layout.DEFAULT_HEADER_COLOR,
        "accent_color": brand.accent_color if brand else email_layout.DEFAULT_ACCENT_COLOR,
        "on_accent_color": contrast.text_on(
            brand.accent_color if brand else email_layout.DEFAULT_ACCENT_COLOR),
        "logo_url": "/api/branding/logo" + _via_query(via) if has_logo else "",
        # Always an image when the practice is known: its own mark, or its
        # initials on gray (P1, D2). Never the product's mark.
        "mark_url": "/api/branding/mark" + _via_query(via) if tenant is not None else "",
        "footer_text": getattr(tenant, "brand_footer_text", "") if tenant is not None else "",
    }


def _via_query(via: str) -> str:
    from urllib.parse import quote

    return f"?via={quote(via, safe=':')}" if via else ""


# The signed-out screen's first call, so it also sets the CSRF cookie the
# client sign-in form needs (2026-09-30: the form did not exist, and a signed-
# out visitor had no cookie to post it with).
@ensure_csrf_cookie
def branding(request):
    """FR-0.6 / G5: one payload, so white-labelling is a data change.

    **White-label (owner ruling, 2026-09-15).** A client never sees the product.
    This returns the practice's own name, colours and logo; `product_name` is
    filled in only for signed-in staff, whose screens may name the product.
    """
    membership = getattr(request, "membership", None)
    from apps.tenancy import contrast

    # The Practices area is a staff screen with no practice bound (P2).
    platform = getattr(request, "area", None) == "platform"
    staff = platform or (membership is not None and membership.role in STAFF_ROLES)
    brand = tenant_branding(_branding_tenant(request), via=request.GET.get("via", ""))
    return JsonResponse({
        "display_name": brand["display_name"],
        "logo_url": brand["logo_url"],
        "mark_url": brand["mark_url"],
        "footer_text": brand["footer_text"],
        "palette": {
            "header": brand["header_color"],
            "accent": brand["accent_color"],
            # Text placed on each fill: white or near-black, whichever reads.
            "on_header": contrast.text_on(brand["header_color"]),
            "on_accent": contrast.text_on(brand["accent_color"]),
            "gray_dark": PALETTE["gray_dark"],
            "gray_light": PALETTE["gray_light"],
        },
        "product_name": PRODUCT_NAME if staff else None,
    })


def branding_mark(request):
    """The practice's mark: its uploaded PNG, or its initials on gray (D2).

    Like the logo, addressed by whose page it is and never by an id, so no
    practice can fetch another's. Used as the client portal's favicon.
    """
    from apps.tenancy import branding as practice_branding
    from apps.tenancy import storage

    tenant = _branding_tenant(request)
    if tenant is None:
        raise Http404
    if tenant.email_mark_id:
        try:
            content = storage.read(tenant.email_mark)
        except storage.StorageError:
            content = None
        if content:
            return HttpResponse(content, content_type=tenant.email_mark.content_type or "image/png")
    name = tenant.email_display_name or tenant.name
    return HttpResponse(practice_branding.initials_svg(name), content_type="image/svg+xml")


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


def _agreement_required(request) -> bool:
    from apps.platform import agreement

    return agreement.required(request)


def _home_practice(user) -> str | None:
    from apps.crm.services import email_layout
    from apps.tenancy.models import Membership

    membership = (Membership.all_objects.select_related("tenant")
                  .filter(user=user, revoked_at__isnull=True).first())
    return email_layout.branding(membership.tenant).display_name if membership else None


def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    membership = getattr(request, "membership", None)
    return JsonResponse({
        "authenticated": True,
        "email": request.user.email,
        "full_name": request.user.full_name,
        "role": membership.role if membership else None,
        "role_label": role_label(membership.role) if membership else None,
        # P2: the Practices area switch. `area` is "platform" only for the
        # platform owner after switching; then no practice is bound.
        "is_platform_owner": request.user.is_platform_owner,
        "area": getattr(request, "area", "practice"),
        # The switch's other label, readable from the Practices area too.
        "home_practice": _home_practice(request.user) if request.user.is_platform_owner else None,
        # P2: a practice owner sees the beta agreement before anything else.
        "agreement_required": _agreement_required(request),
        "tenant": str(membership.tenant_id) if membership else None,
        "client_company": (
            str(membership.client_company_id)
            if membership and membership.client_company_id else None
        ),
        # Whether this build offers the development-only controls (the digest
        # "Generate now", for instance). False anywhere that is not localhost,
        # so the control cannot appear in front of a client.
        "dev_tools": settings.IS_LOCAL,
        # local | demo | production: the staff banner says "Demo" (2026-09-29).
        "environment": settings.APP_ENVIRONMENT,
        # FR-3.42 — while acting as, everything above describes the acted-as
        # user; this names both people, for the banner that never goes away.
        "acting": _acting(request),
    })


@csrf_protect
@require_http_methods(["POST"])
def sign_out(request):
    """The top bar's Sign out. Ends the session on the server; signing out
    while acting as someone ends that too, audited (tenancy.acting)."""
    logout(request)
    return JsonResponse({"signed_out": True})


NAME_MAX = 200


def _profile(request) -> dict:
    """What a person's Profile page shows: themselves, and where they sit.
    While acting as someone it describes the acted-as person, read-only."""
    membership = getattr(request, "membership", None)
    company = membership.client_company if membership and membership.client_company_id else None
    return {
        "email": request.user.email,
        "full_name": request.user.full_name,
        "role_label": role_label(membership.role) if membership else None,
        "practice": email_layout_name(membership.tenant) if membership else None,
        "client_company_name": company.name if company else None,
        # A person's profile is theirs: nobody changes it from inside an
        # acting-as session, the practice owner included.
        "editable": getattr(request, "acting_as", None) is None,
    }


def email_layout_name(tenant) -> str:
    from apps.crm.services import email_layout

    return email_layout.branding(tenant).display_name


@csrf_protect
@require_http_methods(["GET", "PATCH"])
def profile(request):
    """UI 3 spec §5. `GET` reads it; `PATCH` changes the person's own name.

    There is no id in the address: the only profile anyone can reach is their
    own. The sign-in email is not changeable here (D6), and saying so beats
    ignoring it.
    """
    import json

    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    if request.method == "GET":
        return JsonResponse(_profile(request))

    if getattr(request, "acting_as", None) is not None:
        return JsonResponse(
            {"detail": "You are acting as someone else. Their profile is theirs to change."},
            status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JsonResponse({"detail": "Send the changes as JSON."}, status=400)
    unknown = sorted(set(data) - {"full_name"})
    if "email" in unknown:
        return JsonResponse(
            {"email": "The sign-in email cannot be changed here. Ask the practice owner."},
            status=400)
    if unknown:
        return JsonResponse({"detail": f"Not something Profile changes: {', '.join(unknown)}."},
                            status=400)
    name = data.get("full_name")
    if not isinstance(name, str) or not name.strip():
        return JsonResponse({"full_name": "Enter your name."}, status=400)
    name = " ".join(name.split())
    if len(name) > NAME_MAX:
        return JsonResponse({"full_name": f"A name is at most {NAME_MAX} characters."},
                            status=400)

    user = request.user
    if name != user.full_name:
        user.full_name = name
        user.save(update_fields=["full_name", "updated_at"])
    return JsonResponse(_profile(request))


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
                  tenant_branding(_branding_tenant(request), check_logo=True), status=403)


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
        .exclude(tenant__status="archived")     # P2: no sign-in link for an archived practice
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


def sign_in_page_url() -> str:
    """The signed-out screen, absolute, for an email or a page outside the app.

    APP_ROOT_URL is the Vite origin in development and a bare "/" in
    production, where the app is served from PUBLIC_BASE_URL. Signed out, the
    app's root *is* the sign-in page, with "Email me a sign-in link" on it.
    """
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return root


#: The button on the sign-in page, named wherever a dead link sends someone.
SIGN_IN_BUTTON = "Email me a sign-in link"


def invitation_subject(tenant):
    from apps.crm.services import email_layout

    return f"Your invitation to {email_layout.branding(tenant).display_name}"


def invitation_email(tenant, *, url):
    """`(html, text)` for a portal invitation: the sign-in email with a week to
    use it, and the way back in if the week runs out."""
    from apps.crm.services import email_layout

    name = email_layout.branding(tenant).display_name
    return email_layout.action_link_email(
        tenant, subject=invitation_subject(tenant), heading=invitation_subject(tenant),
        paragraphs=[f"{name} has set up portal access for you. Use the button below to "
                    "sign in. You'll see your company's work, and nothing else."],
        button_label="Sign in", url=url,
        expiry="This invitation is valid for 7 days and can be used once.",
        closing=f"After that, or to sign in again later, go to the sign-in page, enter "
                f"this email address and choose \u201c{SIGN_IN_BUTTON}\u201d.",
        help_label="Sign-in page", help_url=sign_in_page_url(),
        redacted_note=MAGIC_LINK_REDACTED,
    )


def _send_magic_link(membership, raw_token, *, invitation=False) -> bool:
    """Sent synchronously, not queued (assumption A2a).

    With one ORM-backed queue and no priority lanes, an enqueued magic link
    could sit behind a 40-minute transcription — a sign-in that looks broken.

    A direct-to-sent Outbox producer (FR-1.15b) through the configured
    transport, like every other app email. The link is delivered but never
    stored: the Outbox row is visible to tenant staff, and a stored link would
    let any of them sign in as the client (assumption C3).

    A send failure does NOT change the response: the request endpoint answers
    identically whether or not the address exists, and an error only for real
    addresses would undo that. The failure is audited for the FF instead, and
    returned, so a staff action (grant, resend) can say the email did not go.

    `invitation=True` is the portal invitation: same link, its own words.
    """
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.crm.services.transport import TransportUnavailable
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import AuditEvent

    url = f"{settings.PUBLIC_BASE_URL}/auth/magic/{raw_token}"
    compose = invitation_email if invitation else magic_link_email
    subject = (invitation_subject if invitation else magic_link_subject)(membership.tenant)
    stored_html, stored_text = compose(membership.tenant, url=None)
    html, text = compose(membership.tenant, url=url)

    try:
        # The requester is not signed in, so no tenant is bound (B1). Bind the
        # member's own, explicitly, as a background job would.
        with tenant_context(membership.tenant_id):
            outbox.create_message(
                tenant=membership.tenant, producer=OutboxMessage.Producer.MAGIC_LINK,
                to_address=membership.user.email, subject=subject,
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
        return False
    return True


@require_http_methods(["GET", "POST"])
def magic_link_landing(request, token: str):
    """C3.3 — GET renders a button; only POST consumes the token.

    Corporate mail scanners and link-preview bots follow GET links and would
    otherwise burn the token before the client ever clicks it.
    """
    record = MagicLinkToken.resolve(token, purpose=SIGN_IN_PURPOSES)
    # A dead link still says whose it was and what kind, and where to get a
    # working one: an expired invitation used to be a dead end that only a
    # revoke and a new grant could fix.
    spent = record or MagicLinkToken.find_sign_in(token)

    brand = tenant_branding(_tenant_of(spent) or _branding_tenant(request), check_logo=True)
    page = {**brand, "token": token, "valid": record is not None,
            "invitation": spent is not None and spent.purpose == MagicLinkPurpose.INVITE,
            "sign_in_url": sign_in_page_url(), "sign_in_button": SIGN_IN_BUTTON}

    if request.method == "GET":
        return render(request, "accounts/magic_link.html", page)

    if record is None:
        return render(request, "accounts/magic_link.html", page, status=400)

    record.consume()
    MagicLinkToken.spend_sign_in_links(tenant_id=record.tenant_id, user_id=record.user_id)
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
