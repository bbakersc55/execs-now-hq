"""The Outbox — both the approval queue AND the complete send log (FR-1.15).

If a message left the app, there is a row here. Rows a human explicitly clicked
are written directly as `sent` (FR-1.15b); everything else enters at
`pending_approval` and expires rather than sending (FR-1.18).
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.crm.models import EmailMessage, EmailThread, OutboxMessage
from apps.tenancy.models import AuditEvent, Role

P = OutboxMessage.Producer
S = OutboxMessage.State


class SendNotPermitted(Exception):
    """Raised when a role attempts a send it may not make (H7)."""


# --------------------------------------------------------------- threading

def thread_for(tenant, contact=None, subject="", client_company=None):
    """Carve-back: every outbound message belongs to a thread with a token."""
    thread = None
    if contact is not None:
        thread = EmailThread.all_objects.filter(tenant=tenant, contact=contact).first()
    if thread is None:
        thread = EmailThread.all_objects.create(
            tenant=tenant, contact=contact, client_company=client_company,
            thread_token=EmailThread.new_token(), subject=subject,
        )
    return thread


def thread_headers_for(tenant, thread):
    """FR-6.2 — how a reply finds its way home in Beta.

    There is no `reply+<token>@inbound` address: Beta has no inbound domain,
    because all app mail goes through the tenant's Gmail (transport change,
    owner decision). The token instead rides in the Message-ID and in a custom
    header, and a reply is recovered from its Gmail thread id or from
    In-Reply-To / References quoting a Message-ID we issued.
    """
    from apps.crm.services.transport import THREAD_HEADER, message_id_for

    return {
        "Message-ID": message_id_for(tenant, thread),
        THREAD_HEADER: thread.thread_token,
    }


def last_message_id_for(thread):
    """The Message-ID to reply to, so a follow-up threads in the client's
    mail client rather than starting a new conversation."""
    last = (
        EmailMessage.all_objects.filter(
            tenant_id=thread.tenant_id, thread_id=thread.pk,
        )
        .exclude(message_id_header="")
        .order_by("-created_at")
        .first()
    )
    return last.message_id_header if last else ""


# ---------------------------------------------------------------- creation

def _direct_to_sent(producer, role):
    """FR-1.15b plus the two role-dependent producers."""
    if producer in OutboxMessage.ALWAYS_DIRECT_TO_SENT:
        return True
    if producer == P.PRECALL_INVITE:
        # H7a — template-only, non-AI, from the tenant address. The one send a
        # VA may make directly.
        return True
    if producer == P.MANUAL:
        # FF/CF send as themselves; a VA's manual mail becomes a draft (FR-1.19a).
        return role in (Role.FF, Role.CF)
    return False


@transaction.atomic
def create_message(*, tenant, producer, to_address, subject, body_text,
                   role=None, actor=None, to_contact=None, body_html="",
                   is_ai_generated=False, warning="", send_by=None,
                   from_address=None, sent_via="postmark", thread=None,
                   source_type="", source_id=None, attachments=()):
    """Single entry point. Nothing else in the codebase writes an OutboxMessage."""
    if thread is None:
        thread = thread_for(tenant, contact=to_contact, subject=subject)

    direct = _direct_to_sent(producer, role)
    if not from_address:
        # FR-1.15c — the per-producer sender default. Resolved once, HERE, and
        # recorded on the row, so the log says what actually went out even if
        # the preference changes afterwards.
        from apps.crm.services import sender as sender_service

        from_address = sender_service.resolve_from(tenant, actor, producer)
    message = OutboxMessage.all_objects.create(
        tenant=tenant,
        state=S.SENT if direct else S.PENDING_APPROVAL,
        producer=producer,
        to_contact=to_contact,
        to_address=to_address,
        from_address=from_address,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        is_ai_generated=is_ai_generated,
        warning=warning,
        send_by=send_by,
        thread=thread,
        sent_via=sent_via,
        source_type=source_type,
        source_id=source_id,
    )
    for stored_file, filename in attachments:
        from apps.crm.models import OutboxAttachment

        OutboxAttachment.all_objects.create(
            tenant=tenant, outbox_message=message,
            stored_file=stored_file, filename=filename,
        )

    if direct:
        _deliver(message, actor=actor)
    return message


# --------------------------------------------------------------- approval

def approve(message, *, actor, role):
    """FR-1.17, FR-1.19. A VA cannot approve (H7)."""
    if role not in (Role.FF, Role.CF):
        raise SendNotPermitted("Only a founder or contractor fractional may send.")
    if message.state not in (S.DRAFT, S.PENDING_APPROVAL):
        raise SendNotPermitted(f"Cannot approve a message in state {message.state}.")

    message.state = S.APPROVED
    message.approved_by = actor
    message.approved_at = timezone.now()
    message.save(update_fields=["state", "approved_by", "approved_at", "updated_at"])
    _deliver(message, actor=actor)
    AuditEvent.all_objects.create(
        tenant=message.tenant, actor=actor, verb="outbox.approved",
        target_type="outbox_message", target_id=message.pk,
        payload={"producer": message.producer, "to": message.to_address},
    )
    return message


def reject(message, *, actor):
    """FR-1.17. Rejecting sends nothing, so it is safe for a VA (matrix 5.4)."""
    message.state = S.REJECTED
    message.save(update_fields=["state", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=message.tenant, actor=actor, verb="outbox.rejected",
        target_type="outbox_message", target_id=message.pk, payload={},
    )
    return message


def expire_due(tenant, *, now=None):
    """FR-1.18 — an item that reaches its send-by without approval EXPIRES.

    It does not send. This is the behaviour that makes an unattended queue safe.
    """
    now = now or timezone.now()
    stale = OutboxMessage.all_objects.filter(
        tenant=tenant, state__in=[S.DRAFT, S.PENDING_APPROVAL],
        send_by__isnull=False, send_by__lte=now,
    )
    ids = list(stale.values_list("pk", flat=True))
    stale.update(state=S.EXPIRED, updated_at=now)
    for pk in ids:
        AuditEvent.all_objects.create(
            tenant=tenant, verb="outbox.expired",
            target_type="outbox_message", target_id=pk, payload={},
        )
    return len(ids)


# --------------------------------------------------------------- delivery

def _deliver(message, *, actor=None):
    """The one path out of the app.

    FR-0.7 / H6 — the dev-outbox guard lives here and is unchanged by the
    transport switch: it governs WHO may receive real mail, not which service
    carries it. On a localhost build everything goes to the dev outbox unless
    the recipient is an exact match in DEV_REAL_SEND_ALLOWLIST.
    """
    from apps.accounts.mailer import is_real_send_allowed
    from apps.crm.services.transport import (
        DevOutboxTransport, TransportUnavailable, get_transport,
    )

    dev_real = settings.IS_LOCAL and is_real_send_allowed(
        message.to_address, message.tenant
    )
    use_real_transport = (not settings.IS_LOCAL) or dev_real
    transport = get_transport() if use_real_transport else DevOutboxTransport()

    thread = message.thread
    if thread is None:
        # `thread` is SET_NULL, so a deleted thread would otherwise reach the
        # transport as None and crash the send. Every outbound message needs a
        # thread token (AC-6.1), so make one rather than fail the delivery.
        thread = thread_for(message.tenant, contact=message.to_contact,
                            subject=message.subject)
        message.thread = thread
        message.save(update_fields=["thread", "updated_at"])
    in_reply_to = last_message_id_for(thread) if thread else ""

    # The bytes, not a placeholder. This read used to be a literal `b""`, so
    # every attachment the app has ever delivered was an empty file with the
    # right name — visible in the Outbox, visible in Gmail, and broken only once
    # the recipient opened it.
    from apps.tenancy import storage

    attachments = []
    for attachment in message.attachments.select_related("stored_file"):
        try:
            content = storage.read(attachment.stored_file)
        except (storage.MissingContent, storage.StorageUnavailable) as exc:
            # Fail the send. Delivering the message without the file it says is
            # attached is worse than not delivering it: the recipient cannot
            # tell, and neither can the sender. An unreachable bucket fails the
            # same way, and the message names which of the two it was.
            raise TransportUnavailable(
                f"{message.subject!r} could not be sent: {exc}"
            ) from exc
        attachments.append((
            attachment.filename, content,
            attachment.stored_file.content_type or "application/pdf",
        ))

    result = transport.send(
        tenant=message.tenant,
        to_address=message.to_address,
        subject=message.subject,
        body_text=message.body_text,
        thread=thread,
        in_reply_to=in_reply_to,
        attachments=attachments,
    )

    message.state = S.SENT
    message.sent_at = timezone.now()
    message.dev_real_send = dev_real
    message.sent_via = result["provider"]
    message.provider_message_id = result.get("provider_message_id", "")
    if result.get("from_address"):
        message.from_address = result["from_address"]
    message.save(update_fields=[
        "state", "sent_at", "dev_real_send", "sent_via",
        "provider_message_id", "from_address", "updated_at",
    ])

    if thread is not None:
        EmailMessage.all_objects.create(
            tenant=message.tenant, thread=thread, direction="outbound",
            provider=result["provider"],
            provider_message_id=result.get("provider_message_id", ""),
            from_address=message.from_address,
            to_addresses=[message.to_address], subject=message.subject,
            body_text=message.body_text, contact=message.to_contact,
            sent_at=message.sent_at,
            message_id_header=result.get("message_id_header", ""),
            in_reply_to=in_reply_to,
            gmail_message_id=result.get("gmail_message_id", ""),
            gmail_thread_id=result.get("gmail_thread_id", ""),
        )
        updates = ["last_message_at", "updated_at"]
        thread.last_message_at = message.sent_at
        # Gmail assigns the thread id on the first send; remembering it is what
        # lets Tier 2 polling recognise the reply later.
        if result.get("gmail_thread_id") and not thread.gmail_thread_id:
            thread.gmail_thread_id = result["gmail_thread_id"]
            updates.insert(0, "gmail_thread_id")
        thread.save(update_fields=updates)

    AuditEvent.all_objects.create(
        tenant=message.tenant, actor=actor, verb="email.sent",
        target_type="outbox_message", target_id=message.pk,
        payload={
            "producer": message.producer, "to": message.to_address,
            "dev_real_send": dev_real, "via": result["provider"],
        },
    )
    return message


# ------------------------------------------------------------- producers

def create_manual_draft(contact, *, subject, body_text, actor=None):
    """A one-off email to one contact, queued for approval.

    Deliberately NOT a direct-to-`sent` producer even though a human typed it:
    the bulk path composes many of these at once from a template, and "the click
    is the approval" stops being true when one click produced forty messages.
    """
    from apps.crm.services import sender as sender_service

    signature_text, _ = sender_service.signature(contact.tenant, actor)
    body = body_text.replace("{first_name}", contact.first_name or "")
    if signature_text and signature_text not in body:
        body = f"{body.rstrip()}\n\n{signature_text}"
    return create_message(
        tenant=contact.tenant, producer=P.MANUAL,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=subject or f"A note from {contact.tenant.name}",
        body_text=body, actor=actor,
        send_by=timezone.now() + timezone.timedelta(days=7),
        source_type="contact", source_id=contact.pk,
    )


def queue_stage_email(contact, rule, *, actor=None):
    """FR-1.12 — a stage rule NEVER sends. Send-by defaults to 7 days."""
    template = rule.email_template
    send_by = timezone.now() + timezone.timedelta(days=rule.send_by_offset_days)
    return create_message(
        tenant=contact.tenant, producer=P.STAGE_RULE,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=template.subject if template else "Following up",
        body_text=template.body if template else "",
        send_by=send_by, actor=actor,
        source_type="stage_automation", source_id=rule.pk,
    )
