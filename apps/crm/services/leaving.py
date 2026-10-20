"""Replies that ask to leave (owner, 2026-10-19).

A reply to a marketing email that says "unsubscribe", "stop", "remove me" or
"opt out", on a line of its own or as the gist of a one-line reply, is marked
**Asked to leave** when it comes in (`flag`). Replies lists it with one click,
**Unsubscribe them**, which does exactly what the email's own link does
(`unsubscribe.unsubscribe`, marketing). **Nothing happens without that
click**, and a person may instead say it was not a request to leave.

Read on the reply's own words (`body_stripped`: what they wrote, the quoted
email taken off), so our own unsubscribe line quoted back never counts.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from apps.crm.models import EmailMessage, OutboxMessage
from apps.tenancy.models import AuditEvent

L = EmailMessage.Leave
#: The words that ask, normalised: lower case, letters and spaces only.
PHRASES = ("unsubscribe", "stop", "remove me", "opt out")
#: A one-line reply this long or shorter is read for its gist.
GIST_WORDS = 12
#: "stop" in a sentence asks to leave only when it is about the mail.
_STOP_ABOUT = re.compile(r"\bstop (?:e ?mailing|sending|contacting|messaging|these|this|"
                         r"the (?:e ?mails|emails|messages))\b")


def _plain(line: str) -> str:
    words = re.sub(r"[^a-z]+", " ", line.lower().replace("opt-out", "opt out")
                   .replace("optout", "opt out")).split()
    return " ".join(words)


def asks_to_leave(text: str) -> bool:
    """On a line of its own ("STOP", "Unsubscribe."), or the gist of a
    one-line reply ("Please remove me from your list", "stop emailing me")."""
    lines = [line for line in (text or "").splitlines()
             if line.strip() and not line.lstrip().startswith(">")]
    plain = [_plain(line) for line in lines]
    plain = [p for p in plain if p]
    if any(p in PHRASES or p in ("please unsubscribe", "unsubscribe me",
                                  "unsubscribe please", "stop please", "please stop")
           for p in plain):
        return True
    if len(plain) != 1 or len(plain[0].split()) > GIST_WORDS:
        return False
    gist = f" {plain[0]} "
    if any(f" {phrase} " in gist for phrase in ("unsubscribe", "remove me", "opt out")):
        return True
    return gist.strip().startswith("stop ") or bool(_STOP_ABOUT.search(gist))


def answered(message) -> OutboxMessage | None:
    """The email the reply answers: the last one sent to its thread before
    it came in."""
    if message.thread_id is None:
        return None
    sent = OutboxMessage.all_objects.filter(
        tenant_id=message.tenant_id, thread_id=message.thread_id,
        state=OutboxMessage.State.SENT)
    if message.received_at:
        sent = sent.filter(sent_at__lte=message.received_at)
    return sent.order_by("-sent_at").first()


def flag(message) -> bool:
    """Mark a reply that came in, if it answers a marketing email and asks
    to leave. Changes nothing else."""
    from apps.crm.services import unsubscribe

    if message.direction != "inbound" or message.leave_request:
        return False
    source = answered(message)
    if source is None or unsubscribe.category_of(source) != unsubscribe.MARKETING:
        return False
    if not asks_to_leave(message.body_stripped or message.body_text):
        return False
    message.leave_request = L.ASKED
    message.save(update_fields=["leave_request", "updated_at"])
    return True


def waiting(queryset):
    return queryset.filter(direction="inbound", leave_request=L.ASKED)\
        .select_related("contact", "thread").order_by("-received_at")


@transaction.atomic
def unsubscribe_them(message, *, actor) -> None:
    """The one click: exactly what the link in the email does, for marketing,
    for this person. Then the reply is marked done."""
    from apps.crm.services import unsubscribe

    if message.leave_request != L.ASKED:
        raise ValueError("That reply is not waiting.")
    source = answered(message)
    contact = message.contact
    data = {"t": str(message.tenant_id), "k": unsubscribe.MARKETING,
            "c": str(contact.pk) if contact else "",
            "a": "" if contact else (message.from_address or "").lower()}
    unsubscribe.unsubscribe(data, category=unsubscribe.MARKETING,
                            message_id=source.pk if source else None,
                            source="reply")
    _done(message, L.UNSUBSCRIBED, actor)


def keep(message, *, actor) -> None:
    """A person says it was not a request to leave. Nothing else changes."""
    if message.leave_request != L.ASKED:
        raise ValueError("That reply is not waiting.")
    _done(message, L.KEPT, actor)


def _done(message, state, actor) -> None:
    message.leave_request = state
    message.save(update_fields=["leave_request", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=message.tenant_id, actor=actor,
        verb="reply.unsubscribed" if state == L.UNSUBSCRIBED else "reply.kept",
        target_type="contact" if message.contact_id else "email_message",
        target_id=message.contact_id or message.pk,
        payload={"reply": str(message.pk), "subject": message.subject,
                 "at": timezone.now().isoformat()})
