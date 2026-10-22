"""A card on file and auto-pay (P4 part 4, `docs/p4_billing.md` §3.4).

**The card.** Only a signed-in client owner saves one, in the portal: NMI's
fields make a one-time token in their browser, and the token becomes a record
in the **practice's own** Customer Vault. The app keeps the vault id, the
brand, the last four, the expiry, who added it and whether it was removed.
Never practice staff, never the pay link, never while someone of the practice
is acting as the client. One card per company; a new one replaces the old,
which is deleted from the vault.

**The consent.** A client owner turns auto-pay on by agreeing to the wording
shown, and that is kept as given: who, when, the exact words, their version,
the address and the browser. Any client owner of the company can turn it off
at any time; removing the card turns it off too. Both are kept.

**The charge.** The practice still approves every send. An invoice whose
email is queued while the company's consent stands says "will be charged to
the card ending NNNN on <date>" and is tied to that consent; on its due date
the daily job charges the card on file for the balance, while that consent
still stands. A failure leaves the invoice open, tells the client and the
practice owner, and is tried once more, on a later day. Nothing else is ever
retried. The job is safe to run twice: an attempt already made today, or one
still in flight, is never made again.

**Expiry.** Thirty days before a card's last month ends, the client is told
once to add the new one.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import escape

from apps.billing import card_payments, money, payment_accounts, services
from apps.billing import gateway as gw
from apps.billing.models import (
    AutopayConsent, ClientInvoice, ClientPaymentMethod, PaymentAttempt,
)

log = logging.getLogger(__name__)
A = PaymentAttempt.Status

#: The words a client owner agrees to. A change of wording is a new version;
#: what each person agreed to is kept on their consent as they saw it.
WORDING_VERSION = "2026-10-21"
WORDING = (
    "I authorize {practice} to charge the card on file for {company} for the full balance "
    "of each invoice it sends {company} from now on, on that invoice's due date. Each "
    "invoice email will say which card will be charged and on what date. If a charge "
    "fails, it will be tried once more. I can turn auto-pay off at any time in the "
    "portal, and it stops for any invoice not yet charged.")
#: How long before a card's last month ends the client is told.
EXPIRY_NOTICE = timedelta(days=30)


class AutopayRefused(Exception):
    """Refused, with a sentence for the client."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------- reading

def card_on_file(company) -> ClientPaymentMethod | None:
    return ClientPaymentMethod.all_objects.filter(client_company=company,
                                                  removed_at__isnull=True).first()


def standing_consent(company) -> AutopayConsent | None:
    return AutopayConsent.all_objects.filter(client_company=company,
                                             revoked_at__isnull=True).first()


def wording_for(company) -> str:
    return WORDING.format(practice=services.practice_name(company.tenant), company=company.name)


def expires_on(card) -> date:
    """The last day a card works: the end of its expiry month."""
    return date(card.exp_year, card.exp_month,
                calendar.monthrange(card.exp_year, card.exp_month)[1])


def state(company) -> dict:
    """What the portal shows a client owner."""
    card, consent = card_on_file(company), standing_consent(company)
    ready = payment_accounts.is_ready(company.tenant)
    account = payment_accounts.practice_account(company.tenant) if ready else None
    return {
        "ready": ready,
        "test_mode": card_payments.is_test_mode(company.tenant),
        "public_key": account.public_key if account else "",
        "card": card and {
            "brand": card.brand, "last4": card.last4,
            "expires": f"{card.exp_month:02d}/{card.exp_year % 100:02d}",
            "added_by": (card.added_by.full_name or card.added_by.email) if card.added_by else "",
            "added_at": card.created_at.isoformat()},
        "autopay": consent and {
            "since": consent.consented_at.isoformat(),
            "by": consent.consented_by.full_name or consent.consented_by.email},
        "wording": wording_for(company), "wording_version": WORDING_VERSION,
    }


# ----------------------------------------------------- the client's acts

def _refuse_acting():
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise AutopayRefused("A card and auto-pay are the client's own: nothing is saved or "
                             "agreed while acting as someone else.")


def save_card(company, *, user, payment_token) -> ClientPaymentMethod:
    """The token into the practice's vault; the card on file replaced."""
    _refuse_acting()
    if not isinstance(payment_token, str) or not payment_token.strip():
        raise AutopayRefused("The card details did not come through. Please try again.", 400)
    if not payment_accounts.is_ready(company.tenant):
        raise AutopayRefused(f"{services.practice_name(company.tenant)} cannot take cards yet.")
    account = payment_accounts.practice_account(company.tenant)
    first, _, last = (user.full_name or user.email).strip().partition(" ")
    try:
        record = gw.gateway().vault_add(account, payment_token=payment_token,
                                        billing=gw.Billing(first_name=first or "Card",
                                                           last_name=last or "Holder"))
    except gw.GatewayRefused as exc:
        raise AutopayRefused(f"The card could not be saved: {exc}") from None
    except gw.GatewayError:
        raise AutopayRefused("The card could not be saved just now. Please try again.",
                             503) from None
    exp = record.card_exp if len(record.card_exp) == 4 and record.card_exp.isdigit() else ""
    if not record.id or not exp:
        raise AutopayRefused("The card could not be saved just now. Please try again.", 503)
    row = payment_accounts.PaymentAccount.all_objects.get(tenant=company.tenant)
    with transaction.atomic():
        old = (ClientPaymentMethod.all_objects.select_for_update()
               .filter(client_company=company, removed_at__isnull=True).first())
        if old is not None:
            _mark_removed(old, user)
        card = ClientPaymentMethod.all_objects.create(
            tenant=company.tenant, client_company=company, vault_id=record.id,
            environment=row.environment, brand=record.brand, last4=record.last4,
            exp_month=int(exp[:2]), exp_year=2000 + int(exp[2:]), added_by=user)
        _audit(company, "card_saved", user, last4=card.last4,
               replaced=old.last4 if old else "")
    if old is not None:
        _delete_from_vault(old)
    return card


def remove_card(company, *, user) -> None:
    _refuse_acting()
    with transaction.atomic():
        card = (ClientPaymentMethod.all_objects.select_for_update()
                .filter(client_company=company, removed_at__isnull=True).first())
        if card is None:
            raise AutopayRefused("There is no card on file.", 404)
        _mark_removed(card, user)
        consent = standing_consent(company)
        if consent is not None:
            _revoke(consent, user, "Card removed")
        _audit(company, "card_removed", user, last4=card.last4)
    _delete_from_vault(card)


def _mark_removed(card, user) -> None:
    card.removed_at = timezone.now()
    card.removed_by = user
    card.save(update_fields=["removed_at", "removed_by", "updated_at"])


def _delete_from_vault(card) -> None:
    """Best effort: the row is already marked removed and is never charged."""
    try:
        gw.gateway().vault_delete(payment_accounts.practice_account(card.tenant), card.vault_id)
    except (gw.GatewayError, payment_accounts.PaymentAccountError) as exc:
        log.warning("card on file %s: not deleted from the vault (%s)", card.pk,
                    type(exc).__name__)


def consent(company, *, user, version, ip_address=None, user_agent="") -> AutopayConsent:
    _refuse_acting()
    if version != WORDING_VERSION:
        raise AutopayRefused("The auto-pay wording has changed. Please read it again.")
    if card_on_file(company) is None:
        raise AutopayRefused("Save a card first.")
    try:
        with transaction.atomic():
            row = AutopayConsent.all_objects.create(
                tenant=company.tenant, client_company=company, consented_by=user,
                consented_at=timezone.now(), wording=wording_for(company),
                wording_version=WORDING_VERSION, ip_address=ip_address or None,
                user_agent=(user_agent or "")[:400])
    except IntegrityError:
        raise AutopayRefused("Auto-pay is already on.") from None
    _audit(company, "autopay_on", user, version=WORDING_VERSION)
    return row


def revoke(company, *, user) -> None:
    _refuse_acting()
    with transaction.atomic():
        row = (AutopayConsent.all_objects.select_for_update()
               .filter(client_company=company, revoked_at__isnull=True).first())
        if row is None:
            raise AutopayRefused("Auto-pay is already off.")
        _revoke(row, user, "Turned off")


def _revoke(row, user, reason) -> None:
    row.revoked_at = timezone.now()
    row.revoked_by = user
    row.revoke_reason = reason
    row.save(update_fields=["revoked_at", "revoked_by", "revoke_reason", "updated_at"])
    _audit(row.client_company, "autopay_off", user, reason=reason)


def _audit(company, verb, user, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=user,
                                  verb=f"billing.{verb}", target_type="company",
                                  target_id=company.pk, payload=payload)


# --------------------------------------------------- the invoice email

def email_line(invoice) -> tuple[AutopayConsent | None, str]:
    """For an invoice email being queued: the standing consent it will be
    charged under, and the sentence that says so; or (None, "")."""
    if not invoice.client_company_id:
        return None, ""
    consent = standing_consent(invoice.client_company)
    card = card_on_file(invoice.client_company)
    if consent is None or card is None:
        return None, ""
    on = max(invoice.due_date, timezone.localdate())
    return consent, (f"This invoice will be charged to the card ending {card.last4} on "
                     f"{on:%B} {on.day}, {on.year}.")


def for_practice(invoice) -> dict | None:
    """The invoice page's plain line for the practice (finding B5, 2026-10-22):
    "Auto-pay is on for Acme: charged to Visa …1111 on the due date", and the
    sentence its email carries. A draft or ready invoice reads the company's
    standing consent, as its email will when it is queued; a sent one the
    consent it was tied to, while that still stands. None otherwise."""
    S = ClientInvoice.Status
    if not invoice.client_company_id or invoice.status in (S.PAID, S.VOID):
        return None
    card = card_on_file(invoice.client_company)
    if invoice.status in (S.DRAFT, S.READY):
        consent, email = email_line(invoice)
    else:
        consent = (AutopayConsent.all_objects.filter(pk=invoice.autopay_consent_id,
                                                     revoked_at__isnull=True).first()
                   if invoice.autopay_consent_id else None)
        email = ""
    if consent is None or card is None:
        return None
    return {"line": f"Auto-pay is on for {invoice.client_company.name}: charged to "
                    f"{card.brand or 'the card'} …{card.last4} on the due date",
            "email_line": email}


# ------------------------------------------------------------- the job

def run(tenant, *, today=None) -> dict:
    """Charge what is due, and tell clients of cards about to expire."""
    today = today or timezone.localdate()
    return {"charged": charge_due(tenant, today=today),
            "expiry_notices": expiry_notices(tenant, today=today)}


def due_invoices(tenant, today):
    return (ClientInvoice.all_objects
            .filter(tenant=tenant, status__in=ClientInvoice.OPEN, due_date__lte=today,
                    autopay_consent__isnull=False, autopay_consent__revoked_at__isnull=True,
                    sent_at__isnull=False)
            .select_related("autopay_consent", "client_company", "tenant")
            .order_by("due_date", "number"))


def charge_due(tenant, *, today) -> int:
    made = 0
    for invoice in due_invoices(tenant, today):
        consent = invoice.autopay_consent
        # Sent after consent, to the company that gave it.
        if invoice.sent_at < consent.consented_at \
                or consent.client_company_id != invoice.client_company_id \
                or invoice.balance_cents <= 0:
            continue
        card = card_on_file(invoice.client_company)
        if card is None or not _another_try_due(invoice, today):
            continue
        account_row = payment_accounts.PaymentAccount.all_objects.filter(tenant=tenant).first()
        if account_row is None or account_row.environment != card.environment:
            # Saved in the other environment's vault: it cannot be charged there.
            continue
        try:
            attempt, message = card_payments.charge_on_file(invoice, card=card)
        except card_payments.PaymentRefused:
            continue
        made += 1
        if attempt.status in (A.DECLINED, A.FAILED):
            _tell_failure(attempt, card, message)
    return made


def _another_try_due(invoice, today) -> bool:
    """None yet; or one that failed, on an earlier day. Never a third, never
    two in a day, never while one is in flight or after one went through."""
    tries = list(PaymentAttempt.all_objects.filter(invoice=invoice,
                                                   via=PaymentAttempt.Via.AUTOPAY)
                 .order_by("created_at"))
    if not tries:
        return True
    if len(tries) >= 2 or tries[0].status not in (A.DECLINED, A.FAILED):
        return False
    return timezone.localtime(tries[0].created_at).date() < today


def _tell_failure(attempt, card, message) -> None:
    """The client and the practice owner, at once. Never undoes anything."""
    try:
        _send_failure(attempt, card, message)
    except Exception as exc:  # noqa: BLE001 — the invoice is open either way
        log.warning("auto-pay %s: failure notice not sent (%s)", attempt.pk, type(exc).__name__)


def _send_failure(attempt, card, message) -> None:
    from apps.crm.models import OutboxMessage
    from apps.tenancy.context import tenant_context

    invoice = attempt.invoice
    first = PaymentAttempt.all_objects.filter(invoice=invoice,
                                              via=PaymentAttempt.Via.AUTOPAY).count() == 1
    amount = money.dollars(attempt.amount_cents)
    said = f'The card processor said: "{attempt.response_text}".' if attempt.response_text \
        else ""
    then = ("It will be tried once more tomorrow." if first
            else "It will not be tried again.")
    with tenant_context(invoice.tenant_id):
        client_lines = [
            f"We could not charge the card ending {card.last4} for invoice {invoice.number} "
            f"({amount}). {said}".strip(),
            f"The invoice is still open. {then} You can also pay it now in the portal, or "
            "add another card there.",
        ]
        for to in _client_addresses(invoice):
            _mail(invoice, OutboxMessage.Producer.AUTOPAY_NOTICE, to,
                  f"Auto-pay could not charge your card for invoice {invoice.number}",
                  client_lines, attempt)
        owner_lines = [
            f"Auto-pay could not charge {invoice.client_company.name}'s card ending "
            f"{card.last4} for invoice {invoice.number} ({amount}). {said}".strip(),
            f"The invoice is still open. {then} The client has been told.",
        ]
        for to in _owner_addresses(invoice.tenant):
            _mail(invoice, OutboxMessage.Producer.PAYMENT_NOTICE, to,
                  f"Auto-pay failed: invoice {invoice.number}", owner_lines, attempt,
                  internal=True)


def _client_addresses(invoice) -> list[str]:
    seen = []
    consent = invoice.autopay_consent
    for address in (invoice.email_to, consent.consented_by.email if consent else ""):
        if address and address.lower() not in (s.lower() for s in seen):
            seen.append(address)
    return seen


def _owner_addresses(tenant) -> list[str]:
    from apps.tenancy.models import Membership, Role

    return [m.user.email for m in Membership.all_objects.filter(
        tenant=tenant, role=Role.FF, revoked_at__isnull=True).select_related("user")
        if m.user.email]


def _mail(invoice, producer, to, subject, lines, source, *, internal=False) -> None:
    from apps.crm.services import email_layout, outbox

    outbox.create_message(
        tenant=invoice.tenant, producer=producer, to_address=to, subject=subject,
        body_text="\n\n".join(lines),
        body_html=email_layout.document(
            invoice.tenant, subject=subject, preheader=lines[0], internal=internal,
            content_html="".join(f"<p>{escape(line)}</p>" for line in lines)),
        thread=services._thread_for(invoice), source_type="payment_attempt",
        source_id=source.pk, force_direct=True)


def expiry_notices(tenant, *, today) -> int:
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.tenancy.context import tenant_context

    sent = 0
    cards = (ClientPaymentMethod.all_objects
             .filter(tenant=tenant, removed_at__isnull=True, expiry_notice_at__isnull=True)
             .select_related("client_company", "added_by"))
    for card in cards:
        last_day = expires_on(card)
        if today < last_day - EXPIRY_NOTICE:
            continue
        to = card.added_by.email if card.added_by else ""
        if not to:
            continue
        practice = services.practice_name(tenant)
        verb = "expired" if today > last_day else "expires"
        subject = f"Your card ending {card.last4} {verb} soon" if verb == "expires" \
            else f"Your card ending {card.last4} has expired"
        lines = [
            f"The card ending {card.last4} that {card.client_company.name} keeps on file with "
            f"{practice} {verb} at the end of {last_day:%B %Y}.",
            "Add the new card in the portal, under Invoices, so invoices can still be paid "
            "with it" + (" by auto-pay." if standing_consent(card.client_company) else "."),
        ]
        with tenant_context(tenant.pk):
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.AUTOPAY_NOTICE, to_address=to,
                subject=subject, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    tenant, subject=subject, preheader=lines[0],
                    content_html="".join(f"<p>{escape(line)}</p>" for line in lines)),
                source_type="client_payment_method", source_id=card.pk, force_direct=True)
        ClientPaymentMethod.all_objects.filter(pk=card.pk).update(expiry_notice_at=timezone.now())
        sent += 1
    return sent
