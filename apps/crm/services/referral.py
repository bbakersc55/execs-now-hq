"""Referral partner touches and onboarding (FR-1.20 - FR-1.23d)."""

from __future__ import annotations

from django.utils import timezone

from apps.crm.models import Contact, ContactType, ContactTypeLink, EmailTemplate
from apps.crm.services.outbox import P, create_message
from apps.tenancy.models import AuditEvent

CADENCE_DAYS = {"monthly": 30, "bimonthly": 60, "quarterly": 90}
DRAFT_LEAD_DAYS = 3  # FR-1.21 — drafted 3 days BEFORE the due date.


def compose_touch(contact) -> tuple[str, bool, str]:
    """FR-1.22 — three parts, 3-5 lines.

    Returns (body, is_ai_generated, warning).

    A touch that only asks is a worse email than one that also offers, which is
    why the reciprocal line is not optional.
    """
    tenant = contact.tenant
    warning = _blurb_warning(contact)

    if contact.referral_touch_mode == "template" and contact.referral_template:
        return contact.referral_template.body, False, warning

    # Part 1 — what the fractional has been working on lately (the substance).
    blurb = (tenant.referral_blurb or "").strip()
    lines = [f"Hi {contact.first_name},", ""]
    if blurb:
        lines.append(blurb)
    # Part 2 — the fee reminder, ONLY when terms exist, phrased as a reminder
    # of the arrangement rather than a demand.
    if contact.referral_fee_terms:
        lines.append(
            f"As a reminder of our arrangement: {contact.referral_fee_terms}."
        )
    # Part 3 — the reciprocal line.
    lines.append(
        "If there's a type of introduction that would help you right now, "
        "tell me and I'll keep an eye out."
    )
    lines += ["", tenant.name]
    return "\n".join(lines), True, warning


def _blurb_warning(contact) -> str:
    """FR-1.22a — warn, do not block.

    Sometimes last month's work is still this month's news; but nobody should
    mail twelve partners the same stale paragraph without noticing.
    """
    tenant = contact.tenant
    if not tenant.referral_blurb_updated_at:
        return "No 'what I'm working on lately' blurb has been set."
    age = (timezone.now() - tenant.referral_blurb_updated_at).days
    period = CADENCE_DAYS.get(contact.referral_cadence or "monthly", 30)
    if age > period:
        return (
            f"The 'what I'm working on lately' blurb was last updated "
            f"{age} days ago, which is older than this contact's "
            f"{contact.referral_cadence or 'monthly'} cadence."
        )
    return ""


def draft_due_touches(tenant, *, now=None):
    """FR-1.21 — a scheduled job drafts each due touch 3 days early.

    The automation buys drafting time, not send authority.
    """
    now = now or timezone.now()
    horizon = now + timezone.timedelta(days=DRAFT_LEAD_DAYS)
    partner = ContactType.all_objects.filter(tenant=tenant, code="referral_partner").first()
    if partner is None:
        return []

    due = Contact.all_objects.filter(
        tenant=tenant, deleted_at__isnull=True,
        type_links__contact_type=partner,
        referral_next_touch_at__isnull=False,
        referral_next_touch_at__lte=horizon,
    ).distinct()

    drafted = []
    for contact in due:
        body, is_ai, warning = compose_touch(contact)
        message = create_message(
            tenant=tenant, producer=P.REFERRAL_TOUCH,
            to_contact=contact, to_address=contact.primary_email or "",
            subject=f"Checking in from {tenant.name}",
            body_text=body, is_ai_generated=is_ai, warning=warning,
            send_by=contact.referral_next_touch_at,
            source_type="contact", source_id=contact.pk,
        )
        contact.referral_next_touch_at = _next_touch(contact, contact.referral_next_touch_at)
        contact.save(update_fields=["referral_next_touch_at", "updated_at"])
        drafted.append(message)
    return drafted


def _next_touch(contact, from_when):
    days = CADENCE_DAYS.get(contact.referral_cadence or "monthly", 30)
    return (from_when or timezone.now()) + timezone.timedelta(days=days)


def onboard_referral_partner(contact, *, actor=None):
    """FR-1.23a-23d — fires the moment a contact FIRST becomes a referral
    partner, by hand or via a Module 5 approval.

    It is the first touch, sent while the meeting is fresh, not on the next
    cadence date. It queues; it never sends.
    """
    if contact.referral_onboarded_at is not None:
        return None  # FR-1.23d — never re-triggers.

    tenant = contact.tenant
    template = EmailTemplate.all_objects.filter(
        tenant=tenant, kind=EmailTemplate.Kind.REFERRAL_ONBOARDING
    ).first()

    attachments = []
    warning = ""
    if tenant.marketing_flyer_id:
        attachments.append((tenant.marketing_flyer, "Executives-Now.pdf"))
    else:
        # FR-1.23b — the flyer is optional; say so rather than suppressing the
        # draft.
        warning = "No marketing flyer is uploaded, so this draft has no attachment."

    body = template.body if template else (
        f"Hi {contact.first_name},\n\n"
        "Great to meet you. I've attached a short overview of what we do, "
        "so you know what to look out for.\n\n"
        "If there's a type of introduction that would help you, tell me and "
        "I'll keep an eye out.\n\n"
        f"{tenant.name}"
    )

    message = create_message(
        tenant=tenant, producer=P.REFERRAL_ONBOARDING,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=template.subject if template else "Good to meet you",
        body_text=body, warning=warning, actor=actor,
        send_by=timezone.now() + timezone.timedelta(days=7),
        attachments=attachments,
        source_type="contact", source_id=contact.pk,
    )

    now = timezone.now()
    contact.referral_onboarded_at = now
    # FR-1.23c — the cadence clock starts from the onboarding date.
    contact.referral_cadence = contact.referral_cadence or "monthly"
    contact.referral_next_touch_at = _next_touch(contact, now)
    contact.save(update_fields=[
        "referral_onboarded_at", "referral_cadence", "referral_next_touch_at", "updated_at",
    ])
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="referral.onboarded",
        target_type="contact", target_id=contact.pk,
        payload={"flyer_attached": bool(attachments), "outbox_id": str(message.pk)},
    )
    return message


def add_type(contact, code, *, actor=None):
    """Adding `referral_partner` triggers onboarding (FR-1.23a, FR-5.9b)."""
    contact_type = ContactType.all_objects.filter(tenant=contact.tenant, code=code).first()
    if contact_type is None:
        return None
    link, created = ContactTypeLink.all_objects.get_or_create(
        tenant=contact.tenant, contact=contact, contact_type=contact_type
    )
    if created and code == "referral_partner":
        onboard_referral_partner(contact, actor=actor)
    return link
