"""The Outbox — both the approval queue AND the complete send log (FR-1.15).

If a message left the app, there is a row here. Rows a human explicitly clicked
are written directly as `sent` (FR-1.15b); everything else enters at
`pending_approval` and expires rather than sending (FR-1.18).
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage as DjangoEmailMessage
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


def reply_to_for(tenant, thread):
    """FR-6.3b — the same token on BOTH transports.

    Postmark app mail and Gmail personal sends carry an identical Reply-To, so a
    client's reply threads whichever way the message went out.
    """
    return f"reply+{thread.thread_token}@{tenant.inbound_domain}"


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
    message = OutboxMessage.all_objects.create(
        tenant=tenant,
        state=S.SENT if direct else S.PENDING_APPROVAL,
        producer=producer,
        to_contact=to_contact,
        to_address=to_address,
        from_address=from_address or tenant.from_address,
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
    """FR-0.7 / H6 — the dev-outbox guard lives here, on the one path out."""
    from apps.accounts.mailer import is_real_send_allowed

    dev_real = settings.IS_LOCAL and is_real_send_allowed(message.to_address)

    email = DjangoEmailMessage(
        subject=message.subject,
        body=message.body_text,
        from_email=message.from_address,
        to=[message.to_address],
        headers={"Reply-To": reply_to_for(message.tenant, message.thread)}
        if message.thread else {},
    )
    for attachment in message.attachments.all():
        email.attach(attachment.filename, b"", "application/pdf")
    email.send(fail_silently=False)

    message.state = S.SENT
    message.sent_at = timezone.now()
    message.dev_real_send = dev_real
    message.save(update_fields=["state", "sent_at", "dev_real_send", "updated_at"])

    if message.thread is not None:
        EmailMessage.all_objects.create(
            tenant=message.tenant, thread=message.thread, direction="outbound",
            provider=message.sent_via, from_address=message.from_address,
            to_addresses=[message.to_address], subject=message.subject,
            body_text=message.body_text, contact=message.to_contact,
            sent_at=message.sent_at,
        )
        message.thread.last_message_at = message.sent_at
        message.thread.save(update_fields=["last_message_at", "updated_at"])

    AuditEvent.all_objects.create(
        tenant=message.tenant, actor=actor, verb="email.sent",
        target_type="outbox_message", target_id=message.pk,
        payload={
            "producer": message.producer, "to": message.to_address,
            "dev_real_send": dev_real, "via": message.sent_via,
        },
    )
    return message


# ------------------------------------------------------------- producers

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
