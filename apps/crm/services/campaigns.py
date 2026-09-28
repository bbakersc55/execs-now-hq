"""Campaigns: one marketing email, written once, queued for many (owner,
2026-09-28).

The composer writes a body — in the rich editor, or as raw HTML — with merge
fields. Choosing recipients and pressing "Enrol and queue" makes **one Outbox
row per recipient**, `pending_approval`, category marketing, each already
merged for its person, so what the queue shows is exactly what they get.
Nothing here sends; approval does.

The branded layout wraps the body, as it wraps every other email, unless the
campaign is "send as-is": then the HTML goes out as written, marked as a
finished document so the layout leaves it alone. Either way, as marketing, it
carries the unsubscribe link (`unsubscribe.apply` puts it before `</body>`).
"""

from __future__ import annotations

import html as html_lib
import re

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape, strip_tags

from apps.crm.models import CampaignRecipient, EmailSuppression, OutboxMessage
from apps.tenancy.models import AuditEvent

P = OutboxMessage.Producer
S = OutboxMessage.State

#: How long a queued campaign email waits for approval before it expires,
#: like every other draft (FR-1.18). Two weeks: a campaign is not urgent.
SEND_BY_DAYS = 14

MERGE_FIELDS = ("{FirstName}", "{Company}", "{FractionalName}")


class CampaignRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# -------------------------------------------------------------- merge fields

def merge_values(contact, sender_name) -> dict:
    """What each field becomes for one person. A missing first name reads
    "there" ("Hi there,"), because "Hi ," is worse than generic."""
    return {
        "{FirstName}": (contact.first_name or "").strip() if contact else "",
        "{Company}": (contact.company.name if contact and contact.company_id else ""),
        "{FractionalName}": sender_name or "",
    }


def merge(value: str, values: dict, *, as_html: bool) -> str:
    out = value or ""
    for field, replacement in values.items():
        if field == "{FirstName}" and not replacement:
            replacement = "there"
        out = out.replace(field, escape(replacement) if as_html else replacement)
    return out


def sender_name(campaign, actor=None) -> str:
    person = campaign.created_by or actor
    return (getattr(person, "full_name", "") or "").strip() if person else ""


# --------------------------------------------------------------- the body

AS_IS = 'data-enhq-email="as-is"'


def as_is_document(markup: str) -> str:
    """Raw HTML sent as written: marked as a finished document so the layout
    does not wrap it. A fragment gets the minimum around it to be a document."""
    if re.search(r"<html\b", markup, re.IGNORECASE):
        return re.sub(r"<html\b", f"<html {AS_IS}", markup, count=1, flags=re.IGNORECASE)
    return (f'<!DOCTYPE html><html {AS_IS}><head><meta charset="utf-8"></head>'
            f"<body>{markup}</body></html>")


def text_of(markup: str) -> str:
    """The plain-text part: the words of the HTML, paragraphs kept."""
    markup = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", markup or "")
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    markup = re.sub(r"(?i)</(p|div|h[1-6]|li|tr)>", "\n\n", markup)
    words = html_lib.unescape(strip_tags(markup))
    lines = [line.strip() for line in words.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def rendered_for(campaign, contact, *, actor=None) -> tuple[str, str, str]:
    """`(subject, html, text)` for one person, merged."""
    values = merge_values(contact, sender_name(campaign, actor))
    subject = merge(campaign.subject, values, as_html=False)
    body = merge(campaign.body_html, values, as_html=True)
    html = as_is_document(body) if campaign.send_as_is else body
    return subject, html, text_of(body)


def preview(campaign, contact=None, *, actor=None, to_address="") -> tuple[str, str]:
    """Exactly as it will land for this person — layout, link and all — from
    the same function every send uses."""
    from apps.crm.services import email_layout

    subject, html, text = rendered_for(campaign, contact, actor=actor)
    message = OutboxMessage(
        tenant=campaign.tenant, producer=P.CAMPAIGN, category="marketing",
        to_contact=contact,
        to_address=to_address or (contact.primary_email if contact else "") or "",
        subject=subject, body_text=text, body_html=html)
    return email_layout.for_delivery(message)


# --------------------------------------------------------------- recipients

def candidates(queryset, *, contact_type="", stage="", tag="", enrolled=""):
    """Contacts matching the filters; the caller has already scoped them."""
    qs = queryset.filter(deleted_at__isnull=True)
    if contact_type:
        qs = qs.filter(type_links__contact_type__code=contact_type)
    if stage:
        qs = qs.filter(pipeline_positions__stage_id=stage)
    if tag:
        qs = qs.filter(tags__contains=[tag])
    from django.db.models import Exists, OuterRef

    from apps.crm.models import Enrollment
    from apps.work.models import Stakeholder

    on_touches = Exists(Enrollment.objects.filter(
        contact=OuterRef("pk"), program="referral_touches", ended_at__isnull=True))
    on_digest = Exists(Stakeholder.objects.filter(contact=OuterRef("pk"), is_muted=False))
    in_campaign = Exists(CampaignRecipient.objects.filter(contact=OuterRef("pk"),
                                                          ended_at__isnull=True))
    if enrolled == "referral_touches":
        qs = qs.filter(on_touches)
    elif enrolled == "digest":
        qs = qs.filter(on_digest)
    elif enrolled == "none":
        qs = qs.exclude(on_touches).exclude(on_digest).exclude(in_campaign)
    return qs.distinct()


def unsendable(contact, campaign) -> str:
    """Why this person cannot be queued, or "" if they can."""
    if not contact.primary_email:
        return "no email address"
    if EmailSuppression.all_objects.filter(tenant_id=contact.tenant_id, contact=contact,
                                           category="marketing",
                                           lifted_at__isnull=True).exists():
        return "unsubscribed from marketing emails"
    if CampaignRecipient.all_objects.filter(campaign=campaign, contact=contact,
                                            ended_at__isnull=True).exists():
        return "already in this campaign"
    return ""


@transaction.atomic
def queue(campaign, contacts, *, actor) -> dict:
    """"Enrol and queue": for each person, their enrolment in the campaign and
    their own Outbox row, pending approval. Skips — each named, with why —
    anyone with no address, anyone who left marketing, and anyone already in."""
    from apps.crm.services import outbox, sender

    if not campaign.subject.strip():
        raise CampaignRefused("Give the campaign a subject first.")
    if not strip_tags(campaign.body_html or "").strip():
        raise CampaignRefused("The email has nothing in it yet.")
    from_address = sender.resolve_from(campaign.tenant, campaign.created_by or actor,
                                       P.CAMPAIGN, override=campaign.sender)
    queued, skipped = [], []
    send_by = timezone.now() + timezone.timedelta(days=SEND_BY_DAYS)
    for contact in contacts:
        why = unsendable(contact, campaign)
        if why:
            skipped.append({"contact": str(contact.pk),
                            "name": f"{contact.first_name} {contact.last_name}".strip(),
                            "detail": why})
            continue
        subject, html, text = rendered_for(campaign, contact, actor=actor)
        message = outbox.create_message(
            tenant=campaign.tenant, producer=P.CAMPAIGN, category="marketing",
            to_contact=contact, to_address=contact.primary_email,
            subject=subject, body_text=text, body_html=html, actor=actor,
            from_address=from_address, send_by=send_by,
            source_type="campaign", source_id=campaign.pk)
        CampaignRecipient.all_objects.update_or_create(
            tenant_id=campaign.tenant_id, campaign=campaign, contact=contact,
            defaults={"outbox_message": message, "enrolled_by": actor,
                      "ended_at": None, "ended_reason": ""})
        queued.append(str(message.pk))
    AuditEvent.all_objects.create(
        tenant_id=campaign.tenant_id, actor=actor, verb="campaign.queued",
        target_type="campaign", target_id=campaign.pk,
        payload={"queued": len(queued), "skipped": skipped, "from": from_address})
    return {"queued": queued, "queued_count": len(queued), "skipped": skipped}


def test_send(campaign, *, actor, contact=None):
    """To the person composing it, now, marked as a test. Merged for
    `contact` when one is given, so the fields can be checked."""
    from apps.crm.services import outbox, sender

    address = (getattr(actor, "email", "") or "").strip()
    if not address:
        raise CampaignRefused("Your account has no email address to send a test to.")
    subject, html, text = rendered_for(campaign, contact, actor=actor)
    return outbox.create_message(
        tenant=campaign.tenant, producer=P.CAMPAIGN, category="marketing",
        to_address=address, subject=f"[Test] {subject}", body_text=text, body_html=html,
        actor=actor, force_direct=True,
        from_address=sender.resolve_from(campaign.tenant, campaign.created_by or actor,
                                         P.CAMPAIGN, override=campaign.sender),
        source_type="campaign_test", source_id=campaign.pk)


# ------------------------------------------------------------- enrolments

def end(recipient, *, actor=None, reason="unenrolled") -> None:
    """Off the campaign. Their email, if nobody has approved it, is withdrawn."""
    recipient.ended_at, recipient.ended_reason = timezone.now(), reason
    recipient.save(update_fields=["ended_at", "ended_reason", "updated_at"])
    if recipient.outbox_message_id:
        OutboxMessage.all_objects.filter(
            pk=recipient.outbox_message_id,
            state__in=[S.DRAFT, S.PENDING_APPROVAL]).update(
            state=S.REJECTED, warning=f"Withdrawn: {reason} from the campaign.",
            updated_at=timezone.now())
    AuditEvent.all_objects.create(
        tenant_id=recipient.tenant_id, actor=actor, verb="enrollment.ended",
        target_type="campaign_recipient", target_id=recipient.pk,
        payload={"program": "campaign", "campaign": str(recipient.campaign_id),
                 "reason": reason})


def stats(campaign) -> dict:
    """The campaign page's numbers, from the rows themselves."""
    rows = CampaignRecipient.all_objects.filter(campaign=campaign)
    messages = OutboxMessage.all_objects.filter(
        pk__in=rows.exclude(outbox_message__isnull=True).values("outbox_message_id"))
    states = {state: messages.filter(state=state).count() for state in S.values}
    return {
        "recipients": rows.filter(ended_at__isnull=True).count(),
        "queued": states[S.PENDING_APPROVAL] + states[S.DRAFT],
        "sent": states[S.SENT],
        "unsubscribed": rows.filter(ended_reason="unsubscribed").count()
        + rows.filter(ended_at__isnull=True, contact__suppressions__category="marketing",
                      contact__suppressions__lifted_at__isnull=True).distinct().count(),
        "not_sent": states[S.REJECTED] + states[S.EXPIRED] + states[S.SUPPRESSED],
    }


def active_for(contact):
    return CampaignRecipient.all_objects.filter(
        tenant_id=contact.tenant_id, contact=contact,
        ended_at__isnull=True).select_related("campaign")

