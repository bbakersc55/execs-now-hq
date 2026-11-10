"""A request from the marketing site's "Request demo access" form (2026-11-09).

The site's own server forwards the form to `POST /api/public/leads`
(`apps/crm/views_site_leads.py`); this is what a valid one does, all of it in
one practice and one transaction:

1. the contact, found by email address or made, typed a prospect;
2. their company, by the address's domain, or by the practice name they typed
   when the address is a public mail provider's (none when that is blank);
3. the tag "Website lead";
4. **New, in the "Website leads" pipeline** (owner, 2026-11-09), for someone
   not in it yet; someone already there stays at their stage. A sales
   position is untouched: a form on the website is not a reason to move a
   deal backwards. A practice without that pipeline (one from before it, not
   yet added in Settings -> Stage rules) gets the sales pipeline's entry
   stage instead, for someone not in it yet;
5. a note on the contact with what the form said;
6. a notice to the practice owner;
7. the reply, from the "Website reply" template, **waiting in the Outbox for
   approval**. Nothing is sent from here.

An existing contact's name, company and discipline are kept: the practice's
record is what the practice wrote. Only what is missing is filled in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

log = logging.getLogger(__name__)

TAG = "Website lead"
SOURCE = "Website"
#: How long the reply waits for approval before it expires unsent. Four days,
#: so a request on a Friday evening is still answerable on Monday.
REPLY_WAITS = timezone.timedelta(days=4)

WANTS = {
    "demo_copy": "a private demo copy for 30 days",
    "call": "a call",
}
#: What the reply says comes next, by what they asked for ({NextStep}).
NEXT_STEP = {
    "demo_copy": "your private demo copy, yours to use for 30 days",
    "call": "a few times for a call",
    "": "a private demo copy to try for 30 days, or a few times for a call, "
        "whichever you prefer",
}
#: What the notice says they want.
NOTICE_WANTS = {"demo_copy": "wants a demo copy", "call": "wants a call",
                "": "asked about the product"}
PLATFORMS = {"google": "Google Workspace (Gmail)", "microsoft": "Microsoft 365 (Outlook)"}


class NoPractice(Exception):
    """There is no practice to receive website leads."""


@dataclass(frozen=True)
class Lead:
    name: str
    email: str
    practice_name: str = ""
    discipline: str = ""
    email_platform: str = ""
    wants: str = ""
    message: str = ""


def lead_practice():
    """The practice website leads land in: `SITE_LEAD_PRACTICE` (a slug) when
    set, otherwise the platform owner's own practice (Executives Now, the one
    platform mail is sent from). Only an active practice; otherwise None."""
    from apps.tenancy.models import Tenant

    slug = (getattr(settings, "SITE_LEAD_PRACTICE", "") or "").strip()
    if slug:
        practice = Tenant.objects.filter(slug=slug).first()
    else:
        from apps.platform.mail import PlatformMailUnavailable, sender_tenant

        try:
            practice = sender_tenant()
        except PlatformMailUnavailable:
            practice = None
    if practice is None or practice.status != Tenant.Status.ACTIVE:
        return None
    return practice


def practice_owner(practice):
    """The practice owner who signs the reply: the first, if there are several."""
    from apps.tenancy.models import Membership, Role

    row = (Membership.all_objects.select_related("user")
           .filter(tenant=practice, role=Role.FF, revoked_at__isnull=True)
           .order_by("created_at").first())
    return row.user if row else None


def receive(lead: Lead):
    """Everything a valid lead does. Returns the contact. Raises NoPractice."""
    from apps.tenancy.context import tenant_context

    practice = lead_practice()
    if practice is None:
        raise NoPractice()
    with tenant_context(practice.pk), transaction.atomic():
        return _receive(practice, lead)


def _receive(practice, lead: Lead):
    from apps.crm.services import pipeline as pipeline_service
    from apps.crm.services import referral

    owner = practice_owner(practice)
    contact, existing = _contact_for(practice, lead, owner)
    referral.add_type(contact, "prospect")
    placed = _place(contact, pipeline_service)
    note = _note(practice, contact, lead)
    _tell(practice, contact, lead, note, existing=existing)
    _queue_reply(practice, contact, lead, owner)
    # Ids only: enough to find the lead from the log, nothing the visitor typed.
    log.info("Website lead received: contact %s (%s) in practice %s, %s.", contact.pk,
             "existing contact" if existing else "new contact", practice.pk, placed)
    return contact


# ------------------------------------------------------------- the contact

def _split(name: str) -> tuple[str, str]:
    parts = name.split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:])
    return first[:120], last[:120]


def _contact_for(practice, lead: Lead, owner):
    """(contact, existed). Found by the address, in this practice only."""
    from apps.crm.models import Contact, ContactEmail
    from apps.crm.services.importer import _merge_tags

    row = (ContactEmail.all_objects
           .filter(tenant=practice, address__iexact=lead.email,
                   contact__deleted_at__isnull=True, contact__merged_into__isnull=True)
           .select_related("contact").order_by("contact__created_at").first())
    if row is None:
        first, last = _split(lead.name)
        contact = Contact.all_objects.create(
            tenant=practice, first_name=first, last_name=last, owner=owner,
            source=SOURCE, tags=[TAG], discipline=lead.discipline,
            company=_company_for(practice, lead),
        )
        ContactEmail.all_objects.create(tenant=practice, contact=contact,
                                        address=lead.email, is_primary=True)
        return contact, False

    contact = row.contact
    changed = []
    tags = _merge_tags(contact.tags, [TAG])
    if tags != list(contact.tags):
        contact.tags = tags
        changed.append("tags")
    if not contact.company_id:
        company = _company_for(practice, lead)
        if company is not None:
            contact.company = company
            changed.append("company")
    if not contact.discipline and lead.discipline:
        contact.discipline = lead.discipline
        changed.append("discipline")
    if not contact.source:
        contact.source = SOURCE
        changed.append("source")
    if changed:
        contact.save(update_fields=[*changed, "updated_at"])
    return contact, True


def _company_for(practice, lead: Lead):
    """By the address's domain; for a public mail provider's address, by the
    practice name they typed; none when that is blank too."""
    from apps.crm.models import Company, CompanyDomain
    from apps.meetings.matching import domain_for_new_company

    domain = domain_for_new_company(lead.email)
    name = " ".join(lead.practice_name.split())[:200]
    if domain:
        row = (CompanyDomain.all_objects
               .filter(tenant=practice, domain__iexact=domain,
                       company__deleted_at__isnull=True, company__is_practice=False)
               .select_related("company").first())
        if row is not None:
            return row.company
    if not name and not domain:
        return None
    company = None
    if name:
        company = Company.all_objects.filter(
            tenant=practice, name__iexact=name, deleted_at__isnull=True,
            is_practice=False).first()
    if company is None:
        company = Company.all_objects.create(tenant=practice, name=name or domain)
    if domain and not CompanyDomain.all_objects.filter(tenant=practice,
                                                       domain__iexact=domain).exists():
        CompanyDomain.all_objects.create(tenant=practice, company=company, domain=domain)
    return company


def _place(contact, pipeline_service):
    """Website leads' New, or without that pipeline the sales pipeline's
    entry stage; nobody is moved who is in that pipeline already. Returns
    where they are, in words, for the log."""
    website = pipeline_service.website_pipeline(contact.tenant)
    target = website or pipeline_service.sales_pipeline(contact.tenant)
    if target is None:
        log.error("Website lead: the practice %s has no sales pipeline; contact %s was "
                  "not placed.", contact.tenant_id, contact.pk)
        return "not placed (no pipeline)"
    held = pipeline_service.position_for(contact, target)
    if held is not None:
        return f"already at {held.stage.label} in {target.name}"
    stage = pipeline_service.entry_stage(target)
    if stage is None:
        return f"not placed ({target.name} has no stages)"
    pipeline_service.change_stage(contact, stage, reason="website form")
    return f"placed at {stage.label} in {target.name}"


# ------------------------------------------------------------- what they said

def _note(practice, contact, lead: Lead):
    from apps.crm.models import Contact
    from apps.notes.models import Note

    lines = ["Asked on the website's \"Request demo access\" form."]
    if lead.practice_name:
        lines.append(f"Practice: {lead.practice_name}")
    if lead.discipline:
        lines.append(f"Discipline: {Contact.Discipline(lead.discipline).label}")
    if lead.email_platform:
        lines.append(f"Email: {PLATFORMS[lead.email_platform]}")
    if lead.wants:
        lines.append(f"Wants: {WANTS[lead.wants]}")
    if lead.message:
        lines.append(f"Message: {lead.message}")
    return Note.all_objects.create(
        tenant=practice, contact=contact, title="Website request", title_is_auto=False,
        body="\n".join(lines), source=Note.Source.WEBSITE,
    )


def _tell(practice, contact, lead: Lead, note, *, existing: bool):
    from apps.notify.models import Kind
    from apps.notify.service import tell
    from apps.tenancy.models import Membership, Role

    who = ", ".join(part for part in (lead.name, lead.practice_name) if part)
    text = f"Website lead: {who}, {NOTICE_WANTS[lead.wants]}."
    if existing:
        text += " Already one of your contacts."
    for member in Membership.all_objects.filter(tenant=practice, role=Role.FF,
                                                revoked_at__isnull=True):
        tell(tenant_id=practice.pk, recipient_id=member.user_id, kind=Kind.NOTICE,
             title="Website lead", text=text, url=f"/contacts/{contact.pk}",
             source_type="website_lead", source_id=note.pk)


def _queue_reply(practice, contact, lead: Lead, owner):
    """The reply, from the practice's "Website reply" template, for approval."""
    from apps.crm import template_seed
    from apps.crm.models import EmailTemplate, OutboxMessage
    from apps.crm.services import outbox, templates

    template_seed.seed_tenant(practice)
    template = EmailTemplate.all_objects.get(tenant=practice, original="website_reply")
    subject, body = templates.compose(template, contact, actor=owner,
                                      NextStep=NEXT_STEP[lead.wants])
    return outbox.create_message(
        tenant=practice, producer=OutboxMessage.Producer.WEBSITE_REPLY,
        to_contact=contact, to_address=lead.email, subject=subject, body_text=body,
        actor=owner, send_by=timezone.now() + REPLY_WAITS,
        source_type="contact", source_id=contact.pk,
    )
