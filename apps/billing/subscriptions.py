"""Practice subscriptions: a practice pays the platform (P4 part 5,
`docs/p4_billing.md` §2, §5.1).

- **The platform account** is the NMI_* keys in the environment
  (`gateway.platform_account()`), never a practice's `tenant_secret`.
- **The card**: the practice owner, under Settings → Billing, "Your
  subscription", types it into NMI's own fields; the token becomes a record
  in the **platform's** Customer Vault. The app keeps the vault id, brand,
  last four and expiry.
- **On the 1st** the app's own job (`billing.charge_subscription`, daily, so
  a missed day catches up) makes the month's invoice with its PDF and makes
  one sale on the vault record carrying the invoice's reference,
  `sub-<invoice id>`. That reference is the only thing that ever marks a
  subscription invoice paid: a client payment carries its attempt's id, and
  each side refuses the other's (§1.2). No part-month: a card put on file
  mid-month is first charged on the next 1st. A change of amount applies from
  the next period.
- **A receipt for every charge that goes through**, with the invoice's PDF,
  to the practice's billing email. A failure leaves the invoice open and
  tells the practice owner, who updates the card and presses **Pay now**.
  A lost answer is looked up by the reference, never charged again blind.
- **Thirty days unpaid** makes the practice eligible for suspension, shown
  on the Practices screen; only the platform owner suspends. **Paying lifts
  it**, by Pay now, the monthly charge or the lookup.
- **The platform owner's own practice is never billed.**
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from apps.billing import gateway as gw
from apps.billing import money
from apps.billing.models import (
    BillingPlan, PracticeInvoice, PracticeInvoiceLine, PracticeSubscription,
    PracticeSubscriptionAddon,
)

log = logging.getLogger(__name__)
S = PracticeSubscription.Status
I = PracticeInvoice.Status
BETA_PLAN = "beta_at_cost"
#: An invoice unpaid this long after it was issued makes the practice
#: eligible for suspension (D2).
SUSPEND_AFTER = timedelta(days=30)
SELLER = "Noble Rose LLC, doing business as Execs NOW HQ"
CONTACT = "bryan.baker@getexecutivesnow.com"


class SubscriptionRefused(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------- reading

def is_owners_practice(tenant) -> bool:
    """The platform owner's own practice, which is never billed."""
    from apps.tenancy.models import Membership

    return Membership.all_objects.filter(tenant=tenant, role="FF", revoked_at__isnull=True,
                                         user__is_platform_owner=True).exists()


def subscription_for(tenant) -> PracticeSubscription:
    row = PracticeSubscription.all_objects.filter(tenant=tenant).first()
    owners = is_owners_practice(tenant)
    if row is None:
        plan, _ = BillingPlan.objects.get_or_create(
            code=BETA_PLAN, defaults={"name": "Beta at cost", "price_cents": 2000})
        try:
            with transaction.atomic():
                row = PracticeSubscription.all_objects.create(
                    tenant=tenant, plan=plan,
                    status=S.NOT_BILLED if owners else S.NEEDS_CARD)
        except IntegrityError:
            row = PracticeSubscription.all_objects.get(tenant=tenant)
    if owners and row.status != S.NOT_BILLED:
        PracticeSubscription.all_objects.filter(pk=row.pk).update(status=S.NOT_BILLED)
        row.status = S.NOT_BILLED
    return row


def base_cents(row) -> int:
    return row.amount_override_cents if row.amount_override_cents is not None \
        else row.plan.price_cents


def first_of_next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def period_of(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    return start, first_of_next_month(start) - timedelta(days=1)


def lines_for(row, period_start) -> list[tuple[str, int, object]]:
    """The base and each add-on charged from this period (D4)."""
    lines = [(f"{row.plan.name}, {period_start:%B %Y}", base_cents(row), None)]
    for item in (PracticeSubscriptionAddon.all_objects
                 .filter(subscription=row, charged_from__lte=period_start)
                 .filter(Q(removed_at__isnull=True) | Q(removed_at__date__gte=period_start))
                 .select_related("addon")):
        lines.append((f"{item.addon.name}, {period_start:%B %Y}", item.addon.price_cents,
                      item.addon))
    return lines


def eligible_for_suspension(tenant, *, now=None) -> bool:
    now = now or timezone.now()
    return PracticeInvoice.all_objects.filter(
        tenant=tenant, status=I.OPEN, issued_at__lte=now - SUSPEND_AFTER).exists()


def state(tenant) -> dict:
    """Settings → Billing, "Your subscription": the practice owner's."""
    row = subscription_for(tenant)
    account_ready = bool(settings.NMI_PUBLIC_TOKENIZATION_KEY and settings.NMI_PRIVATE_API_KEY)
    invoices = PracticeInvoice.all_objects.filter(tenant=tenant).order_by("-period_start")[:24]
    today = timezone.localdate()
    return {
        "status": row.status, "status_label": row.get_status_display(),
        "not_billed": row.status == S.NOT_BILLED,
        "plan": row.plan.name, "amount_cents": base_cents(row),
        "billing_email": row.billing_email or _owner_email(tenant),
        "card": ({"brand": row.card_brand, "last4": row.card_last4,
                  "expires": row.card_expires} if row.nmi_vault_id else None),
        "next_charge_on": (None if row.status == S.NOT_BILLED or not row.nmi_vault_id
                           else max(row.first_charge_on or today,
                                    first_of_next_month(today)).isoformat()),
        # The platform's public key, for NMI's card fields; never its private key.
        "public_key": settings.NMI_PUBLIC_TOKENIZATION_KEY if account_ready else "",
        "test_mode": settings.NMI_ENVIRONMENT != "live",
        "suspended": tenant.status == tenant.Status.SUSPENDED,
        "open_cents": sum(i.balance_cents for i in invoices if i.status == I.OPEN),
        "invoices": [{
            "id": str(i.pk), "number": i.number, "period_start": i.period_start.isoformat(),
            "total_cents": i.total_cents, "status": i.status,
            "status_label": i.get_status_display(),
            "paid_at": i.paid_at.isoformat() if i.paid_at else None,
            "checking": i.charge_state == "unknown",
            "last_charge_text": i.last_charge_text if i.status == I.OPEN else "",
        } for i in invoices],
    }


def _owner_email(tenant) -> str:
    from apps.tenancy.models import Membership

    owner = (Membership.all_objects.select_related("user")
             .filter(tenant=tenant, role="FF", revoked_at__isnull=True)
             .order_by("created_at").first())
    return owner.user.email if owner else ""


# --------------------------------------------------------------- the card

def save_card(tenant, *, user, payment_token) -> PracticeSubscription:
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise SubscriptionRefused("The practice's card is the practice owner's to enter.")
    row = subscription_for(tenant)
    if row.status == S.NOT_BILLED:
        raise SubscriptionRefused("Your practice is not billed.")
    if not isinstance(payment_token, str) or not payment_token.strip():
        raise SubscriptionRefused("The card details did not come through. Please try again.",
                                  400)
    account = gw.platform_account()
    first, _, last = (user.full_name or user.email).strip().partition(" ")
    try:
        record = gw.gateway().vault_add(account, payment_token=payment_token,
                                        billing=gw.Billing(first_name=first or "Card",
                                                           last_name=last or "Holder"))
    except gw.GatewayRefused as exc:
        raise SubscriptionRefused(f"The card could not be saved: {exc}") from None
    except gw.GatewayError:
        raise SubscriptionRefused("The card could not be saved just now. Please try again.",
                                  503) from None
    exp = record.card_exp if len(record.card_exp) == 4 and record.card_exp.isdigit() else ""
    if not record.id or not exp:
        raise SubscriptionRefused("The card could not be saved just now. Please try again.",
                                  503)
    old_vault = row.nmi_vault_id
    today = timezone.localdate()
    with transaction.atomic():
        row = PracticeSubscription.all_objects.select_for_update().get(pk=row.pk)
        row.nmi_vault_id, row.card_environment = record.id, settings.NMI_ENVIRONMENT
        row.card_brand, row.card_last4 = record.brand, record.last4
        row.card_expires = f"{exp[:2]}/{exp[2:]}"
        row.card_added_by, row.card_added_at = user, timezone.now()
        # No part-month: the first charge is the next 1st (§2.2).
        row.first_charge_on = row.first_charge_on or first_of_next_month(today)
        if row.status == S.NEEDS_CARD:
            row.status = S.ACTIVE
        row.save()
        _audit(tenant, "subscription_card_saved", user, last4=row.card_last4)
    if old_vault and old_vault != record.id:
        try:
            gw.gateway().vault_delete(account, old_vault)
        except gw.GatewayError as exc:
            log.warning("subscription %s: old card not deleted from the vault (%s)", row.pk,
                        type(exc).__name__)
    return row


# --------------------------------------------------------- the invoice

def _number(tenant, period_start) -> str:
    return f"ENH-{period_start:%Y%m}-{tenant.slug}"[:60]


def invoice_for_period(tenant, period_start, *, now=None) -> PracticeInvoice | None:
    """The month's invoice, made once. None when nothing is billed then."""
    now = now or timezone.now()
    row = subscription_for(tenant)
    if row.status in (S.NOT_BILLED, S.NEEDS_CARD, S.CANCELED) or not row.nmi_vault_id:
        return None
    if row.first_charge_on is None or period_start < row.first_charge_on:
        return None
    existing = PracticeInvoice.all_objects.filter(tenant=tenant,
                                                  period_start=period_start).first()
    if existing is not None:
        return existing
    _, period_end = period_of(period_start)
    lines = lines_for(row, period_start)
    total = sum(amount for _, amount, _ in lines)
    try:
        with transaction.atomic():
            invoice = PracticeInvoice.all_objects.create(
                tenant=tenant, number=_number(tenant, period_start), period_start=period_start,
                period_end=period_end, subtotal_cents=total, tax_cents=0, total_cents=total,
                issued_at=now, due_at=now)
            for position, (description, amount, addon) in enumerate(lines):
                PracticeInvoiceLine.all_objects.create(
                    tenant=tenant, invoice=invoice, position=position,
                    description=description, amount_cents=amount, addon=addon)
    except IntegrityError:
        return PracticeInvoice.all_objects.get(tenant=tenant, period_start=period_start)
    _store_pdf(invoice)
    return invoice


def render_pdf(invoice) -> bytes:
    from weasyprint import HTML

    from config.branding import PRODUCT_NAME

    long = lambda day: f"{day:%B} {day.day}, {day.year}"  # noqa: E731
    row = subscription_for(invoice.tenant)
    paid = ""
    if invoice.status == I.PAID and invoice.paid_at:
        card = " ".join(p for p in (row.card_brand, f"ending {row.card_last4}") if p)
        paid = (f"{money.dollars(invoice.amount_paid_cents)} charged to the {card} on "
                f"{long(timezone.localtime(invoice.paid_at).date())}. "
                f"Transaction {invoice.nmi_transaction_id}.")
    html = render_to_string("billing/practice_invoice.html", {
        "product": PRODUCT_NAME, "seller": SELLER, "contact": CONTACT,
        "number": invoice.number,
        "practice": invoice.tenant.legal_name or invoice.tenant.name,
        "billing_email": row.billing_email or _owner_email(invoice.tenant),
        "issued": long(timezone.localtime(invoice.issued_at).date()),
        "period": f"{long(invoice.period_start)} to {long(invoice.period_end)}",
        "lines": [{"description": line.description, "amount": money.dollars(line.amount_cents)}
                  for line in invoice.lines.all()],
        "subtotal": money.dollars(invoice.subtotal_cents),
        "tax": money.dollars(invoice.tax_cents), "total": money.dollars(invoice.total_cents),
        "paid": paid})
    return HTML(string=html).write_pdf()


def _store_pdf(invoice):
    from apps.tenancy import storage

    stored = storage.save(tenant=invoice.tenant, content=render_pdf(invoice),
                          object_key=storage.object_key("subscription-invoices",
                                                        f"Invoice-{invoice.number}.pdf"),
                          purpose="subscription_invoice_pdf", content_type="application/pdf")
    PracticeInvoice.all_objects.filter(pk=invoice.pk).update(pdf=stored)
    invoice.pdf = stored
    return stored


# ------------------------------------------------------------ charging

def charge(invoice, *, by=None) -> tuple[PracticeInvoice, str]:
    """One sale on the platform's vault record for the invoice's balance,
    carrying its reference. Never two at once, never one after a lost answer
    until the lookup has settled it."""
    with transaction.atomic():
        invoice = PracticeInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != I.OPEN or invoice.balance_cents <= 0:
            raise SubscriptionRefused(f"Invoice {invoice.number} is not open.")
        if invoice.charge_state in ("pending", "unknown"):
            raise SubscriptionRefused("A charge on this invoice is already being checked. "
                                      "It will show the result within the hour.")
        row = subscription_for(invoice.tenant)
        if row.status == S.NOT_BILLED:
            raise SubscriptionRefused("This practice is not billed.")
        if not row.nmi_vault_id:
            raise SubscriptionRefused("Add a card first.")
        if row.card_environment and row.card_environment != settings.NMI_ENVIRONMENT:
            raise SubscriptionRefused("The card on file was saved in the other NMI "
                                      "environment. Enter it again.")
        invoice.charge_state, invoice.charge_started_at = "pending", timezone.now()
        invoice.charge_tries += 1
        invoice.save(update_fields=["charge_state", "charge_started_at", "charge_tries",
                                    "updated_at"])
    try:
        txn = gw.gateway().sale(gw.platform_account(), amount_cents=invoice.balance_cents,
                                reference=invoice.reference, vault_id=row.nmi_vault_id)
    except gw.GatewayUnreachable:
        PracticeInvoice.all_objects.filter(pk=invoice.pk).update(charge_state="unknown")
        return invoice, ("We did not hear back from the card processor. We are checking "
                         "whether the charge went through; do not pay again until it shows.")
    except gw.GatewayRefused as exc:
        return _failed(invoice, str(exc), by=by)
    except gw.GatewayError as exc:
        return _failed(invoice, str(exc), by=by)
    return settle(invoice, txn)


def settle(invoice, txn: gw.Transaction) -> tuple[PracticeInvoice, str]:
    """Finish a charge from NMI's transaction. Only a transaction carrying
    this invoice's own reference marks it paid. Safe to run twice."""
    if txn.reference != invoice.reference:
        log.warning("subscription invoice %s: NMI transaction carries another reference; "
                    "ignored", invoice.pk)
        raise SubscriptionRefused("That charge is not this invoice's.")
    if not txn.approved:
        return _failed(invoice, txn.response_text or "Declined")
    with transaction.atomic():
        invoice = PracticeInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        if invoice.status == I.PAID:
            return invoice, _paid_message(invoice)
        invoice.status, invoice.paid_at = I.PAID, timezone.now()
        invoice.amount_paid_cents = invoice.total_cents
        invoice.nmi_transaction_id, invoice.charge_state = txn.id, ""
        invoice.last_charge_text = ""
        invoice.save()
        row = subscription_for(invoice.tenant)
        if row.status == S.PAST_DUE and not PracticeInvoice.all_objects.filter(
                tenant=invoice.tenant, status=I.OPEN).exists():
            PracticeSubscription.all_objects.filter(pk=row.pk).update(status=S.ACTIVE)
        _audit(invoice.tenant, "subscription_paid", None, number=invoice.number,
               amount_cents=invoice.amount_paid_cents, nmi_transaction_id=txn.id)
        lifted = _lift_if_paid_up(invoice.tenant)
        transaction.on_commit(lambda: _receipt(invoice.pk))
    message = _paid_message(invoice)
    return invoice, message + (" Your practice is no longer suspended." if lifted else "")


def _paid_message(invoice) -> str:
    return (f"Thank you. {money.dollars(invoice.amount_paid_cents)} was charged for invoice "
            f"{invoice.number}. A receipt is on its way by email.")


def _failed(invoice, text, *, by=None) -> tuple[PracticeInvoice, str]:
    PracticeInvoice.all_objects.filter(pk=invoice.pk).update(
        charge_state="", last_charge_text=(text or "")[:500])
    row = subscription_for(invoice.tenant)
    if row.status == S.ACTIVE:
        PracticeSubscription.all_objects.filter(pk=row.pk).update(status=S.PAST_DUE)
    invoice.refresh_from_db()
    if by is None:
        # The monthly charge failed: the owner is told. Pay now's own failure
        # is said on the screen to the person who pressed it.
        transaction.on_commit(lambda: _failure_notice(invoice.pk))
    said = f' The card processor said: "{text}".' if text else ""
    return invoice, (f"The card could not be charged for invoice {invoice.number}, and the "
                     f"invoice is still open.{said} Update the card and press Pay now.")


def pay_now(tenant, *, user) -> tuple[list[PracticeInvoice], str]:
    """Every open invoice, oldest first: one sale each. Stops at a failure."""
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise SubscriptionRefused("Nothing is paid while acting as someone else.")
    open_ = list(PracticeInvoice.all_objects.filter(tenant=tenant, status=I.OPEN)
                 .order_by("period_start"))
    if not open_:
        raise SubscriptionRefused("Nothing is owed.")
    done, message = [], ""
    for invoice in open_:
        invoice, message = charge(invoice, by=user)
        done.append(invoice)
        if invoice.status != I.PAID:
            break
    return done, message


def run(tenant, *, today=None) -> dict:
    """The daily job: the month's invoice and charge, from its 1st (a missed
    day catches up); and any lost answer looked up."""
    today = today or timezone.localdate()
    looked_up = resolve_unknown(tenant)
    period_start, _ = period_of(today)
    invoice = invoice_for_period(tenant, period_start)
    charged = 0
    if invoice is not None and invoice.status == I.OPEN and invoice.charge_tries == 0:
        try:
            charge(invoice)
            charged = 1
        except SubscriptionRefused:
            pass
    return {"charged": charged, "looked_up": looked_up}


def resolve_unknown(tenant) -> int:
    settled = 0
    stuck = PracticeInvoice.all_objects.filter(tenant=tenant, status=I.OPEN,
                                               charge_state__in=("pending", "unknown"))
    for invoice in stuck:
        if invoice.charge_state == "pending" and invoice.charge_started_at and \
                invoice.charge_started_at > timezone.now() - timedelta(minutes=5):
            continue
        try:
            txn = gw.gateway().find_by_reference(gw.platform_account(), invoice.reference)
        except gw.GatewayError:
            continue
        if txn is not None:
            try:
                settle(invoice, txn)
                settled += 1
            except SubscriptionRefused:
                pass
        elif invoice.charge_started_at and \
                invoice.charge_started_at < timezone.now() - timedelta(hours=1):
            PracticeInvoice.all_objects.filter(pk=invoice.pk).update(
                charge_state="", last_charge_text="NMI has no charge for it: nothing was "
                                                  "taken.")
            settled += 1
    return settled


# ---------------------------------------------------------- suspension

def suspend(tenant, *, actor, reason="") -> None:
    """The platform owner's, by hand, once eligible (D2). Its jobs stop but
    the subscription charge; no data changes."""
    from apps.tenancy.management.commands.ensure_schedules import (
        SUSPENDED_RUNS, remove_for,
    )
    from apps.tenancy.models import Tenant

    if is_owners_practice(tenant):
        raise SubscriptionRefused("Your own practice is not billed.")
    if tenant.status == Tenant.Status.ARCHIVED:
        raise SubscriptionRefused("An archived practice is not suspended.")
    if tenant.status == Tenant.Status.SUSPENDED:
        raise SubscriptionRefused("It is already suspended.")
    if not eligible_for_suspension(tenant):
        raise SubscriptionRefused("Only a practice with an invoice unpaid 30 days or more "
                                  "is suspended.")
    with transaction.atomic():
        tenant.status, tenant.suspended_at = Tenant.Status.SUSPENDED, timezone.now()
        tenant.suspension_reason = (reason or "A subscription invoice unpaid 30 days.")[:200]
        tenant.save(update_fields=["status", "suspended_at", "suspension_reason",
                                   "updated_at"])
        remove_for(tenant, keep=SUSPENDED_RUNS)
        _audit(tenant, "practice_suspended", actor, reason=tenant.suspension_reason)


def _lift_if_paid_up(tenant) -> bool:
    """Automatic (D3): suspended, and nothing open any more."""
    from apps.tenancy.models import Tenant

    tenant = Tenant.objects.get(pk=tenant.pk)
    if tenant.status != Tenant.Status.SUSPENDED:
        return False
    if PracticeInvoice.all_objects.filter(tenant=tenant, status=I.OPEN).exists():
        return False
    lift(tenant, actor=None)
    return True


def lift(tenant, *, actor) -> None:
    from apps.tenancy.management.commands.ensure_schedules import ensure_for
    from apps.tenancy.models import Tenant

    if tenant.status != Tenant.Status.SUSPENDED:
        raise SubscriptionRefused("It is not suspended.")
    tenant.status, tenant.suspended_at, tenant.suspension_reason = (
        Tenant.Status.ACTIVE, None, "")
    tenant.save(update_fields=["status", "suspended_at", "suspension_reason", "updated_at"])
    ensure_for(tenant)
    _audit(tenant, "practice_unsuspended", actor, automatic=actor is None)


# --------------------------------------------------------------- mail

def _receipt(invoice_id) -> None:
    """A receipt for every charge that went through, with the invoice's PDF,
    to the practice's billing email (the agreement promises it)."""
    try:
        invoice = PracticeInvoice.all_objects.select_related("tenant").get(pk=invoice_id)
        content = render_pdf(invoice)
        _store_pdf(invoice)
        row = subscription_for(invoice.tenant)
        to = row.billing_email or _owner_email(invoice.tenant)
        if not to:
            return
        from apps.crm.models import OutboxMessage
        from apps.platform import mail

        card = " ".join(p for p in (row.card_brand, f"ending {row.card_last4}") if p)
        mail.send_platform_mail(
            to=to, subject=f"Receipt: Execs NOW HQ invoice {invoice.number}",
            paragraphs=[
                f"Thank you. {money.dollars(invoice.amount_paid_cents)} was charged to your "
                f"{card} for {invoice.period_start:%B %Y}.",
                f"Invoice: {invoice.number}\nTransaction: {invoice.nmi_transaction_id}",
                "The invoice is attached, and is under Settings → Billing in the app."
                + (" (Test mode: no real money moved.)"
                   if settings.NMI_ENVIRONMENT != "live" else "")],
            producer=OutboxMessage.Producer.SUBSCRIPTION_RECEIPT,
            attachment=(content, f"Invoice-{invoice.number}.pdf"))
    except Exception as exc:  # noqa: BLE001 — the charge stands either way
        log.warning("subscription receipt %s not sent (%s)", invoice_id, type(exc).__name__)


def _failure_notice(invoice_id) -> None:
    try:
        invoice = PracticeInvoice.all_objects.select_related("tenant").get(pk=invoice_id)
        to = _owner_email(invoice.tenant)
        if not to:
            return
        from apps.crm.models import OutboxMessage
        from apps.platform import mail

        root = settings.PUBLIC_BASE_URL.rstrip("/")
        said = f' The card processor said: "{invoice.last_charge_text}".' \
            if invoice.last_charge_text else ""
        mail.send_platform_mail(
            to=to, subject=f"Your Execs NOW HQ payment did not go through ({invoice.number})",
            paragraphs=[
                f"We could not charge the card on file "
                f"{money.dollars(invoice.balance_cents)} for {invoice.period_start:%B %Y}."
                f"{said}",
                f"Update the card and press Pay now under Settings → Billing: "
                f"{root}/settings/billing",
                "An invoice left unpaid for 30 days can lead to your practice being "
                "suspended until it is paid, as the beta agreement says."],
            producer=OutboxMessage.Producer.SUBSCRIPTION_NOTICE)
    except Exception as exc:  # noqa: BLE001
        log.warning("subscription failure notice %s not sent (%s)", invoice_id,
                    type(exc).__name__)


def platform_summary(tenant) -> dict:
    """For the Practices screen (`apps/platform/billing.py`): amounts, dates
    and states only; never the card's details beyond "on file"."""
    row = subscription_for(tenant)
    open_ = list(PracticeInvoice.all_objects.filter(tenant=tenant, status=I.OPEN)
                 .order_by("issued_at"))
    oldest = open_[0].issued_at if open_ else None
    return {
        "status": row.status, "not_billed": row.status == S.NOT_BILLED,
        "amount_cents": base_cents(row), "plan_cents": row.plan.price_cents,
        "overridden": row.amount_override_cents is not None,
        "card_on_file": bool(row.nmi_vault_id),
        "open_cents": sum(i.balance_cents for i in open_),
        "oldest_open_days": (timezone.now() - oldest).days if oldest else None,
        "eligible_for_suspension": eligible_for_suspension(tenant),
        "suspended_at": tenant.suspended_at.isoformat() if tenant.suspended_at else None,
    }


def set_amount(tenant, amount_cents, *, actor) -> None:
    """The platform owner's figure for one practice (D9), from the next
    period (D4). None goes back to the plan's price."""
    if amount_cents is not None and (isinstance(amount_cents, bool)
                                     or not isinstance(amount_cents, int) or amount_cents < 0):
        raise SubscriptionRefused("The amount is a whole number of cents, 0 or more.", 400)
    row = subscription_for(tenant)
    PracticeSubscription.all_objects.filter(pk=row.pk).update(
        amount_override_cents=amount_cents, updated_at=timezone.now())
    _audit(tenant, "subscription_amount_set", actor, amount_cents=amount_cents)


def archived(tenant) -> None:
    """Archiving cancels the subscription at once: no further charge (§2.2)."""
    PracticeSubscription.all_objects.filter(tenant=tenant).exclude(
        status=S.NOT_BILLED).update(status=S.CANCELED, updated_at=timezone.now())


def unarchived(tenant) -> None:
    """Unarchiving starts it again, from the next 1st."""
    row = PracticeSubscription.all_objects.filter(tenant=tenant, status=S.CANCELED).first()
    if row is not None:
        has_card = bool(row.nmi_vault_id)
        PracticeSubscription.all_objects.filter(pk=row.pk).update(
            status=S.ACTIVE if has_card else S.NEEDS_CARD,
            first_charge_on=first_of_next_month(timezone.localdate()) if has_card else None,
            updated_at=timezone.now())


def _audit(tenant, verb, actor, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb=f"billing.{verb}",
                                  target_type="tenant", target_id=tenant.pk, payload=payload)
