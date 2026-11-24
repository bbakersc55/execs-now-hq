"""Postmark, the send-only provider for owner email from our own domain
(owner, 2026-11-23). One call: POST https://api.postmarkapp.com/email with the
server token. Its token is the Railway variable OWNER_EMAIL_POSTMARK_TOKEN; the
domain, the from-address and the reply-to are the company's settings.

Called only through the Outbox (every email leaves through it): an Outbox
message created with `sent_via="owner_domain"` is delivered by
`OwnerDomainTransport` in production; on a laptop the Outbox's dev guard keeps
it on the machine (Mailpit) and Postmark is never called.
"""

from __future__ import annotations

import base64

import requests
from django.conf import settings

URL = "https://api.postmarkapp.com/email"
TIMEOUT = 20
#: Postmark error codes about one recipient: that email fails, the rest go on.
RECIPIENT_ERRORS = {300, 406}


#: The Outbox's mark on a message for a company's own domain.
OWNER_DOMAIN = "owner_domain"


class PostmarkError(Exception):
    def __init__(self, message, *, code=None, recipient_only=False):
        super().__init__(message)
        self.code = code
        self.recipient_only = recipient_only


def _unavailable():
    from apps.crm.services.transport import TransportUnavailable

    class OwnerDomainRefused(TransportUnavailable):
        def __init__(self, message, recipient_only=False):
            super().__init__(message)
            self.recipient_only = recipient_only

    return OwnerDomainRefused


class OwnerDomainTransport:
    """The Outbox's transport for owner email from a company's own domain:
    its from-name and reply-to, through Postmark. No fallback: a refusal is
    raised, and the Outbox's caller pauses owner emails."""

    #: Kept as the Outbox row's `sent_via`, so a preview of it stays white label.
    name = OWNER_DOMAIN

    def __init__(self, program):
        self.program = program

    @classmethod
    def for_message(cls, message):
        from .models import OwnerAgreement, Program

        program = None
        if message.source_type == "owner_agreement" and message.source_id:
            a = OwnerAgreement.all_objects.filter(pk=message.source_id).first()
            program = Program.all_objects.filter(company_id=a.company_id).first() if a else None
        elif message.source_type == "owner_agreement_program" and message.source_id:
            program = Program.all_objects.filter(pk=message.source_id).first()
        if program is None:
            raise _unavailable()("No owner-email settings for this message.")
        return cls(program)

    def send(self, *, tenant, to_address, subject, body_text, body_html="", attachments=(),
             from_address="", **_ignored):
        try:
            message_id = send(from_name=self.program.from_name,
                              from_address=self.program.from_address, to=to_address,
                              reply_to=self.program.reply_to, subject=subject,
                              text=body_text, html=body_html, attachments=attachments)
        except PostmarkError as exc:
            raise _unavailable()(str(exc), recipient_only=exc.recipient_only) from None
        return {"provider": self.name, "provider_message_id": message_id,
                "from_address": self.program.from_address}


def token() -> str:
    return getattr(settings, "OWNER_EMAIL_POSTMARK_TOKEN", "") or ""


def send(*, from_name, from_address, to, reply_to, subject, text, html, attachments=()):
    """The MessageID Postmark gave, or PostmarkError."""
    if not token():
        raise PostmarkError("OWNER_EMAIL_POSTMARK_TOKEN isn't set on this server.")
    name = (from_name or "").replace('"', "'")
    body = {
        "From": f'"{name}" <{from_address}>' if name else from_address,
        "To": to, "Subject": subject, "TextBody": text, "HtmlBody": html,
        "MessageStream": "outbound", "TrackOpens": False, "TrackLinks": "None",
        "Attachments": [{"Name": n, "Content": base64.b64encode(c).decode(),
                         "ContentType": t} for n, c, t in attachments],
    }
    if reply_to:
        body["ReplyTo"] = reply_to
    try:
        response = requests.post(URL, json=body, timeout=TIMEOUT, headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "X-Postmark-Server-Token": token()})
    except requests.RequestException as exc:
        raise PostmarkError(f"Postmark didn't answer: {exc.__class__.__name__}") from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    code = data.get("ErrorCode")
    if response.status_code == 200 and code == 0:
        return str(data.get("MessageID", ""))
    message = str(data.get("Message") or f"HTTP {response.status_code}")[:240]
    raise PostmarkError(f"Postmark refused it ({code}): {message}", code=code,
                        recipient_only=code in RECIPIENT_ERRORS)
