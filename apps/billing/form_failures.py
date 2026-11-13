"""A card form that would not load (2026-11-13). Never silent.

When NMI's card fields can't be shown (the script did not load, it refused
the configuration, or the fields never appeared), the payer's browser reports
it here. Three things follow:

- **The payer is told what to do**, in words that name the practice: nothing
  was charged or saved, try again later, and, on an invoice, the other ways
  to pay that the invoice itself prints ("How to pay").
- **The practice owner gets a Notice** (kind "payments"), at most one a day
  for each place a form failed, so a run of tries is one Notice. A practice's
  subscription card is the platform's form, so that Notice goes to the
  platform owner instead.
- **An audit row and a log line** for every report, with what the browser
  said, cut short and scrubbed of anything shaped like a key.

What the browser sends is only ever used as text: the form kind and the host
are checked against the known values, the reason is cut to 300 characters,
and the report is rate-limited by its caller. It never changes a payment.
"""

from __future__ import annotations

import logging
import re
import uuid

from django.utils import timezone

log = logging.getLogger(__name__)

#: Where a card form is used.
LINK, PORTAL, AUTOPAY, SUBSCRIPTION = "link", "portal", "autopay", "subscription"
WHERE = (LINK, PORTAL, AUTOPAY, SUBSCRIPTION)
REASON_MOST = 300
#: A tokenization key's shape (Collect.js checks the same), and checkout keys.
_KEYS = re.compile(r"[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}"
                   r"|checkout_public_[A-Za-z0-9]{8,}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_NAMESPACE = uuid.UUID("6f1c2f0e-3b7a-4c55-9a51-1b2f1f6a9d10")


def clean_reason(value) -> str:
    text = value if isinstance(value, str) else ""
    text = _CONTROL.sub(" ", text).strip()
    text = _KEYS.sub("[key]", text)
    return text[:REASON_MOST] or "No reason was given."


def _form_words(form, host) -> str:
    from apps.billing import gateway as gw

    host = host if host in gw.API_HOSTS else ""
    if form == "collect":
        return f"Collect.js from {host}" if host else "Collect.js"
    if form == "component":
        return "NMI's Payment Component"
    return "the card form"


def _owners(tenant) -> list:
    from apps.tenancy.models import Membership, Role

    return list(Membership.all_objects.filter(tenant=tenant, role=Role.FF,
                                              revoked_at__isnull=True)
                .select_related("user"))


def _tell(tenant, *, key, title, text, url) -> int:
    """One Notice to each practice owner of `tenant`, once a day per `key`."""
    from apps.notify import service as notify
    from apps.notify.models import Kind

    source_id = uuid.uuid5(_NAMESPACE, f"{tenant.pk}:{key}:{timezone.localdate():%Y-%m-%d}")
    told = 0
    for owner in _owners(tenant):
        if notify.tell(tenant_id=tenant.pk, recipient_id=owner.user_id, kind=Kind.PAYMENTS,
                       title=title, text=text, url=url, source_type="card_form",
                       source_id=source_id):
            told += 1
    return told


def report(tenant, *, where, form="", host="", reason="", invoice=None, company=None,
           actor=None) -> str:
    """Record the failure, tell whoever can fix it, and return the sentence
    the payer sees."""
    from apps.billing import services
    from apps.tenancy.models import AuditEvent

    if where not in WHERE:
        raise ValueError(f"unknown place {where!r}")
    form = form if form in ("collect", "component") else ""
    reason = clean_reason(reason)
    words = _form_words(form, host)
    practice = services.practice_name(tenant)
    number = invoice.number if invoice is not None else ""

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="billing.card_form_failed",
        target_type="client_invoice" if invoice is not None else "tenant",
        target_id=invoice.pk if invoice is not None else tenant.pk,
        payload={"where": where, "form": words, "reason": reason,
                 **({"invoice": number} if number else {})})
    log.warning("card form failed: practice %s, %s, %s: %s", tenant.pk, where, words, reason)

    said = f"It said: {reason}"
    if where == SUBSCRIPTION:
        from apps.billing.subscriptions import owners_practice
        from config.branding import PRODUCT_NAME

        home = owners_practice()
        if home is not None:
            _tell(home, key=f"subscription:{tenant.pk}",
                  title="A subscription card form didn't load",
                  text=(f"{practice}'s owner couldn't load the card form ({words}) to save "
                        f"the subscription card. No card was saved. {said}"),
                  url="/practices")
        return (f"The card form could not be loaded, so no card was saved. {PRODUCT_NAME} "
                "has been told. Please try again later.")

    if where == AUTOPAY:
        name = company.name if company is not None else "A client"
        _tell(tenant, key=f"autopay:{company.pk if company is not None else ''}",
              title="A card form didn't load",
              text=(f"{name}'s client owner couldn't load the card form ({words}) to save a "
                    f"card for auto-pay. No card was saved. {said}"),
              url=f"/companies/{company.pk}" if company is not None else "")
        return (f"The card form could not be loaded, so no card was saved. {practice} "
                "has been told. Please try again later.")

    how = (invoice.pay_instructions or "").strip() if invoice is not None else ""
    payer = ("Someone with the pay link" if where == LINK
             else "A client in the portal")
    _tell(tenant, key=f"{where}:{invoice.pk if invoice is not None else ''}",
          title="A card form didn't load",
          text=(f"{payer} couldn't load the card form ({words}) to pay invoice {number}. "
                f"Nothing was charged. {said}"),
          url=f"/invoices/{invoice.pk}" if invoice is not None else "")
    message = (f"The card form could not be loaded, so nothing was charged. {practice} has "
               "been told.")
    if how:
        return f"{message} Please try again later, or pay another way: {how}"
    return f"{message} Please try again later."
