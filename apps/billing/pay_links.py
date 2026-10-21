"""The signed pay link (P4 part 3, `docs/p4_billing.md` §3.4).

`/pay/<token>` pays one invoice without signing in. It is printed on the PDF
and put in the invoice email as `{PayLink}`.

- **Only the token's hash is stored.** The token itself is an HMAC, under the
  app's secret key, of the invoice and the moment its link was issued: a
  database read never yields a working link, and the app can still print the
  same link again (a resend, a reopened draft made ready again). If the
  secret key ever changes, the old link keeps working (it is found by its
  hash) and the next resend issues a new one.
- **Issued when the invoice is made ready**, if the practice's card account
  is ready then; otherwise when it is next sent. An invoice sent before
  links existed gets one when it is resent.
- **The practice is found from the token.** Nothing else is reachable with it:
  the invoice's number, amount due, due date, its PDF, and the card form.
- **It stops working when the invoice is voided** (the hash is cleared), and
  is not there before the invoice was sent. A paid invoice shows Paid.

The only copies of a link are where it was meant to go: the stored PDF and
the email, as sent, in the Outbox.
"""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.billing.models import ClientInvoice

_SALT = "apps.billing.pay_links"
#: The statuses a link pays or shows: sent, and after. Not before the email
#: has gone (ready), and never void.
LIVE = (ClientInvoice.Status.SENT, ClientInvoice.Status.PARTIALLY_PAID,
        ClientInvoice.Status.PAID)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _token(invoice) -> str:
    message = f"{invoice.pk}:{invoice.pay_link_issued_at.isoformat()}"
    digest = salted_hmac(_SALT, message, algorithm="sha256").digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _root() -> str:
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return root.rstrip("/")


def url_of(invoice) -> str:
    """The invoice's pay link, or "" when it has none (or its token can no
    longer be made, after a change of secret key)."""
    if not invoice.pay_token_hash or invoice.pay_link_issued_at is None:
        return ""
    token = _token(invoice)
    if _hash(token) != invoice.pay_token_hash:
        return ""
    return f"{_root()}/pay/{token}"


def ensure(invoice) -> bool:
    """Give the invoice its link if it has none and can take a card payment.
    Call with the invoice locked. Returns whether a new link was issued."""
    from apps.billing import payment_accounts

    if url_of(invoice) or invoice.status == ClientInvoice.Status.VOID:
        return False
    if not payment_accounts.is_ready(invoice.tenant):
        return False
    invoice.pay_link_issued_at = timezone.now()
    invoice.pay_token_hash = _hash(_token(invoice))
    ClientInvoice.all_objects.filter(pk=invoice.pk).update(
        pay_link_issued_at=invoice.pay_link_issued_at, pay_token_hash=invoice.pay_token_hash,
        updated_at=timezone.now())
    return True


def invoice_for(raw: str) -> ClientInvoice | None:
    """The invoice a token pays, or None: wrong, voided, or not yet sent.
    Unscoped by necessity (no one is signed in) and narrow by design."""
    if not raw or len(raw) > 100:
        return None
    return (ClientInvoice.all_objects.filter(pay_token_hash=_hash(raw), status__in=LIVE)
            .exclude(pay_token_hash="").select_related("tenant").first())
