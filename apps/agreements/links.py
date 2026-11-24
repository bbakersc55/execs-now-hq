"""The owner's agreement link: /a/<token> on the form's own domain, or
ENHQ's host + /forms/<slug>/a/<token> until a domain is set (the intake form's
addresses, apps/intake/links.py).

Only the token's hash is stored. The token is an HMAC, under the app's secret
key, of the agreement and the moment its link was issued, so the app can print
the same link again (a reminder, Copy link) and a database read never yields
a working one. The link always opens the agreement's current version.

Owners 2 to 4 (owner, 2026-11-24) each have their own link, made the same way
from their row, issued when their turn to sign comes.
"""

from __future__ import annotations

import base64
import hashlib

from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import CoOwner, OwnerAgreement

_SALT = "apps.agreements.links"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _token(agreement) -> str:
    if isinstance(agreement, CoOwner):
        message = f"{agreement.agreement_id}:{agreement.position}:" \
                  f"{agreement.link_issued_at.isoformat()}"
    else:
        message = f"{agreement.pk}:{agreement.link_issued_at.isoformat()}"
    digest = salted_hmac(_SALT, message, algorithm="sha256").digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def ensure(agreement) -> str:
    """The agreement's (or a co-owner's) token, issued now (and saved) if it
    has none."""
    if not agreement.link_hash or agreement.link_issued_at is None:
        agreement.link_issued_at = timezone.now()
        agreement.link_hash = _hash(_token(agreement))
        agreement.save(update_fields=["link_issued_at", "link_hash"])
    return _token(agreement)


def url_for(agreement, form, co_owner=None) -> str:
    from apps.intake.links import form_base

    return f"{form_base(form)}/a/{ensure(co_owner or agreement)}"


def resolve_signer(raw: str):
    """(the agreement, which owner: 1 to 4), or (None, 0)."""
    if not raw or len(raw) > 100:
        return None, 0
    found = (OwnerAgreement.all_objects.select_related("company")
             .filter(link_hash=_hash(raw)).first())
    if found is not None:
        return found, 1
    co = (CoOwner.all_objects.select_related("agreement__company")
          .filter(link_hash=_hash(raw)).first())
    if co is not None:
        return co.agreement, co.position
    return None, 0


def resolve(raw: str):
    return resolve_signer(raw)[0]
