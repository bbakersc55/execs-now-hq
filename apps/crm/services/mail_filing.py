"""The Mail tab's filing (2026-10-28): new mail in a mailbox, kept when it is
to or from a contact or a company's domain, and never stored otherwise.

**Only a mailbox with "File mail with contacts and companies" on** is read
this way, and only with the read grant it already holds for replies. What a
mailbox's replies poll reads is unchanged (`inbound_poll`): the threads the
app started.

**Nothing personal is stored.** A message is looked at by its envelope first
(From, To and Cc, from the listing): the practice's own addresses (its
people, its mailboxes, its practice address) are set aside, and only when
someone left is a contact, or at a company's domain, is the message fetched
and kept. A message between the practice's own people, or to anyone the CRM
does not know, is passed over and leaves nothing behind, not even in the
unmatched queue.

**Idempotent**, by the provider's message id, like every other path in: a
message the app sent, or a reply already collected, is not stored twice.
"""

from __future__ import annotations

from email.utils import getaddresses, parseaddr

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    CompanyDomain, ContactEmail, EmailMessage, EmailThread,
)
from apps.crm.services import inbound, mailboxes, transport

FILED = "mailbox_filed"


def own_addresses(tenant) -> set[str]:
    """Every address the practice itself writes from."""
    from apps.tenancy.models import Membership

    out = {(tenant.from_address or "").lower()}
    out.update(a.lower() for a in Membership.all_objects.filter(
        tenant=tenant, revoked_at__isnull=True, user__isnull=False,
    ).exclude(role__in=["FCC", "ECC"]).values_list("user__email", flat=True) if a)
    for mailbox in mailboxes.of_tenant(tenant):
        out.add(mailbox.email_address.lower())
        out.update(mailboxes.addresses(mailbox))
    return {a for a in out if a}


def _addresses(*values) -> list[str]:
    return [a.strip().lower() for _, a in getaddresses([v for v in values if v]) if a]


def who(tenant, envelope, own) -> tuple:
    """(contact, company) for an envelope, or (None, None). The sender first
    when it is not the practice's own, then everyone it was sent to."""
    from apps.crm.models import Company

    sender = _addresses(envelope.get("from", ""))
    others = [a for a in sender + _addresses(envelope.get("to", ""),
                                            envelope.get("cc", "")) if a not in own]
    for address in others:
        row = (ContactEmail.objects.filter(address__iexact=address,
                                           contact__deleted_at__isnull=True)
               .select_related("contact", "contact__company").first())
        if row is not None:
            return row.contact, row.contact.company
    for address in others:
        domain = address.rsplit("@", 1)[-1]
        found = CompanyDomain.objects.filter(domain__iexact=domain,
                                             company__deleted_at__isnull=True) \
            .select_related("company").first()
        if found is not None and not found.company.is_practice:
            return None, found.company
    return None, None


def _known(tenant, provider, message_id, internet_id) -> bool:
    if inbound.already_have(tenant, message_id, provider):
        return True
    ours = EmailMessage.objects.filter(direction="outbound")
    return ours.filter(provider_message_id=message_id).exists() or (
        bool(internet_id) and ours.filter(message_id_header=internet_id).exists())


def _thread(tenant, mailbox, key, contact, company, subject):
    field = "graph_conversation_id" if mailbox.provider == "microsoft" else "gmail_thread_id"
    if key:
        found = EmailThread.objects.filter(mailbox=mailbox, **{field: key}).first() or (
            EmailThread.objects.filter(mailbox__isnull=True, **{field: key}).first()
            if mailbox.is_own else None)
        if found is not None:
            return found
    return EmailThread.objects.create(
        tenant=tenant, thread_token=EmailThread.new_token(), mailbox=mailbox,
        contact=contact, client_company=company, subject=subject[:255], **{field: key or ""})


@transaction.atomic
def _keep(tenant, mailbox, payload, *, contact, company, own, client):
    provider = inbound.provider_of(payload)
    key = payload.get("conversationId") if provider == "microsoft" else payload.get("threadId")
    from_address = parseaddr(inbound.header(payload, "From"))[1].lower()
    outbound = from_address in own
    subject = inbound.header(payload, "Subject")
    thread = _thread(tenant, mailbox, key or "", contact, company, subject)
    if thread.mailbox_id is None:
        thread.mailbox = mailbox
    text, html = inbound.bodies(payload)
    when = inbound._received_at(payload)
    message = EmailMessage.objects.create(
        tenant=tenant, thread=thread, direction="outbound" if outbound else "inbound",
        provider=provider, provider_message_id=payload.get("id") or "",
        from_address=from_address[:254],
        to_addresses=_addresses(inbound.header(payload, "To")),
        cc_addresses=_addresses(inbound.header(payload, "Cc")),
        subject=subject[:255], body_html=html, body_text=text,
        body_stripped=inbound.strip_quoted(text), raw=payload,
        contact=contact or thread.contact, matched_by=FILED,
        received_at=None if outbound else when, sent_at=when if outbound else None,
        message_id_header=inbound.header(payload, "Message-ID")[:255],
        in_reply_to=inbound.header(payload, "In-Reply-To")[:255],
        references=inbound.header(payload, "References"),
        gmail_message_id=(payload.get("id") or "") if provider == "gmail" else "",
        gmail_thread_id=payload.get("threadId") or "",
    )
    if not outbound:
        inbound._store_attachments(tenant, message, payload, client=client)
    if thread.last_message_at is None or when > thread.last_message_at:
        thread.last_message_at = when
    thread.save(update_fields=["mailbox", "last_message_at", "updated_at"])
    return message


def file_mailbox(mailbox, *, client=None, limit=mailboxes.FILE_PER_RUN) -> dict:
    """One run over one mailbox. Moves its cursor past what it looked at."""
    tenant = mailbox.tenant
    counts = {"looked_at": 0, "kept": 0, "passed_over": 0, "already_had": 0}
    if not (mailbox.files_mail and mailboxes.reads(mailbox)):
        return counts
    mailboxes.file_start(mailbox)
    if client is None:
        client = reader_for(mailbox)
    own = own_addresses(tenant)
    try:
        listed = client.listing(mailbox.files_after, limit=limit)
    except transport.TransportUnavailable as exc:
        mailbox.files_error = str(exc)
        mailbox.save(update_fields=["files_after", "files_error", "updated_at"])
        counts["errors"] = 1
        return counts
    for envelope in listed:
        counts["looked_at"] += 1
        if _known(tenant, mailbox.provider, envelope["id"], envelope.get("message_id", "")):
            counts["already_had"] += 1
        else:
            contact, company = who(tenant, envelope, own)
            if contact is None and company is None:
                counts["passed_over"] += 1
            else:
                payload = client.full(envelope)
                if payload:
                    _keep(tenant, mailbox, payload, contact=contact, company=company, own=own,
                          client=client)
                    counts["kept"] += 1
        if envelope.get("at") and envelope["at"] > mailbox.files_after:
            mailbox.files_after = envelope["at"]
    mailbox.files_error = ""
    mailbox.save(update_fields=["files_after", "files_error", "updated_at"])
    return counts


def reader_for(mailbox):
    connection = mailbox.connection
    if mailbox.provider == "microsoft":
        from apps.crm.services.graph import GraphReader

        return GraphReader(connection)
    return transport.GmailReader(connection)
