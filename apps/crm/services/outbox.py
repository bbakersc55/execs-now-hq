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

def thread_for(tenant, contact=None, subject="", client_company=None, mailbox=None):
    """Carve-back: every outbound message belongs to a thread with a token.

    With a mailbox (2026-10-28), the contact's thread in that mailbox: a
    conversation lives in one mailbox, and Gmail knows its thread only
    there. A thread from before mailboxes is someone's own mailbox's."""
    thread = None
    if contact is not None:
        # Never a financial thread: that one holds an invoice and its replies,
        # and ordinary mail on it would vanish from an assistant's view.
        threads = EmailThread.all_objects.filter(tenant=tenant, contact=contact,
                                                 is_financial=False)
        if mailbox is None:
            thread = threads.first()
        else:
            thread = threads.filter(mailbox=mailbox).first() or (
                threads.filter(mailbox__isnull=True).first() if mailbox.is_own else None)
    if thread is None:
        thread = EmailThread.all_objects.create(
            tenant=tenant, contact=contact, client_company=client_company,
            thread_token=EmailThread.new_token(), subject=subject, mailbox=mailbox,
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
    if producer == P.PRECALL_QUESTIONS:
        # Same rule as `manual`, and for the same reason: it goes from the
        # fractional's own address and carries an intro they wrote. H7a lets a
        # VA send the *invite* because it is template-only with nothing
        # discretionary in it; this one is not that.
        return role in (Role.FF, Role.CF)
    if producer == P.MANUAL:
        # FF/CF send as themselves; a VA's manual mail becomes a draft (FR-1.19a).
        return role in (Role.FF, Role.CF)
    return False


@transaction.atomic
def create_message(*, tenant, producer, to_address, subject, body_text,
                   role=None, actor=None, to_contact=None, body_html="",
                   is_ai_generated=False, warning="", send_by=None,
                   from_address=None, sent_via="postmark", thread=None,
                   source_type="", source_id=None, attachments=(),
                   deliver_body_text=None, force_direct=False, deliver_body_html=None,
                   category=None, also_to_contact=None, also_to_address="",
                   mailbox=None):
    """Single entry point. Nothing else in the codebase writes an OutboxMessage.

    `deliver_body_text` is for one-time links (magic links, PIN resets): it is
    what the recipient receives, and it is NEVER stored. `body_text` — the copy
    on the Outbox row and the thread, visible to every tenant user — carries the
    same message with the link removed, so no row holds a working credential
    (assumption C3). Only a direct-to-sent message may use it: a draft that
    waits for approval has to be sendable from what is stored.
    """
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        return _suppressed_while_acting(
            tenant=tenant, producer=producer, to_contact=to_contact, to_address=to_address,
            from_address=from_address, subject=subject, body_text=body_text,
            body_html=body_html, is_ai_generated=is_ai_generated,
            source_type=source_type, source_id=source_id,
        )

    from apps.crm.services import mailboxes
    from apps.crm.services import sender as sender_service

    # The mailbox and its From (2026-10-28), resolved once, HERE, and kept on
    # the row: FR-1.15c's per-producer default, then the mailbox defaults
    # (`sender.choose`), or what the producer chose.
    company = (to_contact.company if to_contact is not None and to_contact.company_id
               else getattr(thread, "client_company", None))
    if mailbox is not None:
        from_address = from_address or mailboxes.address_of(mailbox)
    elif from_address:
        mailbox = mailboxes.for_address(tenant, from_address)
    else:
        mailbox, from_address = sender_service.choose(tenant, actor, producer,
                                                      company=company, thread=thread)
    if thread is None:
        thread = thread_for(tenant, contact=to_contact, subject=subject, mailbox=mailbox)

    # `force_direct` is for a message whose human approval happened upstream in
    # its own review queue — a digest approved on the digest screen (FR-3.29),
    # or a deterministic digest the rules say needs no approval (FR-3.27).
    # It does not bypass a gate; it records that one was already passed.
    direct = force_direct or _direct_to_sent(producer, role)
    if (deliver_body_text is not None or deliver_body_html is not None) and not direct:
        raise ValueError("deliver_body_text is only for direct-to-sent producers.")
    from apps.crm.services import unsubscribe

    message = OutboxMessage.all_objects.create(
        tenant=tenant,
        state=S.SENT if direct else S.PENDING_APPROVAL,
        producer=producer,
        # Every email has a category (owner, 2026-09-28): it decides whether
        # an unsubscribe link goes on it and whether a suppression stops it.
        category=category or unsubscribe.category_for(producer),
        to_contact=to_contact,
        to_address=to_address,
        also_to_contact=also_to_contact,
        also_to_address=also_to_address or "",
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
        mailbox=mailbox,
    )
    for stored_file, filename in attachments:
        from apps.crm.models import OutboxAttachment

        OutboxAttachment.all_objects.create(
            tenant=tenant, outbox_message=message,
            stored_file=stored_file, filename=filename,
        )

    if direct:
        _deliver(message, actor=actor, body_text=deliver_body_text,
                 body_html=deliver_body_html)
    return message


def _suppressed_while_acting(*, tenant, producer, to_contact, to_address, from_address,
                             subject, body_text, body_html, is_ai_generated,
                             source_type, source_id):
    """FR-3.42 — no email of any kind leaves while someone acts as another user.

    Checked here, at the single entry point, so a magic link, a cadence
    confirmation or anything added later is covered without knowing about it.
    The row is kept, because the Outbox is the complete record of what the app
    tried to send, but it is never delivered, starts no thread, and the one-time
    body of a link is never stored — exactly as for a real send.
    """
    message = OutboxMessage.all_objects.create(
        tenant=tenant, state=S.SUPPRESSED, producer=producer, to_contact=to_contact,
        to_address=to_address, from_address=from_address or "", subject=subject[:255],
        body_text=body_text, body_html=body_html, is_ai_generated=is_ai_generated,
        source_type=source_type, source_id=source_id,
    )
    AuditEvent.all_objects.create(
        tenant=tenant, verb="email.suppressed", target_type="outbox_message",
        target_id=message.pk,
        payload={"reason": "written while acting as", "producer": producer,
                 "to": to_address, "subject": subject[:200]},
    )
    return message


# --------------------------------------------------------------- approval

def approve(message, *, actor, role):
    """FR-1.17, FR-1.19. A VA cannot approve (H7)."""
    if role not in (Role.FF, Role.CF):
        raise SendNotPermitted("Only the practice owner or an associate can send.")
    # Matrix 13.4c: an invoice is sent on the practice owner's approval alone.
    if message.producer == P.CLIENT_INVOICE and role != Role.FF:
        raise SendNotPermitted("Only the practice owner can send an invoice.")
    if message.state not in (S.DRAFT, S.PENDING_APPROVAL):
        raise SendNotPermitted(f"Cannot approve a message in state {message.get_state_display().lower()}.")
    reason = _suppress_if_unsubscribed(message, actor=actor)
    if reason:
        raise SendNotPermitted(reason)
    from apps.crm.services import mailboxes

    if (refused := mailboxes.refusal(message)):
        raise SendNotPermitted(refused)
    if message.producer == P.SIGNATURE_REQUEST:
        # Its document may have been voided while the email waited.
        from apps.esign import services as esign

        if (refused := esign.send_refusal(message)):
            raise SendNotPermitted(refused)

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
    if message.producer == P.CLIENT_INVOICE:
        from apps.billing import services as billing

        billing.message_sent(message, actor=actor)
    if message.producer == P.REFERRAL_THANKS and message.state == S.SENT:
        # Approved, a thank-you is the referrer's touch (owner, 2026-10-20).
        from apps.crm.services import referrals

        referrals.thanks_sent(message)
    if message.producer == P.SIGNATURE_REQUEST and message.state == S.SENT:
        # Delivered: the document is Sent, and its rules run.
        from apps.esign import services as esign

        esign.request_sent(message, actor=actor)
    if message.producer == P.CAMPAIGN and message.state == S.SENT:
        # "When this campaign is sent" (owner, 2026-10-19): only once it is.
        from apps.crm.services import campaigns

        campaigns.after_sent(message, actor=actor)
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


def switch_refusal(tenant) -> str:
    """Why a practice's mail may not change transport now, or "": nothing may
    be waiting that could still go out through one nobody chose for it."""
    waiting = OutboxMessage.all_objects.filter(
        tenant=tenant, state__in=[S.DRAFT, S.PENDING_APPROVAL, S.APPROVED]).count()
    if not waiting:
        return ""
    return (f"The Outbox has {waiting} message{'' if waiting == 1 else 's'} waiting "
            "(drafts, waiting for approval, or approved and not yet sent). Send or "
            "reject them first, so none goes out through a transport nobody chose "
            "for it.")


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

def recipients_of(message) -> list[str]:
    """Every address the message is for, the first first."""
    return [a for a in (message.to_address, message.also_to_address) if a]


def _suppress_if_unsubscribed(message, *, actor=None) -> str:
    """Owner, 2026-09-28 — the Outbox refuses a category the recipient left,
    and says why. The row is kept, marked suppressed with the reason."""
    from apps.crm.services import unsubscribe

    reason = unsubscribe.refusal(message)
    if reason:
        message.state = S.SUPPRESSED
        message.warning = reason
        message.save(update_fields=["state", "warning", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=message.tenant, actor=actor, verb="email.suppressed",
            target_type="outbox_message", target_id=message.pk,
            payload={"reason": reason, "producer": message.producer,
                     "category": unsubscribe.category_of(message),
                     "to": message.to_address})
    return reason


def _unsubscribe_headers(message) -> dict:
    from apps.crm.services import unsubscribe

    return unsubscribe.headers_for(message)


def _demo_recipient(tenant) -> str:
    """Where a demo message really goes: the redirect, when the demo has one
    and its own send-only connection to send it through; otherwise "", and
    the message is discarded."""
    from apps.crm.services.transport import TransportUnavailable, sending_connection_for
    from config import environment

    redirect = environment.demo_redirect(tenant)
    if not redirect:
        return ""
    try:
        connection = sending_connection_for(tenant)
    except TransportUnavailable:
        return ""
    if (connection.send_as_address or "").lower() != environment.demo_sender():
        return ""
    return redirect


def _with_demo_banner(message, html: str, text: str) -> tuple[str, str]:
    """Who it was for, at the top of both parts."""
    import re

    from django.utils.html import escape

    from config import environment

    contact = message.to_contact
    name = f"{contact.first_name} {contact.last_name}".strip() if contact else ""
    line = environment.demo_banner(name, message.to_address)
    text = f"{line}\n\n{text}"
    if html:
        block = ('<div style="background:#FFF4CE;color:#3B2F00;font:14px/1.4 Arial,'
                 'Helvetica,sans-serif;padding:10px 16px;border-bottom:1px solid #E0C36A">'
                 f"{escape(line)}</div>")
        html, placed = re.subn(r"(<body\b[^>]*>)", lambda m: m.group(1) + block, html,
                               count=1, flags=re.IGNORECASE)
        if not placed:
            html = block + html
    return html, text


def _deliver(message, *, actor=None, body_text=None, body_html=None):
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

    # Checked again here, because a direct-to-sent message (a digest) never
    # passes through `approve`. A suppressed category does not leave.
    if _suppress_if_unsubscribed(message, actor=actor):
        return message
    # A disconnected mailbox sends nothing, and never hands its mail to another.
    from apps.crm.services import mailboxes

    if (refused := mailboxes.refusal(message)):
        raise TransportUnavailable(refused)

    # One check per address (owner, 2026-10-26): real mail leaves a laptop
    # only when every address on it is on the allow-list.
    dev_real = settings.IS_LOCAL and all(
        is_real_send_allowed(address, message.tenant, message.mailbox)
        for address in recipients_of(message))
    # The demo sends only through its redirect (owner, 2026-10-08). Where it
    # can, the one address below replaces the recipient before anything is
    # built; where it cannot (no redirect set, no connection of its own, or
    # the seed is running), the message goes to the dev transport, whose
    # backend there discards it. No branch here sends to `message.to_address`.
    from config import environment

    demo = environment.is_demo()
    demo_to = _demo_recipient(message.tenant) if demo else ""
    use_real_transport = (bool(demo_to) if demo
                          else (not settings.IS_LOCAL) or dev_real)
    mailbox = message.mailbox
    if not use_real_transport:
        transport = DevOutboxTransport()
    elif mailbox is not None and not mailbox.is_own and not demo:
        # A shared or a client's mailbox goes through its own provider.
        transport = get_transport("microsoft" if mailbox.provider == "microsoft" else None)
    else:
        transport = get_transport(tenant=message.tenant)

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

    # A signature request's link is made now and never stored: the row
    # keeps {SignLink} (apps/esign/links.py).
    if message.producer == P.SIGNATURE_REQUEST and body_text is None:
        from apps.esign import services as esign

        body_text, body_html = esign.delivery_text(message)

    # One function decides what leaves, and every preview calls it too.
    from apps.crm.services import email_layout

    html_part, text_part = email_layout.for_delivery(message, body_text=body_text,
                                                     body_html=body_html)
    html_part, inline_images = email_layout.with_logo(html_part, message.tenant)
    from_address = message.from_address
    if demo_to:
        # Mail already for the one person it goes to (a visitor's own sign-in
        # link) needs no banner saying who it was for.
        if demo_to != (message.to_address or "").strip().lower():
            html_part, text_part = _with_demo_banner(message, html_part, text_part)
        from_address = environment.demo_sender()
    result = transport.send(
        tenant=message.tenant,
        to_address=demo_to or message.to_address,
        # The demo's redirect is its only address: a second one never goes.
        also_to=() if demo_to else tuple(recipients_of(message)[1:]),
        subject=message.subject,
        body_text=text_part,
        body_html=html_part,
        thread=thread,
        in_reply_to=in_reply_to,
        attachments=attachments,
        inline_images=inline_images,
        from_address=from_address,
        # Gmail's own unsubscribe button, for marketing and updates only.
        headers=_unsubscribe_headers(message),
        mailbox=mailbox,
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
            to_addresses=recipients_of(message), subject=message.subject,
            body_text=message.body_text, contact=message.to_contact,
            sent_at=message.sent_at,
            message_id_header=result.get("message_id_header", ""),
            in_reply_to=in_reply_to,
            gmail_message_id=result.get("gmail_message_id", ""),
            gmail_thread_id=result.get("gmail_thread_id", ""),
        )
        updates = ["last_message_at", "updated_at"]
        thread.last_message_at = message.sent_at
        # The mailbox it actually went through: the conversation's from now on.
        went = result.get("mailbox") or mailboxes.of_connection(result.get("connection")) \
            or mailbox
        if went is not None and thread.mailbox_id is None:
            thread.mailbox = went
            updates.insert(0, "mailbox")
        # Gmail assigns the thread id on the first send; remembering it is what
        # lets Tier 2 polling recognise the reply later.
        if result.get("gmail_thread_id") and not thread.gmail_thread_id:
            thread.gmail_thread_id = result["gmail_thread_id"]
            updates.insert(0, "gmail_thread_id")
        # The same for Microsoft 365: its first send's conversation is the
        # one replies are read from.
        if result.get("graph_conversation_id") and not thread.graph_conversation_id:
            thread.graph_conversation_id = result["graph_conversation_id"]
            updates.insert(0, "graph_conversation_id")
        thread.save(update_fields=updates)

    AuditEvent.all_objects.create(
        tenant=message.tenant, actor=actor, verb="email.sent",
        target_type="outbox_message", target_id=message.pk,
        payload={
            "producer": message.producer, "to": message.to_address,
            **({"also_to": message.also_to_address} if message.also_to_address else {}),
            "dev_real_send": dev_real, "via": result["provider"],
            **({"demo_redirect": demo_to} if demo_to else {}),
        },
    )
    return message


# ------------------------------------------------------------- producers

def create_manual_draft(contact, *, subject, body_text, actor=None, category=None,
                        fallback=None):
    """A one-off email to one contact, queued for approval.

    Deliberately NOT a direct-to-`sent` producer even though a human typed it:
    the bulk path composes many of these at once from a template, and "the click
    is the approval" stops being true when one click produced forty messages.

    Merged like every template (`services.templates`); the old `{first_name}`
    still works.
    """
    from apps.crm.services import templates

    values = templates.values_for(contact, tenant=contact.tenant, sender=actor)
    fallback = fallback or templates.DEFAULT_FALLBACK
    body = templates.render(body_text.replace("{first_name}", "{FirstName}"), values,
                            fallback=fallback)
    subject = templates.render_subject((subject or "").replace("{first_name}", "{FirstName}"),
                                       values, fallback=fallback)
    body = templates.with_signature(body, contact.tenant, actor)
    return create_message(
        tenant=contact.tenant, producer=P.MANUAL,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=subject or f"A note from {contact.tenant.name}",
        body_text=body, actor=actor,
        send_by=timezone.now() + timezone.timedelta(days=7),
        source_type="contact", source_id=contact.pk,
        # One person writing to one person is correspondence (the producer's
        # default); the same draft to several at once is marketing.
        category=category,
    )


def queue_stage_email(contact, rule, *, actor=None):
    """FR-1.12 — a stage rule NEVER sends. Send-by defaults to 7 days. Its
    template is merged and signed like every other (`services.templates`)."""
    from apps.crm.services import templates

    template = rule.email_template
    send_by = timezone.now() + timezone.timedelta(days=rule.send_by_offset_days)
    if template is not None:
        subject, body = templates.compose(template, contact, actor=actor)
    else:
        subject, body = "Following up", templates.with_signature("", contact.tenant, actor)
    return create_message(
        tenant=contact.tenant, producer=P.STAGE_RULE,
        to_contact=contact, to_address=contact.primary_email or "",
        subject=subject, body_text=body,
        send_by=send_by, actor=actor,
        source_type="stage_automation", source_id=rule.pk,
    )
