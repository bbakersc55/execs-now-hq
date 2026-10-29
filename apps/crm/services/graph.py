"""Microsoft 365 as the practice's mail transport (docs/m365_transport.md).

The second transport beside `transport.GmailTransport`, chosen by
`tenant.mail_provider`. Everything above it is shared and unchanged: the
Outbox and its approvals, the dev allow-list and the demo's redirect
(`outbox._deliver`), unsubscribe headers and suppression, what a reply means
(`inbound`). This module only carries the message and fetches the replies.

**Sending is MIME, as with Gmail.** The message is built by the same
`transport.build_mime`, so the headers, the HTML and text parts, the inline
logo and the attachments are byte-for-byte what Gmail would have been handed.
Graph takes it as a draft (`POST /me/messages` with the MIME, base64, as
`text/plain`), which returns the draft's `conversationId` and
`internetMessageId` before it is sent (§3); `/me/sendMail` would return
nothing to track the conversation by.

**Ids are immutable** (`Prefer: IdType="ImmutableId"`), so the id a draft is
given is still the id of the copy in Sent Items after it moves.

**Read only conversations the app started.** `Mail.Read` is the whole mailbox,
as `gmail.readonly` is; the boundary is here, in `GraphReader`, which only
ever asks for a `conversationId` the app stored.

What only a real Microsoft 365 account can confirm is listed in
`docs/m365_transport.md` §10, and each place it matters says [verify].
"""

from __future__ import annotations

import base64
import time
from email import policy
from email.parser import BytesParser

import requests
from django.utils import timezone

from apps.crm.services import microsoft_oauth
from apps.crm.services.transport import (
    SendAsNotVerified, TransportUnavailable, build_mime, message_id_for,
)

GRAPH = microsoft_oauth.GRAPH
#: Graph refuses a request over 4 MB. A draft whose request (the MIME, its
#: attachments already base64 inside it, base64 again for Graph) stays under
#: this carries its attachments; a bigger one is made without them and they
#: are added after, each by the route its size needs.
REQUEST_LIMIT = int(3.5 * 1024 * 1024)
#: Under this, an attachment is added with one POST; at or over, by an
#: upload session (Graph's 3 MB line).
INLINE_LIMIT = 3 * 1024 * 1024
#: An upload session's chunks are multiples of 320 KiB (Graph's rule).
CHUNK = 320 * 1024 * 10
#: Waits on a 429 or 503, each no longer than this many seconds; longer than
#: that and the send fails with Graph's own figure, and the Outbox shows it.
RETRIES = 2
LONGEST_WAIT = 10
#: The alias check reads back the copy in Sent Items: this many looks, a
#: second apart, before it says "not yet".
READ_BACK_TRIES = 6


# ------------------------------------------------------------ connection

def _membership_ids(tenant, roles):
    from apps.tenancy.models import Membership

    return list(Membership.all_objects.filter(
        tenant=tenant, role__in=roles, revoked_at__isnull=True,
    ).values_list("user_id", flat=True))


def sending_connection_for(tenant, from_address=""):
    """The Microsoft connection a message goes through: the twin of
    `transport.sending_connection_for` (FR-1.15c). A practice owner's or an
    associate's own address goes through their own verified connection;
    everything else through the practice owner's, as the practice address."""
    from apps.crm.models import MicrosoftConnection
    from apps.tenancy.models import Role

    if from_address:
        own = MicrosoftConnection.all_objects.filter(
            tenant=tenant, user_id__in=_membership_ids(tenant, [Role.FF, Role.CF]),
            email_address__iexact=from_address, send_as_verified_at__isnull=False,
        ).first()
        if own is not None:
            return own
    connection = (MicrosoftConnection.all_objects
                  .filter(tenant=tenant, user_id__in=_membership_ids(tenant, [Role.FF]))
                  .order_by("-send_as_verified_at").first())
    if connection is None:
        raise TransportUnavailable(
            "No Microsoft 365 account is connected for this practice. Connect it in "
            "Settings → Email: all app mail, including sign-in links, goes through it.")
    if connection.send_as_verified_at is None:
        raise SendAsNotVerified(
            connection.send_as_error
            or f"The practice address is not yet confirmed for {connection.email_address}.")
    return connection


def access_token_for(connection):
    """A fresh access token. Microsoft rotates the refresh token on every use,
    so the new one is stored before the access token is handed back."""
    from apps.crm.services.secrets import encrypt, write_secret
    from apps.crm.services.transport import stored_refresh
    from apps.tenancy.models import SecretKind

    stored = stored_refresh(connection)
    if not stored:
        raise TransportUnavailable(
            f"{connection.email_address} has no stored Microsoft 365 credential. "
            "Reconnect Microsoft 365 in Settings → Email.")
    try:
        tokens = microsoft_oauth.refresh(stored, connection.scopes or microsoft_oauth.SEND_SCOPES)
    except microsoft_oauth.MicrosoftOAuthError as exc:
        raise TransportUnavailable(
            f"{exc} Reconnect Microsoft 365 for {connection.email_address} in Settings → "
            "Email; until then, no app mail (including sign-in links) can be sent.") from exc
    rotated = tokens.get("refresh_token")
    if rotated and rotated != stored and hasattr(connection, "stored_token"):
        # A shared or client mailbox keeps its token on its own row.
        connection.token_ciphertext = encrypt(rotated)
        connection.save(update_fields=["token_ciphertext", "updated_at"])
    elif rotated and rotated != stored:
        secret = write_secret(tenant=connection.tenant, kind=SecretKind.MICROSOFT_REFRESH,
                              value=rotated, user=connection.user)
        if connection.secret_id != secret.pk:
            connection.secret = secret
            connection.save(update_fields=["secret", "updated_at"])
    return tokens["access_token"]


# ------------------------------------------------------------------ calls

def _headers(token, **extra):
    return {"Authorization": f"Bearer {token}", "Prefer": 'IdType="ImmutableId"', **extra}


def _call(method, url, *, token=None, headers=None, **kwargs):
    """One Graph request, waiting out a 429 or 503 when Graph says how long
    and it is short (§3: "a 429 is retried after the time Graph says")."""
    timeout = kwargs.pop("timeout", 30)
    for attempt in range(RETRIES + 1):
        response = requests.request(
            method, url, headers=headers if headers is not None else _headers(token),
            timeout=timeout, **kwargs)
        if response.status_code not in (429, 503) or attempt == RETRIES:
            return response
        try:
            wait = int(response.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5
        if wait > LONGEST_WAIT:
            return response
        time.sleep(wait)
    return response                                     # pragma: no cover - loop returns


def _error_code(response) -> str:
    try:
        return (response.json().get("error") or {}).get("code", "")
    except ValueError:
        return ""


def _said(response) -> str:
    try:
        error = response.json().get("error") or {}
        return f"{error.get('code', '')}: {error.get('message', '')}".strip(": ")
    except ValueError:
        return response.text[:300]


def _send_as_refusal(connection, from_address) -> str:
    return (
        f"Microsoft 365 would not let {connection.email_address} send as {from_address}. "
        f"If {from_address} is a shared mailbox or a group, an administrator gives "
        f"{connection.email_address} “Send as” on it (Exchange admin center → Recipients → "
        "the mailbox → Delegation). If it is an alias on your own mailbox, an administrator "
        "turns on sending from aliases for the organization. Then check again here.")


# ---------------------------------------------------------------- sending

def _create_draft(token, mime_bytes):
    response = _call("POST", f"{GRAPH}/me/messages",
                     headers=_headers(token, **{"Content-Type": "text/plain"}),
                     data=base64.b64encode(mime_bytes))
    return response


def _attach(token, message_id, filename, content, content_type):
    """One attachment onto a draft too big to carry it in its MIME: a plain
    POST under 3 MB, an upload session above (§3)."""
    if len(content) < INLINE_LIMIT:
        response = _call("POST", f"{GRAPH}/me/messages/{message_id}/attachments", token=token,
                         json={"@odata.type": "#microsoft.graph.fileAttachment",
                               "name": filename, "contentType": content_type,
                               "contentBytes": base64.b64encode(content).decode()})
        if not response.ok:
            raise TransportUnavailable(
                f"Microsoft 365 would not take the attachment {filename} "
                f"({response.status_code}): {_said(response)}")
        return
    session = _call("POST", f"{GRAPH}/me/messages/{message_id}/attachments/createUploadSession",
                    token=token, json={"AttachmentItem": {
                        "attachmentType": "file", "name": filename,
                        "size": len(content), "contentType": content_type}})
    if not session.ok:
        raise TransportUnavailable(
            f"Microsoft 365 would not start the upload of {filename} "
            f"({session.status_code}): {_said(session)}")
    upload_url = session.json()["uploadUrl"]
    total = len(content)
    for start in range(0, total, CHUNK):
        piece = content[start:start + CHUNK]
        # The upload URL carries its own authorization; a bearer token on it
        # is refused (Graph's upload-session rule).
        response = _call("PUT", upload_url, headers={
            "Content-Length": str(len(piece)),
            "Content-Range": f"bytes {start}-{start + len(piece) - 1}/{total}",
        }, data=piece, timeout=120)
        if not response.ok:
            raise TransportUnavailable(
                f"Microsoft 365 stopped the upload of {filename} at byte {start} "
                f"({response.status_code}).")


def _discard(token, message_id):
    """A draft that could not be sent is removed, so a failed send leaves
    nothing half-made in the practice's Drafts folder."""
    try:
        _call("DELETE", f"{GRAPH}/me/messages/{message_id}", token=token)
    except requests.RequestException:                   # pragma: no cover - best effort
        pass


def send_mime(connection, token, mime, *, attachments_after=()):
    """Draft, attach what did not fit, send. Returns the draft's JSON."""
    response = _create_draft(token, mime.as_bytes())
    if not response.ok:
        if _error_code(response) in ("ErrorSendAsDenied", "ErrorFromAddressNotPermitted"):
            raise SendAsNotVerified(_send_as_refusal(connection, mime["From"]))
        raise TransportUnavailable(
            f"Microsoft 365 rejected the message ({response.status_code}): {_said(response)}")
    draft = response.json()
    try:
        for filename, content, content_type in attachments_after:
            _attach(token, draft["id"], filename, content, content_type)
        sent = _call("POST", f"{GRAPH}/me/messages/{draft['id']}/send", token=token)
    except TransportUnavailable:
        _discard(token, draft["id"])
        raise
    if not sent.ok:
        _discard(token, draft["id"])
        if _error_code(sent) in ("ErrorSendAsDenied", "ErrorFromAddressNotPermitted"):
            raise SendAsNotVerified(_send_as_refusal(connection, mime["From"]))
        raise TransportUnavailable(
            f"Microsoft 365 did not send the message ({sent.status_code}): {_said(sent)}")
    return draft


class GraphTransport:
    name = "microsoft"

    def send(self, *, tenant, to_address, subject, body_text, thread,
             in_reply_to="", references="", attachments=(), body_html="",
             inline_images=(), from_address="", headers=None, also_to=(), mailbox=None):
        from config import environment

        if environment.is_demo():
            # The demo's promise rides on its one Gmail connection
            # (`transport.GmailTransport`); it is never a Microsoft practice.
            raise TransportUnavailable(
                "This is the demo. It sends through its own Gmail connection only.")
        if mailbox is not None and not mailbox.is_own:
            # A shared or a client's mailbox: its own token, its own addresses.
            from apps.crm.services import mailboxes

            connection = mailbox.connection
            if connection is None:
                raise TransportUnavailable(f"{mailbox.email_address} is disconnected.")
            if (from_address or "").lower() not in mailboxes.addresses(mailbox):
                from_address = mailboxes.address_of(mailbox)
            own = True
            sender = from_address
        else:
            connection = sending_connection_for(tenant, from_address)
            own = bool(from_address) and from_address.lower() == connection.email_address.lower()
            sender = (connection.email_address if own
                      else connection.send_as_address or tenant.from_address)
        token = access_token_for(connection)
        message_id = message_id_for(tenant, thread)

        def mime_with(carried):
            return build_mime(
                to_address=", ".join([to_address, *also_to]),
                from_address=sender,
                subject=subject, body_text=body_text, message_id=message_id,
                thread_token=thread.thread_token, in_reply_to=in_reply_to,
                references=references, attachments=carried, body_html=body_html,
                inline_images=inline_images, headers=headers,
            )

        mime, after = mime_with(attachments), ()
        if attachments and len(mime.as_bytes()) * 4 // 3 > REQUEST_LIMIT:
            mime, after = mime_with(()), attachments
        draft = send_mime(connection, token, mime, attachments_after=after)
        return {
            "provider": "microsoft",
            "provider_message_id": draft.get("id", ""),
            "gmail_message_id": "",
            "gmail_thread_id": "",
            "graph_conversation_id": draft.get("conversationId", ""),
            # What recipients' clients will quote back. [verify] whether
            # Exchange keeps the Message-ID we set; whichever it is, the
            # draft says, and that is what a reply's In-Reply-To will carry.
            "message_id_header": draft.get("internetMessageId") or message_id,
            "from_address": mime["From"],
            **({"mailbox": mailbox} if mailbox is not None and not mailbox.is_own
               else {"connection": connection}),
        }


# ------------------------------------------------- the practice address (D3)

def verify_send_as(connection, alias, *, save=True):
    """Confirm this account may send as the practice address.

    Graph has no send-as list. The account's own address always works; any
    other is checked by sending a short message from it to the account's own
    inbox and reading back, from Sent Items, who Microsoft says it was from.
    A refusal and a quiet rewrite to the account's own address both fail the
    check: the second is the one that would put the wrong sender on every
    digest a client receives.
    """
    def fail(message):
        if save:
            connection.send_as_error = message
            connection.send_as_verified_at = None
            connection.save(update_fields=["send_as_error", "send_as_verified_at", "updated_at"])
        raise SendAsNotVerified(message)

    def passed():
        if save:
            connection.send_as_address = alias
            connection.send_as_verified_at = timezone.now()
            connection.send_as_error = ""
            connection.save(update_fields=[
                "send_as_address", "send_as_verified_at", "send_as_error", "updated_at"])
        return True

    if not alias:
        fail("The practice has no address to send from yet. Choose one above.")
    if alias.lower() == connection.email_address.lower():
        return passed()

    from apps.crm.models import EmailThread
    from config.branding import PRODUCT_NAME

    token = access_token_for(connection)
    probe = EmailThread(thread_token=EmailThread.new_token())
    mime = build_mime(
        to_address=connection.email_address, from_address=alias,
        subject=f"Checking {alias} for {connection.tenant.name}",
        body_text=(f"{PRODUCT_NAME} sent this from {alias} to check that "
                   f"{connection.email_address} may send as it. Nothing else is in it, "
                   "and it can be deleted."),
        message_id=message_id_for(connection.tenant, probe),
        thread_token=probe.thread_token)
    try:
        draft = send_mime(connection, token, mime)
    except SendAsNotVerified as exc:
        fail(str(exc))
    except TransportUnavailable as exc:
        fail(f"The check could not be sent: {exc}")

    seen = ""
    for attempt in range(READ_BACK_TRIES):
        response = _call("GET", f"{GRAPH}/me/messages/{draft['id']}", token=token,
                         params={"$select": "from,sender,isDraft"})
        if response.ok:
            data = response.json()
            if not data.get("isDraft", False):
                seen = (((data.get("from") or {}).get("emailAddress") or {})
                        .get("address", "")).lower()
                break
        if attempt < READ_BACK_TRIES - 1:
            time.sleep(1)
    if not seen:
        fail(f"The check was sent from {alias}, but Microsoft 365 has not shown the copy in "
             "Sent Items yet. Check again in a minute.")
    if seen != alias.lower():
        fail(f"Microsoft 365 sent the check from {seen}, not {alias}. "
             + _send_as_refusal(connection, alias))
    return passed()


# ---------------------------------------------------------------- reading

def _received_ms(value: str) -> str:
    """Graph's `receivedDateTime` as the epoch milliseconds Gmail's
    `internalDate` carries, which `inbound` falls back on without a Date."""
    from datetime import datetime

    try:
        return str(int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000))
    except (AttributeError, ValueError):
        return ""


def _part(part) -> dict:
    """One MIME part in the shape `inbound` reads (Gmail's `payload`)."""
    shaped = {
        "mimeType": part.get_content_type(),
        "filename": part.get_filename() or "",
        "headers": [{"name": k, "value": str(v)} for k, v in part.items()],
    }
    if part.is_multipart():
        shaped["body"] = {"size": 0}
        shaped["parts"] = [_part(child) for child in part.iter_parts()]
        return shaped
    content = part.get_payload(decode=True) or b""
    if part.get_content_maintype() == "text" and not shaped["filename"]:
        # The text as text, in UTF-8, whatever charset it travelled in:
        # `inbound.bodies` decodes UTF-8.
        try:
            content = part.get_content().encode("utf-8")
        except (LookupError, KeyError, ValueError):
            pass
    shaped["body"] = {"size": len(content),
                      "data": base64.urlsafe_b64encode(content).decode()}
    return shaped


def mime_to_payload(raw: bytes, *, message_id: str, conversation_id: str,
                    received: str = "") -> dict:
    """A message's MIME, as Graph's `$value` returns it, in the shape a Gmail
    `threads.get` message has, so `inbound` reads both without knowing which.
    The headers are the real ones (Message-ID, In-Reply-To, References, the
    thread token), which is what matching rests on."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {
        "id": message_id,
        "provider": "microsoft",
        "conversationId": conversation_id,
        "internalDate": _received_ms(received),
        "payload": _part(message),
    }


class GraphReader:
    """The read half of a Microsoft connection (FR-6.5), the twin of
    `transport.GmailReader`. Fetches and reshapes; decides nothing."""

    def __init__(self, connection):
        self.connection = connection
        self._token = None

    def token(self):
        if self._token is None:
            self._token = access_token_for(self.connection)
        return self._token

    def _known(self, message_id: str, internet_id: str) -> bool:
        """Already filed, or one the app sent: the MIME is not fetched again.
        Gmail's `threads.get` returns every body every time; Graph would cost
        a request per message per poll, so the ones with nothing new to say
        are recognised from the listing."""
        from apps.crm.models import EmailMessage
        from apps.crm.services import inbound

        if inbound.already_have(self.connection.tenant, message_id, provider="microsoft"):
            return True
        ours = EmailMessage.objects.filter(direction="outbound")
        return (ours.filter(provider_message_id=message_id).exists()
                or bool(internet_id) and ours.filter(message_id_header=internet_id).exists())

    def thread(self, conversation_id: str) -> dict:
        """Every message in one conversation the app started. {} when there
        is none any more (deleted in Outlook): not an error."""
        url = f"{GRAPH}/me/messages"
        params = {
            "$filter": "conversationId eq '{}'".format(conversation_id.replace("'", "''")),
            "$select": "id,conversationId,internetMessageId,receivedDateTime,isDraft",
            "$top": "50",
        }
        listed = []
        while url:
            response = _call("GET", url, token=self.token(), params=params)
            if response.status_code == 404:
                return {}
            if not response.ok:
                raise TransportUnavailable(
                    f"Microsoft 365 would not return conversation {conversation_id[:24]}… "
                    f"({response.status_code}): {_said(response)[:200]}")
            data = response.json()
            listed.extend(data.get("value") or [])
            url, params = data.get("@odata.nextLink"), None
        if not listed:
            return {}

        messages = []
        for row in listed:
            if row.get("isDraft"):
                continue
            internet_id = row.get("internetMessageId") or ""
            if self._known(row["id"], internet_id):
                messages.append({
                    "id": row["id"], "provider": "microsoft",
                    "conversationId": row.get("conversationId") or conversation_id,
                    "payload": {"headers": [{"name": "Message-ID", "value": internet_id}]},
                })
                continue
            raw = _call("GET", f"{GRAPH}/me/messages/{row['id']}/$value", token=self.token(),
                        timeout=60)
            if raw.status_code == 404:
                continue
            if not raw.ok:
                raise TransportUnavailable(
                    f"Microsoft 365 would not return a message in conversation "
                    f"{conversation_id[:24]}… ({raw.status_code}).")
            messages.append(mime_to_payload(
                raw.content, message_id=row["id"],
                conversation_id=row.get("conversationId") or conversation_id,
                received=row.get("receivedDateTime", "")))
        return {"id": conversation_id, "provider": "microsoft", "messages": messages}

    def listing(self, after, *, limit=100) -> list[dict]:
        """The Mail tab's filing (2026-10-28): the oldest `limit` messages
        since `after`, by their envelope only."""
        from datetime import datetime

        def said(recipient):
            mail = (recipient or {}).get("emailAddress") or {}
            name, address = mail.get("name", ""), mail.get("address", "")
            return f"{name} <{address}>" if name else address

        response = _call("GET", f"{GRAPH}/me/messages", token=self.token(), params={
            "$filter": f"receivedDateTime gt {after.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "$orderby": "receivedDateTime asc", "$top": str(limit),
            "$select": "id,conversationId,internetMessageId,receivedDateTime,from,"
                       "toRecipients,ccRecipients,isDraft"})
        if not response.ok:
            raise TransportUnavailable(
                f"Microsoft 365 would not list new mail ({response.status_code}): "
                f"{_said(response)[:200]}")
        out = []
        for row in response.json().get("value") or []:
            if row.get("isDraft"):
                continue
            out.append({
                "id": row["id"], "thread": row.get("conversationId") or "",
                "at": datetime.fromisoformat(row["receivedDateTime"].replace("Z", "+00:00")),
                "from": said(row.get("from")),
                "to": ", ".join(said(r) for r in row.get("toRecipients") or []),
                "cc": ", ".join(said(r) for r in row.get("ccRecipients") or []),
                "message_id": row.get("internetMessageId") or ""})
        return out

    def full(self, envelope) -> dict:
        raw = _call("GET", f"{GRAPH}/me/messages/{envelope['id']}/$value", token=self.token(),
                    timeout=60)
        if raw.status_code == 404:
            return {}
        if not raw.ok:
            raise TransportUnavailable(
                f"Microsoft 365 would not return a message ({raw.status_code}).")
        return mime_to_payload(raw.content, message_id=envelope["id"],
                               conversation_id=envelope["thread"],
                               received=envelope["at"].strftime("%Y-%m-%dT%H:%M:%SZ"))

    def attachment(self, message_id: str, attachment_id: str) -> str:
        """Every attachment arrives inside the MIME, so there is never one to
        fetch separately; here so the reader has the shape `inbound` calls."""
        return ""
