"""Replies coming back (FR-6.5 to FR-6.12).

**Polling, not a webhook.** The app reads the threads it started, out of the
practice's own mailbox, over an authenticated Google call. That has three
consequences worth stating, because the design follows from them:

1. **There is nothing to forge.** Authenticity comes from the transport rather
   than from a shared secret, so Beta needs no signature check and no public
   endpoint — which is why this module runs on a laptop (FR-6.11).
2. **Every poll re-reads the whole thread**, so idempotency is load-bearing in
   a way it never was for a webhook. One message, one row, forever, keyed on
   the provider's own id (FR-6.12).
3. **Catching up is the same operation as keeping up.** `threads.get` returns
   the thread entire, so a laptop shut for a fortnight ingests on the next run
   without a resync and without a history cursor that would have expired.

Everything below this line is a pure function over a parsed thread payload
(FR-6.13), which is why the fixtures are the regression suite and not a
nice-to-have: the only part that needs Google is fetching the JSON.
"""

from __future__ import annotations

import base64
import re
from email.utils import parseaddr, parsedate_to_datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.crm.models import (
    Contact, ContactEmail, EmailMessage, EmailThread, UnmatchedInbound,
)
from apps.crm.services import transport

#: In the order FR-6.6 sets out. Each is recorded on the message as
#: `matched_by`, so the history can say how a reply found its way home rather
#: than presenting the connection as a fact.
BY_THREAD_ID = "gmail_thread_id"
BY_IN_REPLY_TO = "in_reply_to"
BY_HEADER = "thread_header"
BY_SENDER = "sender_email"
NO_MATCH = ""

#: A file bigger than this is recorded and skipped **with a reason**, never
#: silently dropped (FR-6.10).
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


# --------------------------------------------------------------- reading a payload

def header(payload: dict, name: str) -> str:
    """One header, case-insensitively, from Gmail's list-of-pairs shape."""
    wanted = name.lower()
    for row in (payload.get("payload") or {}).get("headers") or []:
        if str(row.get("name", "")).lower() == wanted:
            return str(row.get("value", "") or "")
    return ""


def _decode(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except Exception:                                   # pragma: no cover - malformed
        return ""


def _walk(part: dict):
    yield part
    for child in part.get("parts") or []:
        yield from _walk(child)


def bodies(payload: dict) -> tuple[str, str]:
    """`(text, html)`. Gmail nests parts arbitrarily; take the first of each."""
    text = html = ""
    for part in _walk((payload.get("payload") or {})):
        mime = part.get("mimeType", "")
        content = _decode(((part.get("body") or {}).get("data")) or "")
        if not content:
            continue
        if mime == "text/plain" and not text:
            text = content
        elif mime == "text/html" and not html:
            html = content
    return text, html


def attachments_in(payload: dict) -> list[dict]:
    found = []
    for part in _walk((payload.get("payload") or {})):
        body = part.get("body") or {}
        filename = part.get("filename") or ""
        if not filename:
            continue
        found.append({
            "filename": filename,
            "content_type": part.get("mimeType", ""),
            "size": int(body.get("size") or 0),
            "attachment_id": body.get("attachmentId", ""),
            "data": body.get("data", ""),
        })
    return found


# ------------------------------------------------------------- quoted history

#: The shapes a mail client uses to fence off what came before. Deliberately
#: conservative: trimming is for display only and the raw message is kept
#: beside it (FR-6.9), so a missed quote is untidy while an over-eager one
#: hides what somebody wrote.
QUOTE_MARKERS = [
    re.compile(r"^On .{5,120}\bwrote:\s*$", re.M),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.M | re.I),
    re.compile(r"^_{5,}\s*$", re.M),
    re.compile(r"^From:\s.+$", re.M),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.M | re.I),
]
SIGNATURE = re.compile(r"^-- \s*$", re.M)


def strip_quoted(text: str) -> str:
    """What this person actually wrote, for display.

    Everything from the first quote marker onward goes, as does everything
    after an RFC 3676 signature delimiter. Lines beginning `>` are dropped
    wherever they are.
    """
    if not text:
        return ""
    cut = len(text)
    for marker in QUOTE_MARKERS:
        found = marker.search(text)
        if found and found.start() < cut:
            cut = found.start()
    body = text[:cut]
    signature = SIGNATURE.search(body)
    if signature:
        body = body[:signature.start()]
    kept = [line for line in body.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(kept).strip()


# ------------------------------------------------------------------- matching

def _thread_by_reference(tenant, value: str):
    """Any Message-ID we issued, quoted back at us in In-Reply-To/References."""
    for candidate in re.findall(r"<[^>]+>", value or ""):
        existing = EmailMessage.objects.filter(
            message_id_header=candidate).select_related("thread").first()
        if existing is not None:
            return existing.thread
        token = transport.token_from_message_id(candidate)
        if token:
            thread = EmailThread.objects.filter(thread_token=token).first()
            if thread is not None:
                return thread
    return None


def match(tenant, payload: dict):
    """`(thread, contact, how, why_not)` — **in the order FR-6.6 sets out.**

    Nothing here creates anything. A match is a claim about which conversation
    a message belongs to, and the one case where we cannot make that claim
    honestly is the case the unmatched queue exists for.
    """
    gmail_thread_id = payload.get("threadId") or ""
    if gmail_thread_id:
        thread = EmailThread.objects.filter(gmail_thread_id=gmail_thread_id).first()
        if thread is not None:
            return thread, thread.contact, BY_THREAD_ID, ""

    for field in ("In-Reply-To", "References"):
        thread = _thread_by_reference(tenant, header(payload, field))
        if thread is not None:
            return thread, thread.contact, BY_IN_REPLY_TO, ""

    token = header(payload, "X-ExecsNowHQ-Thread").strip()
    if token:
        thread = EmailThread.objects.filter(thread_token=token).first()
        if thread is not None:
            return thread, thread.contact, BY_HEADER, ""

    address = parseaddr(header(payload, "From"))[1].lower()
    if address:
        row = (ContactEmail.objects.filter(address__iexact=address,
                                           contact__deleted_at__isnull=True)
               .select_related("contact").first())
        if row is not None:
            # A known person on a conversation we did not start. Their own
            # thread, so the history stays one conversation per thread.
            thread = (EmailThread.objects.filter(contact=row.contact,
                                                 gmail_thread_id=gmail_thread_id).first()
                      if gmail_thread_id else None)
            return thread, row.contact, BY_SENDER, ""

    if not address:
        return None, None, NO_MATCH, "no sender address on the message"
    return None, None, NO_MATCH, f"no thread, and no contact holds {address}"


# ------------------------------------------------------------------- ingesting

def already_have(tenant, provider_message_id: str) -> bool:
    return bool(provider_message_id) and (
        EmailMessage.objects.filter(provider="gmail",
                                    provider_message_id=provider_message_id).exists()
        or UnmatchedInbound.objects.filter(
            provider_message_id=provider_message_id).exists())


def _received_at(payload: dict):
    raw = header(payload, "Date")
    if raw:
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            pass
    stamp = payload.get("internalDate")
    if stamp:
        try:
            return timezone.datetime.fromtimestamp(int(stamp) / 1000,
                                                   tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    return timezone.now()


@transaction.atomic
def ingest_message(tenant, payload: dict, *, client=None) -> dict:
    """One message from one thread. Returns what happened, in a word.

    **Idempotent first**, because every poll re-reads the whole thread: the
    second sighting of a message is the normal case, not the exception.
    """
    provider_message_id = payload.get("id") or ""
    if already_have(tenant, provider_message_id):
        return {"outcome": "already_had", "message": None}

    thread, contact, how, why_not = match(tenant, payload)
    text, html = bodies(payload)
    stripped = strip_quoted(text)
    from_name, from_address = parseaddr(header(payload, "From"))
    received = _received_at(payload)

    if thread is None and contact is None:
        row = UnmatchedInbound.objects.create(
            tenant=tenant, provider="gmail",
            provider_message_id=provider_message_id,
            gmail_thread_id=payload.get("threadId") or "",
            from_address=from_address[:254], from_name=from_name[:200],
            to_addresses=[a for a in [parseaddr(header(payload, "To"))[1]] if a],
            subject=header(payload, "Subject")[:255],
            body_text=text, body_html=html, body_stripped=stripped,
            raw=payload, received_at=received, reason=why_not[:120],
        )
        return {"outcome": "unmatched", "unmatched": row}

    if thread is None:
        # Matched a person but not a conversation: give them one, so the
        # history is still one thread per conversation.
        thread = EmailThread.objects.create(
            tenant=tenant, thread_token=EmailThread.new_token(),
            contact=contact,
            client_company=contact.company if contact and contact.company_id else None,
            gmail_thread_id=payload.get("threadId") or "",
            subject=header(payload, "Subject")[:255],
        )

    message = EmailMessage.objects.create(
        tenant=tenant, thread=thread, direction="inbound", provider="gmail",
        provider_message_id=provider_message_id,
        from_address=from_address[:254],
        to_addresses=[a for a in [parseaddr(header(payload, "To"))[1]] if a],
        subject=header(payload, "Subject")[:255],
        body_html=html, body_text=text, body_stripped=stripped, raw=payload,
        contact=contact or thread.contact, matched_by=how,
        received_at=received,
        message_id_header=header(payload, "Message-ID")[:255],
        in_reply_to=header(payload, "In-Reply-To")[:255],
        references=header(payload, "References"),
        gmail_message_id=provider_message_id,
        gmail_thread_id=payload.get("threadId") or "",
    )
    _store_attachments(tenant, message, payload, client=client)

    if not thread.gmail_thread_id and payload.get("threadId"):
        thread.gmail_thread_id = payload["threadId"]
    thread.last_message_at = received
    thread.save(update_fields=["gmail_thread_id", "last_message_at", "updated_at"])
    return {"outcome": "matched", "message": message, "matched_by": how}


def _store_attachments(tenant, message, payload, *, client=None):
    """FR-6.10. Anything not stored is **written into the message**, never
    dropped: the failure mode that matters in this module is silence."""
    from apps.crm.models import EmailAttachment
    from apps.tenancy import storage

    def note(text):
        message.body_stripped = f"{message.body_stripped}\n\n[{text}]".strip()
        message.save(update_fields=["body_stripped", "updated_at"])

    for found in attachments_in(payload):
        limit_mb = MAX_ATTACHMENT_BYTES // (1024 * 1024)
        if found["size"] > MAX_ATTACHMENT_BYTES:
            note(f"{found['filename']} was not stored: "
                 f"{found['size'] // (1024 * 1024)} MB is over the {limit_mb} MB limit.")
            continue
        data = found["data"]
        if not data and found["attachment_id"] and client is not None:
            data = client.attachment(payload.get("id", ""), found["attachment_id"])
        if not data:
            note(f"{found['filename']} could not be downloaded from Gmail.")
            continue
        content = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        content_type = found["content_type"] or "application/octet-stream"
        try:
            stored = storage.save(
                tenant=tenant, content=content, purpose="email_attachment",
                object_key=storage.object_key("email", found["filename"]),
                content_type=content_type)
        except Exception as exc:                        # pragma: no cover - storage
            note(f"{found['filename']} could not be stored: {exc}")
            continue
        EmailAttachment.objects.create(
            tenant=tenant, message=message, stored_file=stored,
            filename=found["filename"][:255], content_type=content_type[:120],
            byte_size=stored.byte_size)


def ingest_thread(tenant, payload: dict, *, client=None) -> dict:
    """A whole `users.threads.get` payload. The unit the poller works in."""
    counts = {"matched": 0, "unmatched": 0, "already_had": 0, "skipped_outbound": 0}
    for message in payload.get("messages") or []:
        if _is_ours(tenant, message):
            counts["skipped_outbound"] += 1
            continue
        counts[ingest_message(tenant, message, client=client)["outcome"]] += 1
    return counts


def _is_ours(tenant, payload: dict) -> bool:
    """A message we sent, seen again in its own thread.

    Recognised by the Message-ID we issued rather than by the From address: a
    CF sending from their own mailbox is still us, and the alias is not the
    only address the practice sends from.
    """
    message_id = header(payload, "Message-ID")
    if message_id and EmailMessage.objects.filter(
            direction="outbound", message_id_header=message_id).exists():
        return True
    return bool(payload.get("id")) and EmailMessage.objects.filter(
        direction="outbound", provider_message_id=payload["id"]).exists()


# --------------------------------------------------------------------- filing

@transaction.atomic
def file_to_contact(row, *, contact, actor=None, thread=None, add_address=False):
    """R13 — a person decides where it belongs, and the app does the filing.

    Optionally adds the sending address to that contact, which is how the
    *next* reply from it matches itself (FR-6.8).
    """
    if row.state != UnmatchedInbound.State.PENDING:
        raise ValueError("That message has already been filed.")
    tenant = row.tenant
    if thread is None:
        thread = (EmailThread.objects.filter(contact=contact,
                                             gmail_thread_id=row.gmail_thread_id).first()
                  if row.gmail_thread_id else None)
    if thread is None:
        thread = EmailThread.objects.create(
            tenant=tenant, thread_token=EmailThread.new_token(), contact=contact,
            client_company=contact.company if contact.company_id else None,
            gmail_thread_id=row.gmail_thread_id, subject=row.subject)

    message = EmailMessage.objects.create(
        tenant=tenant, thread=thread, direction="inbound", provider=row.provider,
        provider_message_id=row.provider_message_id, from_address=row.from_address,
        to_addresses=row.to_addresses, subject=row.subject,
        body_html=row.body_html, body_text=row.body_text,
        body_stripped=row.body_stripped, raw=row.raw, contact=contact,
        matched_by="filed_by_hand", received_at=row.received_at,
        message_id_header=header(row.raw, "Message-ID")[:255],
        gmail_message_id=row.provider_message_id,
        gmail_thread_id=row.gmail_thread_id,
    )
    if add_address and row.from_address:
        ContactEmail.objects.get_or_create(
            tenant=tenant, contact=contact, address=row.from_address.lower(),
            defaults={"is_primary": not contact.emails.exists()})

    thread.last_message_at = row.received_at or timezone.now()
    thread.save(update_fields=["last_message_at", "updated_at"])
    row.state = UnmatchedInbound.State.FILED
    row.filed_contact = contact
    row.filed_thread = thread
    row.filed_message = message
    row.filed_by = actor
    row.filed_at = timezone.now()
    row.save(update_fields=["state", "filed_contact", "filed_thread",
                            "filed_message", "filed_by", "filed_at", "updated_at"])
    return message
