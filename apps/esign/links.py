"""The signing link (`/sign/<token>`), on the pay link's pattern
(`apps/billing/pay_links.py`).

- **Only the token's hash is stored.** The token is an HMAC, under the app's
  secret key, of the document and the moment its link was issued: a database
  read never yields a working link, and the app can print the same link again
  (the reminder, the demo's "Open the signing page").
- **Issued when the request email is delivered**, never stored on the Outbox
  row: the draft waiting for approval carries `{SignLink}`, and delivery
  fills it in.
- **One use.** Signing or declining clears the hash, and so does voiding;
  the document's expiry ends it too. A used, voided or expired link is the
  same refusal as a wrong one.
"""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.esign.models import Document

_SALT = "apps.esign.links"
#: The states a link opens: waiting on the signer.
LIVE = (Document.State.SENT, Document.State.VIEWED, Document.State.DRAFT)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _token(document) -> str:
    message = f"{document.pk}:{document.link_issued_at.isoformat()}"
    digest = salted_hmac(_SALT, message, algorithm="sha256").digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _root() -> str:
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return root.rstrip("/")


def url_of(document) -> str:
    """The live link, or "" when it has none (used, voided, never issued)."""
    if not document.link_hash or document.link_issued_at is None:
        return ""
    token = _token(document)
    if _hash(token) != document.link_hash:
        return ""
    return f"{_root()}/sign/{token}"


def ensure(document) -> str:
    """The document's link, issued now if it has none. Never for a document
    past waiting on its signer."""
    if document.state not in LIVE:
        return ""
    url = url_of(document)
    if url:
        return url
    document.link_issued_at = timezone.now()
    document.link_hash = _hash(_token(document))
    Document.all_objects.filter(pk=document.pk).update(
        link_issued_at=document.link_issued_at, link_hash=document.link_hash,
        updated_at=timezone.now())
    return url_of(document)


def clear(document) -> None:
    document.link_hash = ""
    Document.all_objects.filter(pk=document.pk).update(link_hash="", updated_at=timezone.now())


def document_for(raw: str):
    """The document a token opens, or None: wrong, used, voided or expired.
    Unscoped by necessity (no one is signed in) and narrow by design."""
    if not raw or len(raw) > 100:
        return None
    document = (Document.all_objects.filter(link_hash=_hash(raw),
                                            state__in=(Document.State.SENT,
                                                       Document.State.VIEWED))
                .exclude(link_hash="").select_related("tenant", "company").first())
    if document is None:
        return None
    if document.expires_at is not None and document.expires_at <= timezone.now():
        return None
    return document
