"""Referral partner touches and onboarding (FR-1.20 - FR-1.23d)."""

from __future__ import annotations

from django.utils import timezone

from apps.crm.models import Contact, ContactType, ContactTypeLink, EmailTemplate
from apps.crm.services.outbox import P, create_message
from apps.tenancy.models import AuditEvent

CADENCE_DAYS = {"monthly": 30, "bimonthly": 60, "quarterly": 90}
DRAFT_LEAD_DAYS = 3  # FR-1.21 — drafted 3 days BEFORE the due date.


def compose_touch(contact, *, actor=None) -> tuple[str, bool, str]:
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
    # FR-1.15d — sign off as a person. A bare practice name under a message
    # asking a partner for introductions reads as a form letter.
    from apps.crm.services import sender as sender_service

    signature_text, _ = sender_service.signature(tenant, actor)
    lines += ["", signature_text]
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
        # No human triggered this run, so the touch signs off as the person
        # whose relationship it is — the contact's owner — not as nobody.
        actor = contact.owner
        body, is_ai, warning = compose_touch(contact, actor=actor)
        message = create_message(
            actor=actor,
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

    # FR-1.23b — the sentence has to match reality. Claiming an attachment that
    # is not there is worse than not mentioning one: the partner looks for a
    # file, finds none, and the first impression is of a broken email.
    opening = (
        "Great to meet you. I've attached a short overview of what we do, "
        "so you know what to look out for."
        if attachments else
        "Great to meet you — good to know what you're working on."
    )
    body = template.body if template else (
        f"Hi {contact.first_name},\n\n"
        f"{opening}\n\n"
        "If there's a type of introduction that would help you, tell me and "
        "I'll keep an eye out.\n\n"
        f"{_signature_for(tenant, actor)}"
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

    # FR-1.23 — a new referral partner enters the referral pipeline at its entry
    # stage. Placed here, not inferred from the type: pipeline membership and
    # contact type are separate facts (the partner may also be a live prospect
    # in the sales pipeline, and neither position should disturb the other).
    _place_in_referral_pipeline(contact, actor=actor)

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


def _signature_for(tenant, actor):
    from apps.crm.services import sender as sender_service

    text, _ = sender_service.signature(tenant, actor)
    return text


def _place_in_referral_pipeline(contact, *, actor=None):
    """Entry stage of the referral pipeline, if the tenant has one.

    Uses the ordinary `change_stage`, so the move produces an ordinary
    `stage_change` row and shows on the timeline like any other — there is no
    second, invisible way for a contact to move.
    """
    from apps.crm.services import pipeline as pipeline_service

    pipeline = pipeline_service.referral_pipeline(contact.tenant)
    if pipeline is None:
        return None
    if pipeline_service.position_for(contact, pipeline) is not None:
        return None  # already in it; onboarding must not reset their progress
    stage = pipeline_service.entry_stage(pipeline)
    if stage is None:
        return None
    return pipeline_service.change_stage(
        contact, stage, actor=actor, reason="became a referral partner",
    )


DEFAULT_CADENCE = "monthly"


def ensure_touch_schedule(contact, *, from_when=None):
    """FR-1.20/1.21 — a referral partner without a cadence is invisible to the
    scheduler, so it never drafts for them.

    That is exactly what happened to the imported book: 40 partners arrived with
    the type set and no cadence and no `next_touch_at`, so the due-touch job had
    nothing to find. Setting both is what makes a partner real to the scheduler.

    Only fills what is missing — it never moves a date somebody already has.
    """
    updates = []
    if not contact.referral_cadence:
        contact.referral_cadence = DEFAULT_CADENCE
        updates.append("referral_cadence")
    if contact.referral_next_touch_at is None:
        contact.referral_next_touch_at = _next_touch(contact, from_when or timezone.now())
        updates.append("referral_next_touch_at")
    if updates:
        contact.save(update_fields=[*updates, "updated_at"])
    return updates


def add_type(contact, code, *, actor=None, onboard=True):
    """Adding `referral_partner` puts them on the touch cadence, and (unless
    `onboard=False`) triggers onboarding (FR-1.23a, FR-5.9b).

    `onboard=False` is the CSV import's path: a backfill is a statement about
    history, so it must not queue a first-touch email to forty partners the
    fractional met years ago. It still sets the cadence, because a partner the
    scheduler cannot see is the bug this fixes.
    """
    contact_type = ContactType.all_objects.filter(tenant=contact.tenant, code=code).first()
    if contact_type is None:
        return None
    link, created = ContactTypeLink.all_objects.get_or_create(
        tenant=contact.tenant, contact=contact, contact_type=contact_type
    )
    if created and code == "referral_partner":
        if onboard:
            # FR-1.23c — onboarding sets the clock from the draft date, so it
            # owns the schedule when it runs. Clock rules unchanged.
            onboard_referral_partner(contact, actor=actor)
        ensure_touch_schedule(contact)
    return link


def draft_touch_now(contact, *, actor=None):
    """FR-1.21/1.22 — draft this partner's touch on demand.

    The same composer the scheduled job uses, landing in the same
    `pending_approval` state. A manual trigger that took a different path could
    produce a different email, which would make the scheduled one untestable.

    It does NOT move `referral_next_touch_at`: drafting one now is an extra
    touch, not a replacement for the one already due.
    """
    body, is_ai, warning = compose_touch(contact, actor=actor)
    message = create_message(
        tenant=contact.tenant, producer=P.REFERRAL_TOUCH,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=f"Checking in — {contact.tenant.name}",
        body_text=body, is_ai_generated=is_ai, warning=warning, actor=actor,
        send_by=timezone.now() + timezone.timedelta(days=DRAFT_LEAD_DAYS),
        source_type="contact", source_id=contact.pk,
    )
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="referral.touch_drafted",
        target_type="contact", target_id=contact.pk,
        payload={"outbox_id": str(message.pk), "on_demand": True},
    )
    return message
