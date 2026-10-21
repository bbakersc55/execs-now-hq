"""Referral partner touches and onboarding (FR-1.20 - FR-1.23d)."""

from __future__ import annotations

from django.utils import timezone

from apps.crm.models import Contact, ContactType, ContactTypeLink
from apps.crm.services.outbox import P, create_message
from apps.tenancy.models import AuditEvent

CADENCE_DAYS = {"monthly": 30, "bimonthly": 60, "quarterly": 90}
DRAFT_LEAD_DAYS = 3  # FR-1.21 — drafted 3 days BEFORE the due date.


def touch_template(contact):
    """The partner's own template, else the practice's touch template."""
    from apps.crm.services import templates

    return contact.referral_template or templates.for_use(contact.tenant, "referral_touch")


def compose_touch(contact, *, actor=None) -> tuple[str, str, bool, str]:
    """FR-1.22: `(subject, body, is_ai_generated, warning)`.

    Two modes (owner, 2026-10-20). **My template**: the touch template, merged
    and signed. **Draft with Claude**: Claude writes it from the partner's
    record and the last meeting they were in, under the practice's key, in
    the shape of the template; with no key, or if Claude cannot answer, the
    template is used and the draft says why.
    """
    from apps.crm.services import templates

    warning = _blurb_warning(contact)
    template = touch_template(contact)
    subject, body = templates.compose(template, contact, actor=actor)
    if contact.referral_touch_mode != "claude":
        return subject, body, False, warning
    from apps.tenancy import claude

    try:
        drafted = claude.complete(
            tenant=contact.tenant, purpose="referral_touch",
            system=claude.drafting(TOUCH_SYSTEM),
            user_text=_touch_facts(contact, template, actor),
            target_type="contact", target_id=contact.pk,
            trigger="auto", max_tokens=1500,
        ).strip()
    except (claude.ClaudeUnavailable, claude.ClaudeRefused) as error:
        why = str(error).strip() or "Claude could not draft it"
        note = f"Drafted from the template instead of by Claude: {why}"
        return subject, body, False, " ".join(filter(None, [note, warning]))
    if not drafted:
        return subject, body, False, " ".join(filter(None, [
            "Drafted from the template: Claude's answer was empty.", warning]))
    return subject, templates.with_signature(drafted, contact.tenant, actor), True, warning


TOUCH_SYSTEM = """You write a short check-in email from a fractional executive to one of \
their referral partners: someone who sends them clients and whom they help in return.

Three to five short lines, warm and plain, written as the person writes, never as \
marketing. Use only the facts you are given; never invent news, clients, numbers or \
promises. If a recent meeting is given, pick up one real thread from it. Mention the \
fee arrangement only when terms are given, as a light reminder, never a demand. End \
with an offer to look out for introductions that would help them.

Write only the email's body. Start with "Hi <their first name>," on its own line, and \
stop before any sign-off: the signature is added after. No subject line."""


def _touch_facts(contact, template, actor) -> str:
    """What Claude is given: the partner's record, their last meeting, and the
    practice's own template for tone and shape."""
    from django.db.models import F

    from apps.crm.services import templates
    from apps.meetings.models import Meeting

    tenant = contact.tenant
    lines = [
        f"Practice: {tenant.name}",
        f"Written by: {(getattr(actor, 'full_name', '') or '').strip() or 'the practice owner'}",
        f"Partner: {contact.first_name} {contact.last_name}".rstrip(),
    ]
    if contact.title:
        lines.append(f"Their title: {contact.title}")
    if contact.company_id:
        lines.append(f"Their company: {contact.company.name}")
    if contact.background.strip():
        lines.append(f"Who they are and how we know them: {contact.background.strip()[:1500]}")
    if contact.referral_fee_terms.strip():
        lines.append(f"Fee terms: {contact.referral_fee_terms.strip()}")
    if (tenant.referral_blurb or "").strip():
        lines.append(f"What the practice is working on lately: {tenant.referral_blurb.strip()}")
    # Newest first, an undated one last: Postgres sorts NULL first otherwise.
    meeting = (Meeting.all_objects.filter(tenant=tenant, participants__contact=contact)
               .order_by(F("meeting_date").desc(nulls_last=True), "-created_at").first())
    if meeting is not None:
        when = meeting.meeting_date.isoformat() if meeting.meeting_date else "date unknown"
        lines.append(f"\nTheir last meeting with us ({when}): {meeting.title or 'untitled'}")
        if meeting.summary.strip():
            lines.append(meeting.summary.strip()[:3000])
    else:
        lines.append("\nNo meeting with them is on record.")
    shape = templates.render(template.body, templates.values_for(
        contact, tenant=tenant, sender=actor), fallback=template.first_name_fallback)
    lines += ["", "The practice's own touch email, for tone and length:", shape]
    return "\n".join(lines)


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

    The automation buys drafting time, not send authority. **Only enrolled
    partners** (owner, 2026-09-28): a partner nobody has enrolled has nothing
    drafted, whatever date is on their record.
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
        enrollments__program="referral_touches",
        enrollments__ended_at__isnull=True,
    ).distinct()

    drafted = []
    for contact in due:
        # No human triggered this run, so the touch signs off as the person
        # whose relationship it is — the contact's owner — not as nobody.
        actor = contact.owner
        subject, body, is_ai, warning = compose_touch(contact, actor=actor)
        message = create_message(
            actor=actor,
            tenant=tenant, producer=P.REFERRAL_TOUCH,
            to_contact=contact, to_address=contact.primary_email or "",
            subject=subject,
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


def compose_onboarding(contact, *, actor=None, template=None, with_attachment=False):
    """FR-1.23b: `(subject, body)`, from the practice's onboarding template.
    The flyer line is there only when the flyer is: claiming an attachment
    that is not there is worse than not mentioning one."""
    from apps.crm.services import templates

    template = template or templates.for_use(contact.tenant, "referral_onboarding")
    return templates.compose(template, contact, actor=actor,
                             FlyerNote=templates.FLYER_NOTE if with_attachment else "")


def onboard_referral_partner(contact, *, actor=None):
    """FR-1.23a-23d — fires the moment a contact FIRST becomes a referral
    partner, by hand or via a Module 5 approval.

    It is the first touch, sent while the meeting is fresh, not on the next
    cadence date. It queues; it never sends.
    """
    if contact.referral_onboarded_at is not None:
        return None  # FR-1.23d — never re-triggers.

    tenant = contact.tenant
    attachments = []
    warning = ""
    if tenant.marketing_flyer_id:
        # The practice's own name, never the product owner's: a client of any
        # tenant sees only their fractional's brand (white-label).
        from django.utils.text import slugify

        attachments.append((tenant.marketing_flyer, f"{slugify(tenant.name) or 'practice'}.pdf"))
    else:
        # FR-1.23b — the flyer is optional; say so rather than suppressing the
        # draft.
        warning = "No marketing flyer is uploaded, so this draft has no attachment."

    subject, body = compose_onboarding(contact, actor=actor,
                                       with_attachment=bool(attachments))

    message = create_message(
        tenant=tenant, producer=P.REFERRAL_ONBOARDING,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=subject, body_text=body, warning=warning, actor=actor,
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
    """Adding `referral_partner` triggers onboarding (unless `onboard=False`)
    — one draft, waiting for approval (FR-1.23a, FR-5.9b).

    It does **not** put them on the touch cadence (owner, 2026-09-28): that is
    an enrolment, and enrolment is something the FF or a CF does on purpose
    (`services.enrollment`). `onboard=False` is the CSV import's path: a
    backfill is a statement about history and queues nothing.
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
    return link


def draft_touch_now(contact, *, actor=None):
    """FR-1.21/1.22 — draft this partner's touch on demand.

    The same composer the scheduled job uses, landing in the same
    `pending_approval` state. A manual trigger that took a different path could
    produce a different email, which would make the scheduled one untestable.

    It does NOT move `referral_next_touch_at`: drafting one now is an extra
    touch, not a replacement for the one already due.
    """
    subject, body, is_ai, warning = compose_touch(contact, actor=actor)
    message = create_message(
        tenant=contact.tenant, producer=P.REFERRAL_TOUCH,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=subject,
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
