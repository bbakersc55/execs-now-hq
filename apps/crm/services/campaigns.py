"""Campaigns: one marketing email, written once, queued for many (owner,
2026-09-28).

The composer writes a body — in the rich editor, or as raw HTML — with merge
fields. Choosing recipients and pressing "Enroll and queue" makes **one Outbox
row per recipient**, `pending_approval`, category marketing, each already
merged for its person, so what the queue shows is exactly what they get.
Nothing here sends; approval does.

The branded layout wraps the body, as it wraps every other email, unless the
campaign is "send as-is": then the HTML goes out as written, marked as a
finished document so the layout leaves it alone. Either way, as marketing, it
carries the unsubscribe link (`unsubscribe.apply` puts it before `</body>`).

**Follow-through** (owner, 2026-10-19). A campaign may carry up to three
files, copied onto every draft it makes; and "when this campaign is sent" it
may move each recipient to a stage and enrol them in referral touches at a
cadence. Both happen per person, **when their draft is approved and sent**
(`after_sent`, called by the Outbox): a draft refused, deleted, expired or
suppressed does nothing, and so an unsubscribed recipient is never moved or
enrolled. Each move and enrolment is on the contact's history and Activity.
"""

from __future__ import annotations

import html as html_lib
import re

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape, strip_tags

from apps.crm.models import (
    CampaignAttachment, CampaignRecipient, EmailSuppression, OutboxMessage,
)
from apps.tenancy.models import AuditEvent

P = OutboxMessage.Producer
S = OutboxMessage.State

#: How long a queued campaign email waits for approval before it expires,
#: like every other draft (FR-1.18). Two weeks: a campaign is not urgent.
SEND_BY_DAYS = 14

#: The template library's fields that mean something in a campaign: all but
#: the two that belong to one email (a thank-you's prospect, the flyer line).
#: One style everywhere (owner, 2026-10-20), `services.templates`.
GENERAL_FIELDS = ("FirstName", "LastName", "Company", "FractionalName", "PracticeName",
                  "PracticeNews", "FeeTerms")
MERGE_FIELDS = tuple(f"{{{name}}}" for name in GENERAL_FIELDS)
#: Files on a campaign (owner, 2026-10-19), each within the Outbox's limit.
MOST_ATTACHMENTS = 3


class CampaignRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# -------------------------------------------------------------- merge fields

def merge_values(contact, sender_name, tenant=None) -> dict:
    """What each field becomes for one person. A missing first name reads as
    the campaign's fallback ("Hi there,"), because "Hi ," is worse than
    generic."""
    from apps.crm.services import templates

    values = templates.values_for(contact, tenant=tenant or contact.tenant)
    values["FractionalName"] = sender_name or ""
    return {f"{{{name}}}": values[name] for name in GENERAL_FIELDS}


#: What the preview and a test show for each field when no person is chosen
#: (owner, 2026-10-20): a visible placeholder, not a nameless sample.
def _placeholders() -> dict:
    from apps.crm.services import templates

    return {f"{{{name}}}": templates.PLACEHOLDERS[name] for name in GENERAL_FIELDS}


PLACEHOLDERS = _placeholders()
TEST_LINE = "Test copy. Bracketed words are filled in for each person on the real send."
DEFAULT_FALLBACK = "there"


def merge(value: str, values: dict, *, as_html: bool, fallback: str = DEFAULT_FALLBACK) -> str:
    """Each field replaced. A missing first name reads as the campaign's
    fallback ("there" unless the campaign says otherwise)."""
    out = value or ""
    for field, replacement in values.items():
        if field == "{FirstName}" and not replacement:
            replacement = fallback
        out = out.replace(field, escape(replacement) if as_html else replacement)
    return out


def fallback_of(campaign) -> str:
    return (campaign.first_name_fallback or "").strip() or DEFAULT_FALLBACK


def uses_first_name(campaign) -> bool:
    return "{FirstName}" in (campaign.subject or "") or "{FirstName}" in (campaign.body_html or "")


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


def rendered_for(campaign, contact, *, actor=None, test=False) -> tuple[str, str, str]:
    """`(subject, html, text)` for one person, merged. With no person (the
    preview, or a test with nobody chosen), each field is its bracketed
    placeholder. `test` puts the test copy's line at the top."""
    if contact is None:
        values, fallback = dict(PLACEHOLDERS), PLACEHOLDERS["{FirstName}"]
    else:
        values = merge_values(contact, sender_name(campaign, actor), campaign.tenant)
        fallback = fallback_of(campaign)
    subject = merge(campaign.subject, values, as_html=False, fallback=fallback)
    body = merge(campaign.body_html, values, as_html=True, fallback=fallback)
    if test:
        body = _with_test_line(body)
    html = as_is_document(body) if campaign.send_as_is else body
    return subject, html, text_of(body)


def _with_test_line(body: str) -> str:
    """The test copy's line, first thing in the body (after <body> for a
    whole document)."""
    line = (f'<p style="background:#FFF4CE;padding:8px 12px;margin:0 0 12px;">'
            f"{escape(TEST_LINE)}</p>")
    if re.search(r"<body\b[^>]*>", body, re.IGNORECASE):
        return re.sub(r"(<body\b[^>]*>)", lambda m: m.group(1) + line, body, count=1,
                      flags=re.IGNORECASE)
    return line + body


def missing_first_names(campaign, contacts) -> list:
    """Who, of these, has no first name, when the email uses {FirstName}."""
    if not uses_first_name(campaign):
        return []
    return [c for c in contacts if not (c.first_name or "").strip()]


def _files(campaign) -> list:
    return [(row.stored_file, row.filename)
            for row in CampaignAttachment.all_objects.filter(campaign=campaign)
            .select_related("stored_file")]


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
    """"Enroll and queue": for each person, their enrolment in the campaign and
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
    # The campaign's own files, onto each draft: the same stored file, never
    # copied bytes, so ten drafts do not store a flyer ten times.
    files = _files(campaign)
    for contact in contacts:
        why = unsendable(contact, campaign)
        if why:
            skipped.append({"contact": str(contact.pk),
                            "name": f"{contact.first_name} {contact.last_name}".strip(),
                            "detail": why})
            continue
        subject, html, text = rendered_for(campaign, contact, actor=actor)
        mailbox, address = sender.choose(
            campaign.tenant, campaign.created_by or actor, P.CAMPAIGN,
            override=campaign.sender, company=contact.company if contact.company_id else None)
        message = outbox.create_message(
            tenant=campaign.tenant, producer=P.CAMPAIGN, category="marketing",
            to_contact=contact, to_address=contact.primary_email,
            subject=subject, body_text=text, body_html=html, actor=actor,
            # Each recipient's From (2026-10-28): the campaign's own choice, or
            # their company's default mailbox, or the sender's, as the Outbox.
            mailbox=mailbox, from_address=address, send_by=send_by,
            source_type="campaign", source_id=campaign.pk, attachments=files)
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
    subject, html, text = rendered_for(campaign, contact, actor=actor, test=True)
    # The campaign's files, as a queued copy carries them (owner, 2026-10-20).
    return outbox.create_message(
        tenant=campaign.tenant, producer=P.CAMPAIGN, category="marketing",
        to_address=address, subject=f"[Test] {subject}", body_text=text, body_html=html,
        actor=actor, force_direct=True, attachments=_files(campaign),
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



# ------------------------------------------------------- the campaign's files

def add_attachment(campaign, *, upload, actor) -> CampaignAttachment:
    """One more file on the campaign, at most three, each within the Outbox's
    own size limit. Drafts made from then on carry it."""
    from apps.crm.views import MAX_ATTACHMENT_BYTES
    from apps.tenancy import storage

    if CampaignAttachment.all_objects.filter(campaign=campaign).count() >= MOST_ATTACHMENTS:
        raise CampaignRefused(f"A campaign carries at most {MOST_ATTACHMENTS} files. "
                              "Remove one first.")
    if upload.size > MAX_ATTACHMENT_BYTES:
        raise CampaignRefused(f"{upload.name} is {upload.size // 1024} KB. The limit is "
                              f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB per file.")
    stored = storage.save(
        tenant=campaign.tenant, content=upload.read(),
        object_key=storage.object_key(f"campaigns/{campaign.tenant.slug}/{campaign.pk}",
                                      upload.name),
        content_type=upload.content_type or "application/octet-stream",
        purpose="campaign_attachment")
    row = CampaignAttachment.all_objects.create(tenant=campaign.tenant, campaign=campaign,
                                                stored_file=stored,
                                                filename=upload.name[:255])
    AuditEvent.all_objects.create(
        tenant_id=campaign.tenant_id, actor=actor, verb="campaign.file_added",
        target_type="campaign", target_id=campaign.pk, payload={"file": row.filename})
    return row


def remove_attachment(row, *, actor) -> None:
    """Off the campaign. Drafts already made keep their copy of it."""
    AuditEvent.all_objects.create(
        tenant_id=row.tenant_id, actor=actor, verb="campaign.file_removed",
        target_type="campaign", target_id=row.campaign_id, payload={"file": row.filename})
    row.delete()


# ------------------------------------------------------ when it is sent

def check_follow_through(campaign, *, stage) -> None:
    """The stage must be one of this practice's."""
    if stage is not None and stage.tenant_id != campaign.tenant_id:
        raise CampaignRefused("That stage is not in this practice.", status=404)


def after_sent(message, *, actor=None) -> dict:
    """Owner, 2026-10-19: what the campaign says happens when it is sent, for
    the one person this draft went to. Called by the Outbox only once the
    draft is sent; anything else (refused, deleted, expired, suppressed) never
    reaches here. Returns what was done, for the caller and the tests."""
    from apps.crm.models import Enrollment
    from apps.crm.services import enrollment, pipeline

    done = {"moved": False, "enrolled": False, "skipped": ""}
    if message.producer != P.CAMPAIGN or message.state != S.SENT \
            or message.source_type != "campaign" or not message.to_contact_id:
        return done
    recipient = CampaignRecipient.all_objects.filter(
        outbox_message=message, ended_at__isnull=True).select_related(
        "campaign", "campaign__on_sent_stage", "contact").first()
    if recipient is None:
        return done
    campaign, contact = recipient.campaign, recipient.contact
    if contact.deleted_at is not None or _left_marketing(contact):
        return done
    reason = f"Campaign \u201c{campaign.name}\u201d was sent"
    stage = campaign.on_sent_stage
    if stage is not None and stage.tenant_id == contact.tenant_id:
        done["moved"] = pipeline.change_stage(contact, stage, actor=actor,
                                              reason=reason) is not None
    cadence = campaign.on_sent_cadence
    if cadence:
        program = Enrollment.Program.REFERRAL_TOUCHES
        if enrollment.is_enrolled(contact, program):
            done["skipped"] = "already on referral touches"
        elif not enrollment._is_partner(contact):
            done["skipped"] = "not a referral partner"
        else:
            contact.referral_cadence = cadence
            contact.save(update_fields=["referral_cadence", "updated_at"])
            enrollment.enroll(contact, program, actor=actor,
                              source=f"campaign \u201c{campaign.name}\u201d")
            done["enrolled"] = True
        if done["skipped"]:
            AuditEvent.all_objects.create(
                tenant_id=contact.tenant_id, actor=actor,
                verb="campaign.enrolment_skipped", target_type="contact",
                target_id=contact.pk,
                payload={"campaign": str(campaign.pk), "campaign_name": campaign.name,
                         "why": done["skipped"]})
    return done


def _left_marketing(contact) -> bool:
    return EmailSuppression.all_objects.filter(
        tenant_id=contact.tenant_id, contact=contact, category="marketing",
        lifted_at__isnull=True).exists()
