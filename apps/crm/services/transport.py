"""Mail transport.

Beta sends **all** app-originated mail through the founder fractional's
connected Gmail (Tier 1), with `From` set to the tenant's send-as alias.
Postmark becomes a per-tenant transport option in V1, not a Beta dependency.

Selected by `APP_MAIL_TRANSPORT` (`gmail` | `postmark`). The Outbox remains the
single queue and the complete send log — only the delivery mechanism changes.

**Trade-offs the owner accepted in making this change:**

1. **Magic links depend on the FF's Gmail token.** Sign-in mail is sent
   synchronously in-request (A2a) and now rides on one OAuth credential; if that
   token is revoked or expires, client sign-in stops until it is reconnected.
   `TransportUnavailable` is raised with a message that says exactly that,
   rather than failing as a generic 500.
2. **App mail appears in the FF's Sent folder.** Digests, referral touches, and
   magic links are all sent by that account.
3. **No third-party delivery log in Beta.** Postmark's per-message activity
   trail does not exist; the Outbox is the only send log, and bounces are
   visible only in Gmail.
"""

from __future__ import annotations

import base64
import uuid
from email.message import EmailMessage as MimeMessage

import requests
from django.conf import settings
from django.utils import timezone

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
THREAD_HEADER = "X-ExecsNowHQ-Thread"


class TransportUnavailable(Exception):
    """No usable transport. Never swallowed — a send that cannot happen must be
    visible, not silently dropped."""


class SendAsNotVerified(TransportUnavailable):
    pass


# --------------------------------------------------------------- threading

def message_id_for(tenant, thread):
    """Carry the thread token in the Message-ID.

    With no inbound domain in Beta there is no `reply+<token>@` address, so the
    token rides here instead. A reply's In-Reply-To / References will quote this
    value back, which is how a thread is recovered without a webhook.
    """
    domain = (tenant.from_address.split("@", 1)[-1]) or "localhost"
    return f"<{thread.thread_token}.{uuid.uuid4().hex[:12]}@{domain}>"


def token_from_message_id(value: str) -> str:
    """Recover a thread token from a Message-ID we issued, or ''."""
    if not value:
        return ""
    inner = value.strip().lstrip("<").rstrip(">")
    local = inner.split("@", 1)[0]
    return local.split(".", 1)[0] if "." in local else ""


def build_mime(*, to_address, from_address, subject, body_text,
               message_id, thread_token, in_reply_to="", references="",
               attachments=()):
    mime = MimeMessage()
    mime["To"] = to_address
    mime["From"] = from_address
    mime["Subject"] = subject
    mime["Message-ID"] = message_id
    mime[THREAD_HEADER] = thread_token
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = (references + " " + in_reply_to).strip()
    mime.set_content(body_text)
    for filename, content, content_type in attachments:
        maintype, _, subtype = content_type.partition("/")
        mime.add_attachment(content, maintype=maintype or "application",
                            subtype=subtype or "octet-stream", filename=filename)
    return mime


# ------------------------------------------------------------------ Gmail

def access_token_for(connection):
    """Exchange the stored refresh token for an access token."""
    from apps.crm.services.secrets import read_secret

    refresh_token = read_secret(connection.secret)
    if not refresh_token:
        raise TransportUnavailable(
            f"{connection.email_address} has no stored Gmail credential. "
            "Reconnect Gmail in Settings."
        )
    response = requests.post(TOKEN_URL, data={
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=20)
    if not response.ok:
        raise TransportUnavailable(
            f"Gmail refused the stored credential for {connection.email_address} "
            f"({response.status_code}). Reconnect Gmail in Settings — until then, "
            "no app mail (including magic links) can be sent."
        )
    return response.json()["access_token"]


def list_send_as(connection):
    """Every address Gmail says this account may send as.

    What `verify_send_as` checks one address against, returned whole so the
    Email settings screen can show the alias in the context of the list — "not
    there" and "there but unconfirmed" are different problems with different
    fixes, and both are invisible if you only ever see a pass/fail on one row.
    """
    token = access_token_for(connection)
    response = requests.get(
        f"{GMAIL_API}/settings/sendAs",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if not response.ok:
        raise SendAsNotVerified(
            f"Could not read the send-as settings for {connection.email_address} "
            f"({response.status_code}). The connection needs the "
            "gmail.settings.basic scope — reconnect Gmail to grant it."
        )
    return [
        {
            "address": entry.get("sendAsEmail", ""),
            "verification_status": entry.get("verificationStatus", "accepted") or "accepted",
            "is_primary": bool(entry.get("isPrimary")),
            "is_default": bool(entry.get("isDefault")),
        }
        for entry in response.json().get("sendAs", [])
    ]


def verify_send_as(connection, alias, *, save=True):
    """Confirm this Gmail account may send as the tenant's alias.

    Beta routes every app-originated message through this one connection, so an
    unverified alias is a hard error surfaced at connect time — not a silent
    fallback to the fractional's personal address, which would put the wrong
    From on every digest a client receives.
    """
    token = access_token_for(connection)
    response = requests.get(
        f"{GMAIL_API}/settings/sendAs",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if not response.ok:
        message = (
            f"Could not read the send-as settings for {connection.email_address} "
            f"({response.status_code}). The connection needs the "
            "gmail.settings.basic scope — reconnect Gmail to grant it."
        )
        if save:
            connection.send_as_error = message
            connection.send_as_verified_at = None
            connection.save(update_fields=["send_as_error", "send_as_verified_at", "updated_at"])
        raise SendAsNotVerified(message)

    entries = response.json().get("sendAs", [])
    available = {e.get("sendAsEmail", "").lower(): e for e in entries}
    entry = available.get((alias or "").lower())

    if entry is None:
        message = (
            f"{alias} is not a send-as address on {connection.email_address}. "
            "Add it in Gmail under Settings → Accounts → 'Send mail as', complete "
            f"the confirmation email, then reconnect here. Available right now: "
            f"{', '.join(sorted(available)) or 'none'}."
        )
    elif entry.get("verificationStatus", "accepted") not in ("accepted", ""):
        message = (
            f"{alias} is listed on {connection.email_address} but Gmail has not "
            f"confirmed it (status: {entry.get('verificationStatus')}). Complete "
            "the confirmation email Gmail sent, then verify again here."
        )
    else:
        if save:
            connection.send_as_address = alias
            connection.send_as_verified_at = timezone.now()
            connection.send_as_error = ""
            connection.save(update_fields=[
                "send_as_address", "send_as_verified_at", "send_as_error", "updated_at",
            ])
        return True

    if save:
        connection.send_as_error = message
        connection.send_as_verified_at = None
        connection.save(update_fields=["send_as_error", "send_as_verified_at", "updated_at"])
    raise SendAsNotVerified(message)


def sending_connection_for(tenant):
    """The FF's Gmail connection — the one app mail goes through."""
    from apps.crm.models import GmailConnection
    from apps.tenancy.models import Membership, Role

    ff_ids = Membership.all_objects.filter(
        tenant=tenant, role=Role.FF, revoked_at__isnull=True
    ).values_list("user_id", flat=True)

    connection = GmailConnection.all_objects.filter(
        tenant=tenant, user_id__in=list(ff_ids)
    ).order_by("-send_as_verified_at").first()

    if connection is None:
        raise TransportUnavailable(
            "No Gmail account is connected for this practice. Connect Gmail in "
            "Settings — in Beta all app mail, including magic links, goes "
            "through it."
        )
    if connection.send_as_verified_at is None:
        raise SendAsNotVerified(
            connection.send_as_error
            or f"The send-as alias for {connection.email_address} is not verified."
        )
    return connection


class GmailTransport:
    name = "gmail"

    def send(self, *, tenant, to_address, subject, body_text, thread,
             in_reply_to="", references="", attachments=()):
        connection = sending_connection_for(tenant)
        token = access_token_for(connection)

        message_id = message_id_for(tenant, thread)
        mime = build_mime(
            to_address=to_address,
            from_address=connection.send_as_address or tenant.from_address,
            subject=subject, body_text=body_text, message_id=message_id,
            thread_token=thread.thread_token, in_reply_to=in_reply_to,
            references=references, attachments=attachments,
        )
        payload = {"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()}
        if thread.gmail_thread_id:
            payload["threadId"] = thread.gmail_thread_id

        response = requests.post(
            f"{GMAIL_API}/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json=payload, timeout=30,
        )
        if not response.ok:
            raise TransportUnavailable(
                f"Gmail rejected the message ({response.status_code}): "
                f"{response.text[:300]}"
            )
        data = response.json()
        return {
            "provider": "gmail",
            "provider_message_id": data.get("id", ""),
            "gmail_message_id": data.get("id", ""),
            "gmail_thread_id": data.get("threadId", ""),
            "message_id_header": message_id,
            "from_address": mime["From"],
        }


class PostmarkTransport:
    """V1. Kept so the transport seam is real rather than hypothetical."""

    name = "postmark"

    def send(self, **kwargs):
        raise TransportUnavailable(
            "The Postmark transport is a V1 option and is not configured. "
            "Set APP_MAIL_TRANSPORT=gmail for Beta."
        )


class DevOutboxTransport:
    """FR-0.7 / H6 — where mail goes on a localhost build.

    Unchanged by the transport switch: the guard is about WHO may receive real
    mail, not about which service carries it.
    """

    name = "dev"

    def send(self, *, tenant, to_address, subject, body_text, thread,
             in_reply_to="", references="", attachments=()):
        from django.core.mail import EmailMessage as DjangoEmailMessage

        message_id = message_id_for(tenant, thread)
        email = DjangoEmailMessage(
            subject=subject, body=body_text, from_email=tenant.from_address,
            to=[to_address],
            headers={"Message-ID": message_id, THREAD_HEADER: thread.thread_token,
                     **({"In-Reply-To": in_reply_to} if in_reply_to else {})},
        )
        for filename, content, content_type in attachments:
            email.attach(filename, content, content_type)
        email.send(fail_silently=False)
        return {
            "provider": "dev", "provider_message_id": "",
            "gmail_message_id": "", "gmail_thread_id": "",
            "message_id_header": message_id, "from_address": tenant.from_address,
        }


def get_transport(name=None):
    name = name or getattr(settings, "APP_MAIL_TRANSPORT", "gmail")
    if name == "postmark":
        return PostmarkTransport()
    return GmailTransport()
