"""Mail from the platform rather than from a practice (P2, D2): the practice
owner's invitation, and the feedback notice to the platform owner.

Sent through the platform owner's own practice (Executives Now), so it goes
out from its verified Gmail alias and lands in its Outbox, the one send log,
like every other message. No client footer: it is not client mail.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.html import escape

from config.branding import PRODUCT_NAME


class PlatformMailUnavailable(Exception):
    pass


def platform_owner():
    from apps.accounts.models import User

    return User.objects.filter(is_platform_owner=True).order_by("created_at").first()


def sender_tenant():
    """The platform owner's own practice: the one platform mail is sent from."""
    from apps.tenancy.models import Membership

    owner = platform_owner()
    membership = (Membership.all_objects.select_related("tenant")
                  .filter(user=owner, revoked_at__isnull=True).first()) if owner else None
    if membership is None:
        raise PlatformMailUnavailable("There is no platform owner with a practice to send from.")
    return membership.tenant


def _send(*, to, subject, paragraphs, producer):
    from apps.crm.services import email_layout, outbox
    from apps.tenancy.context import tenant_context

    sender = sender_tenant()
    text = "\n\n".join(paragraphs)
    html = email_layout.document(
        sender, subject=subject, preheader=paragraphs[0][:140], internal=True,
        content_html="".join(f"<p>{escape(p)}</p>" for p in paragraphs))
    from apps.crm.services.transport import TransportUnavailable

    try:
        with tenant_context(sender.pk):
            return outbox.create_message(tenant=sender, producer=producer, to_address=to,
                                         subject=subject, body_text=text, body_html=html)
    except TransportUnavailable as exc:
        raise PlatformMailUnavailable(
            f"Platform mail goes through {sender.email_display_name or sender.name}'s Gmail, "
            f"which could not send: {exc}") from exc


def send_invitation(tenant, *, actor):
    """The practice owner's invitation. Sent only when the platform owner
    presses Invite; provisioning never sends it."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import gmail_oauth
    from apps.tenancy.models import AuditEvent, Membership

    owner = (Membership.all_objects.select_related("user")
             .filter(tenant=tenant, role="FF", revoked_at__isnull=True)
             .order_by("created_at").first())
    if owner is None:
        raise PlatformMailUnavailable("This practice has no practice owner to invite.")
    if not gmail_oauth.is_configured(tenant):
        raise PlatformMailUnavailable(
            "Google sign-in for this practice is not set up yet: the External OAuth "
            "client is not configured (docs/google_verification.md, step 5). Inviting "
            "now would send someone a sign-in that cannot work.")
    name = tenant.email_display_name or tenant.name
    url = settings.PUBLIC_BASE_URL.rstrip("/")
    paragraphs = [
        f"{name} is set up in {PRODUCT_NAME}, and you are its practice owner.",
        # "Practice sign-in" is the heading on the sign-in page (SignedOut.tsx).
        f"To sign in, go to {url}. Under Practice sign-in, enter {owner.user.email} and choose "
        "Sign in with Google, using that same Google account.",
        "The first time, you will be asked to read and accept the beta agreement. "
        "Then the Getting started list on your dashboard walks you through the rest: "
        "your branding, Gmail, your Anthropic key, your contacts, your team, your "
        "first client and your first strategy template.",
        f"Questions: reply to this email. — {getattr(actor, 'full_name', '') or 'Executives Now'}",
    ]
    message = _send(to=owner.user.email, subject=f"{name} is ready in {PRODUCT_NAME}",
                    paragraphs=paragraphs, producer=OutboxMessage.Producer.PRACTICE_INVITE)
    AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb="practice.invited",
                                  target_type="user", target_id=owner.user_id,
                                  payload={"to": owner.user.email})
    return message
