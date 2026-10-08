"""Client invoices: writing, numbering, sending, and recording that one was
paid (`docs/p4a_client_invoicing.md`).

No payment is taken here. An invoice goes out through the Sending queue with
its PDF, on the practice owner's approval, and money received is recorded by
hand.

What this module keeps true:

- **A number is given once**, when an invoice is made ready, under a lock on
  the practice's counter, and never cleared or reused. A numbered invoice is
  voided, never deleted.
- **Ready means frozen.** Who it bills, its lines, its words and its PDF are
  fixed from then; "back to draft" reopens it with its number.
- **Nothing sends from here.** Making ready queues a message that waits for
  the practice owner.
- **Every change of state writes an audit event**, with what it was, what it
  is and why.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.billing import money
from apps.billing.models import (
    ClientInvoice, ClientInvoiceLine, ClientInvoiceSchedule, ClientPayment, InvoiceSettings,
)
from apps.tenancy.models import AuditEvent, Role

S = ClientInvoice.Status
K = ClientInvoice.Kind

LINES_MOST = 50
DEFAULT_SUBJECT = "Invoice {Number} from {Practice}"
DEFAULT_BODY = ("Hi {First name},\n\nInvoice {Number} for {Total} is attached. "
                "It is due {Due date}.\n\nThank you,\n{Practice}")
MERGE_FIELDS = ("Client", "First name", "Number", "Total", "Due date", "Practice")
_MERGE = re.compile(r"\{([A-Za-z ]+)\}")


class BillingError(Exception):
    """Refused, with a sentence for whoever asked."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ helpers

def audit(invoice, verb, actor, **payload):
    AuditEvent.all_objects.create(
        tenant_id=invoice.tenant_id, actor=actor, verb=f"billing.{verb}",
        target_type="client_invoice", target_id=invoice.pk,
        payload={"number": invoice.number or "", **payload})


def settings_for(tenant) -> InvoiceSettings:
    row, _made = InvoiceSettings.all_objects.get_or_create(tenant=tenant)
    return row


def practice_name(tenant) -> str:
    from apps.crm.services import email_layout

    brand = email_layout.branding(tenant)
    return brand.display_name or brand.practice_name


def unknown_merge_fields(text: str) -> list[str]:
    return sorted({field for field in _MERGE.findall(text or "")
                   if field not in MERGE_FIELDS})


def _check_merge(text: str) -> None:
    unknown = unknown_merge_fields(text)
    if unknown:
        raise BillingError(
            "There is no merge field called " + ", ".join(f"{{{f}}}" for f in unknown)
            + ". The ones you can use: " + ", ".join(f"{{{f}}}" for f in MERGE_FIELDS) + ".")


def _a_date(value, what) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BillingError(f"{what} is a date, as YYYY-MM-DD.") from None


def is_overdue(invoice, today=None) -> bool:
    """Not a status: worked out when read, so it cannot go stale."""
    today = today or timezone.localdate()
    return invoice.status in ClientInvoice.OPEN and invoice.due_date < today


# ---------------------------------------------------------------- settings

EDITABLE_SETTINGS = ("prefix", "next_value", "terms_days", "default_notes", "default_terms",
                     "pay_instructions", "email_subject", "email_body")


@transaction.atomic
def update_settings(tenant, changes: dict, *, actor=None) -> InvoiceSettings:
    row = InvoiceSettings.all_objects.select_for_update().get(pk=settings_for(tenant).pk)
    unknown = set(changes) - set(EDITABLE_SETTINGS)
    if unknown:
        raise BillingError(f"Not a setting: {', '.join(sorted(unknown))}.")
    if "prefix" in changes:
        prefix = str(changes["prefix"] or "").strip()
        if len(prefix) > 12 or not re.fullmatch(r"[A-Za-z0-9._/-]*", prefix):
            raise BillingError("A prefix is up to 12 letters, digits, dots, dashes or "
                               "slashes.")
        row.prefix = prefix
    if "next_value" in changes:
        value = changes["next_value"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BillingError("The next number is a whole number, 1 or more.")
        # Raised to carry on from an older system; never lowered, because a
        # lower number may already be on an invoice.
        if value < row.next_value:
            raise BillingError(f"The next number can be raised, not lowered: it is "
                               f"{row.next_value} now.")
        row.next_value = value
    if "terms_days" in changes:
        days = changes["terms_days"]
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 365:
            raise BillingError("Payment terms are a number of days, 0 to 365.")
        row.terms_days = days
    for field in ("default_notes", "default_terms", "pay_instructions", "email_body"):
        if field in changes:
            setattr(row, field, str(changes[field] or "").strip())
    if "email_subject" in changes:
        row.email_subject = " ".join(str(changes["email_subject"] or "").split())[:200]
    _check_merge(row.email_subject)
    _check_merge(row.email_body)
    row.save()
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="billing.settings_changed",
        target_type="invoice_settings", target_id=row.pk,
        payload={"fields": sorted(changes)})
    return row


# ------------------------------------------------------------------- drafts

def _clean_lines(tenant, lines) -> list[dict]:
    from apps.work.models import Goal, Project

    if not isinstance(lines, list):
        raise BillingError("lines is a list.")
    if len(lines) > LINES_MOST:
        raise BillingError(f"An invoice holds {LINES_MOST} lines at most.")
    out = []
    for raw in lines:
        if not isinstance(raw, dict):
            raise BillingError("Each line is an object.")
        description = str(raw.get("description") or "").strip()
        if not description:
            raise BillingError("Every line needs a description.")
        try:
            quantity = Decimal(str(raw.get("quantity", "1"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise BillingError("A quantity is a number, to two decimals.") from None
        if quantity < 0 or quantity > Decimal("99999999.99"):
            raise BillingError("A quantity is between 0 and 99,999,999.99.")
        price = money.cents(raw.get("unit_price_cents", 0), what="A unit price")
        project = goal = None
        if raw.get("project"):
            project = Project.all_objects.filter(tenant=tenant, pk=raw["project"]).first()
            if project is None:
                raise BillingError("That project is not in this practice.", status=404)
        if raw.get("goal"):
            goal = Goal.all_objects.filter(tenant=tenant, pk=raw["goal"]).first()
            if goal is None:
                raise BillingError("That goal is not in this practice.", status=404)
        out.append({"description": description, "quantity": quantity,
                    "unit_price_cents": price,
                    "amount_cents": money.line_amount(quantity, price),
                    "project": project, "goal": goal})
    return out


def _write_lines(invoice, lines: list[dict]) -> None:
    ClientInvoiceLine.all_objects.filter(invoice=invoice).delete()
    for position, line in enumerate(lines):
        ClientInvoiceLine.all_objects.create(tenant_id=invoice.tenant_id, invoice=invoice,
                                             position=position, **line)
    invoice.subtotal_cents = sum(line["amount_cents"] for line in lines)
    invoice.total_cents = invoice.subtotal_cents + invoice.tax_cents


def _recipient(tenant, *, kind, company, contact):
    """Who an invoice may be addressed to. A client invoice goes to a contact
    at that client company; a contact invoice to any one contact."""
    if contact is None or contact.tenant_id != tenant.pk or contact.deleted_at is not None:
        raise BillingError("Choose who the invoice is addressed to.")
    if kind == K.CONTACT:
        if company is not None:
            raise BillingError("An invoice to a contact names no client company.")
        return
    if company is None or company.tenant_id != tenant.pk or company.deleted_at is not None:
        raise BillingError("Choose the client company the invoice is for.")
    if not company.is_client_company:
        raise BillingError(f"“{company.name}” is not a client company. To bill someone "
                           "who is not a client, write an invoice to the contact.")
    if contact.company_id != company.pk:
        raise BillingError("The person it is addressed to has to be at that client "
                           "company.")


EDITABLE = ("issue_date", "due_date", "tax_cents", "notes", "terms", "pay_instructions",
            "email_to", "email_subject", "email_body", "bill_to_address")


def _apply(invoice, changes: dict, config: InvoiceSettings) -> None:
    if "issue_date" in changes:
        invoice.issue_date = _a_date(changes["issue_date"], "The issue date")
        if "due_date" not in changes:
            invoice.due_date = invoice.issue_date + timedelta(days=config.terms_days)
    if "due_date" in changes:
        invoice.due_date = _a_date(changes["due_date"], "The due date")
    if invoice.due_date < invoice.issue_date:
        raise BillingError("The due date cannot be before the issue date.")
    if "tax_cents" in changes:
        invoice.tax_cents = money.cents(changes["tax_cents"], what="Tax")
    for field in ("notes", "terms", "pay_instructions", "email_body"):
        if field in changes:
            setattr(invoice, field, str(changes[field] or "").strip())
    if "email_subject" in changes:
        invoice.email_subject = " ".join(str(changes["email_subject"] or "").split())[:200]
    if "email_to" in changes:
        invoice.email_to = str(changes["email_to"] or "").strip()
    if "bill_to_address" in changes:
        invoice.bill_to = {**(invoice.bill_to or {}),
                           "address": str(changes["bill_to_address"] or "").strip()}
    _check_merge(invoice.email_subject)
    _check_merge(invoice.email_body)


@transaction.atomic
def create_draft(tenant, *, actor, kind=K.ONE_OFF, client_company=None, contact=None,
                 lines=(), schedule=None, **changes) -> ClientInvoice:
    if kind not in K.values:
        raise BillingError("kind is one_off, recurring or contact.")
    _recipient(tenant, kind=kind, company=client_company, contact=contact)
    config = settings_for(tenant)
    today = timezone.localdate()
    invoice = ClientInvoice(
        tenant=tenant, kind=kind, client_company=client_company, contact=contact,
        schedule=schedule, issue_date=today,
        due_date=today + timedelta(days=config.terms_days),
        notes=config.default_notes, terms=config.default_terms,
        pay_instructions=config.pay_instructions,
        email_subject=config.email_subject or DEFAULT_SUBJECT,
        email_body=config.email_body or DEFAULT_BODY, created_by=actor)
    _apply(invoice, changes, config)
    invoice.save()
    _write_lines(invoice, _clean_lines(tenant, list(lines)))
    invoice.save()
    audit(invoice, "invoice_created", actor, kind=kind,
          **({"from_schedule": str(schedule.pk)} if schedule else {}))
    return invoice


def _only_draft(invoice):
    if invoice.status != S.DRAFT:
        raise BillingError(
            f"Invoice {invoice.number} is {invoice.get_status_display().lower()} and "
            "cannot be edited. "
            + ("Send it back to draft first." if invoice.status == S.READY
               else "Void it and write a new one."), status=409)


@transaction.atomic
def update_draft(invoice, *, actor, lines=None, contact=None, **changes) -> ClientInvoice:
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    _only_draft(invoice)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise BillingError(f"Not editable: {', '.join(sorted(unknown))}.")
    if contact is not None:
        _recipient(invoice.tenant, kind=invoice.kind, company=invoice.client_company,
                   contact=contact)
        invoice.contact = contact
    _apply(invoice, changes, settings_for(invoice.tenant))
    if lines is not None:
        _write_lines(invoice, _clean_lines(invoice.tenant, lines))
    invoice.total_cents = invoice.subtotal_cents + invoice.tax_cents
    invoice.save()
    return invoice


@transaction.atomic
def delete_draft(invoice, *, actor) -> None:
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != S.DRAFT or invoice.number:
        raise BillingError(
            f"Invoice {invoice.number} has a number and cannot be deleted. Void it "
            "instead, so the number is accounted for.", status=409)
    audit(invoice, "draft_deleted", actor, total_cents=invoice.total_cents)
    invoice.delete()


# -------------------------------------------------------- ready and sending

def merge_values(invoice) -> dict:
    contact = invoice.contact
    return {
        "Client": (invoice.client_company.name if invoice.client_company_id
                   else f"{contact.first_name} {contact.last_name}".strip()),
        "First name": contact.first_name or "there",
        "Number": invoice.number or "",
        "Total": money.dollars(invoice.total_cents),
        "Due date": f"{invoice.due_date:%B} {invoice.due_date.day}, {invoice.due_date.year}",
        "Practice": practice_name(invoice.tenant),
    }


def render(text: str, values: dict) -> str:
    return _MERGE.sub(lambda match: values.get(match.group(1), match.group(0)), text or "")


def _address_of(invoice) -> str:
    typed = ((invoice.bill_to or {}).get("address") or "").strip()
    if typed or not invoice.client_company_id:
        return typed
    # A company's address is kept as {"lines": [...]}.
    address = invoice.client_company.address or {}
    lines = address.get("lines") if isinstance(address, dict) else None
    return "\n".join(str(line) for line in (lines or []) if line)


def _email_of(contact) -> str:
    primary = contact.primary_email
    return (getattr(primary, "address", primary) or "").strip()


@transaction.atomic
def make_ready(invoice, *, actor, role) -> ClientInvoice:
    """Give it its number, freeze it, store its PDF and queue the email for the
    practice owner's approval. Sends nothing."""
    from apps.billing import pdf
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise BillingError("An invoice cannot be made ready while you are acting as "
                           "someone else: nothing is sent that way.", status=409)
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != S.DRAFT:
        raise BillingError(f"Invoice {invoice.number} is already "
                           f"{invoice.get_status_display().lower()}.", status=409)
    if not ClientInvoiceLine.all_objects.filter(invoice=invoice).exists():
        raise BillingError("An invoice needs at least one line.")
    if invoice.total_cents <= 0:
        raise BillingError("An invoice for nothing cannot be sent.")
    # The lock on the practice's counter is what makes twenty invoices made
    # ready at once take twenty consecutive numbers.
    config = InvoiceSettings.all_objects.select_for_update().get(
        pk=settings_for(invoice.tenant).pk)
    invoice.pay_instructions = invoice.pay_instructions or config.pay_instructions
    if not invoice.pay_instructions.strip():
        raise BillingError("Say how to pay first, in the invoice settings: with no "
                           "payment link it is the only way your client knows.")
    invoice.email_to = invoice.email_to or _email_of(invoice.contact)
    if not invoice.email_to:
        raise BillingError(f"{invoice.contact} has no email address to send it to.")
    before = invoice.status
    if not invoice.number:
        invoice.number = f"{config.prefix}{config.next_value:04d}"
        InvoiceSettings.all_objects.filter(pk=config.pk).update(
            next_value=F("next_value") + 1)
    contact = invoice.contact
    invoice.bill_to = {
        "name": f"{contact.first_name} {contact.last_name}".strip(),
        "company": invoice.client_company.name if invoice.client_company_id else "",
        "email": invoice.email_to, "address": _address_of(invoice),
    }
    values = merge_values(invoice)
    invoice.email_subject = render(invoice.email_subject or DEFAULT_SUBJECT, values)
    invoice.email_body = render(invoice.email_body or DEFAULT_BODY, values)
    invoice.status = S.READY
    invoice.ready_at = timezone.now()
    invoice.save()
    invoice.pdf = pdf.store(invoice)
    invoice.save(update_fields=["pdf", "updated_at"])
    audit(invoice, "invoice_ready", actor, before=before, after=S.READY,
          total_cents=invoice.total_cents)
    _queue(invoice, actor=actor, role=role)
    return invoice


def _thread_for(invoice):
    """An invoice and the replies to it live on a thread of their own, marked
    financial, so they are not part of the history an assistant shares."""
    from apps.crm.models import EmailThread

    thread = EmailThread.all_objects.filter(
        tenant_id=invoice.tenant_id, contact=invoice.contact, is_financial=True,
        client_company=invoice.client_company).first()
    if thread is None:
        thread = EmailThread.all_objects.create(
            tenant_id=invoice.tenant_id, contact=invoice.contact,
            client_company=invoice.client_company, is_financial=True,
            thread_token=EmailThread.new_token(), subject=invoice.email_subject)
    return thread


def _queue(invoice, *, actor, role, to_address=None):
    """The email into the Sending queue, waiting. The PDF attached is the one
    stored. Never direct: the Outbox has no rule that sends an invoice by
    itself."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    message = outbox.create_message(
        tenant=invoice.tenant, producer=OutboxMessage.Producer.CLIENT_INVOICE,
        to_address=to_address or invoice.email_to, to_contact=invoice.contact,
        subject=invoice.email_subject, body_text=invoice.email_body, role=role,
        actor=actor, thread=_thread_for(invoice), source_type="client_invoice",
        source_id=invoice.pk,
        attachments=[(invoice.pdf, f"Invoice-{invoice.number}.pdf")])
    invoice.outbox_message = message
    invoice.save(update_fields=["outbox_message", "updated_at"])
    return message


def _waiting(invoice):
    from apps.crm.models import OutboxMessage

    message = invoice.outbox_message
    if message is not None and message.state in (OutboxMessage.State.PENDING_APPROVAL,
                                                 OutboxMessage.State.DRAFT):
        return message
    return None


@transaction.atomic
def send(invoice, *, actor, role, to_address=None) -> ClientInvoice:
    """The practice owner's approval, from the invoice itself: the PDF and the
    whole email are on that page, which is what approving is (I3). Also
    "resend" for one already sent, to the same or another address."""
    from apps.crm.services import outbox
    from apps.tenancy.context import get_acting

    if role != Role.FF:
        raise BillingError("Only the practice owner can send an invoice.", status=403)
    if get_acting() is not None:
        raise BillingError("Nothing is sent while you are acting as someone else.",
                           status=409)
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status in (S.DRAFT, S.VOID):
        raise BillingError("Make the invoice ready before sending it." if invoice.status
                           == S.DRAFT else "A void invoice is not sent.", status=409)
    message = _waiting(invoice)
    if message is None or (to_address and to_address != message.to_address):
        if message is not None:
            outbox.reject(message, actor=actor)
        message = _queue(invoice, actor=actor, role=role, to_address=to_address)
    try:
        outbox.approve(message, actor=actor, role=role)
    except outbox.SendNotPermitted as exc:
        raise BillingError(str(exc), status=409) from exc
    return ClientInvoice.all_objects.get(pk=invoice.pk)


def message_sent(message, *, actor=None) -> None:
    """Called by the Outbox once an invoice's message has actually left,
    whether it was approved here or in the Sending queue."""
    from apps.crm.models import OutboxMessage

    if message.state != OutboxMessage.State.SENT or not message.source_id:
        return
    with transaction.atomic():
        invoice = (ClientInvoice.all_objects.select_for_update()
                   .filter(tenant_id=message.tenant_id, pk=message.source_id).first())
        if invoice is None:
            return
        first = invoice.status == S.READY
        if first:
            invoice.status = S.SENT
            invoice.sent_at = message.sent_at or timezone.now()
            invoice.save(update_fields=["status", "sent_at", "updated_at"])
        audit(invoice, "invoice_sent" if first else "invoice_resent", actor,
              to=message.to_address,
              **({"before": S.READY, "after": S.SENT} if first else {}))


@transaction.atomic
def queue_again(invoice, *, actor, role) -> ClientInvoice:
    """A ready invoice whose message was sent back: into the queue again."""
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != S.READY:
        raise BillingError("Only an invoice that is ready and unsent is queued.", status=409)
    if _waiting(invoice) is None:
        _queue(invoice, actor=actor, role=role)
    return invoice


@transaction.atomic
def back_to_draft(invoice, *, actor) -> ClientInvoice:
    """Reopen a ready invoice. It keeps its number; the waiting message is
    withdrawn, so nothing can be sent from the old wording."""
    from apps.crm.services import outbox

    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != S.READY:
        raise BillingError("Only an invoice that is ready and unsent goes back to "
                           "draft. One that was sent is voided instead.", status=409)
    message = _waiting(invoice)
    if message is not None:
        outbox.reject(message, actor=actor)
    invoice.status = S.DRAFT
    invoice.ready_at = None
    invoice.save(update_fields=["status", "ready_at", "updated_at"])
    audit(invoice, "invoice_reopened", actor, before=S.READY, after=S.DRAFT)
    return invoice


# ------------------------------------------------------- payments and void

def _recount(invoice) -> None:
    paid = (ClientPayment.all_objects.filter(invoice=invoice, removed_at__isnull=True)
            .aggregate(total=Sum("amount_cents"))["total"] or 0)
    invoice.paid_cents = paid
    if paid >= invoice.total_cents:
        invoice.status = S.PAID
    elif paid > 0:
        invoice.status = S.PARTIALLY_PAID
    else:
        invoice.status = S.SENT
    invoice.save(update_fields=["paid_cents", "status", "updated_at"])


@transaction.atomic
def record_payment(invoice, *, actor, amount_cents, paid_on, method=None, reference="",
                   note="") -> ClientPayment:
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status not in ClientInvoice.OPEN:
        raise BillingError(
            {S.PAID: f"Invoice {invoice.number} is already paid in full.",
             S.VOID: "A void invoice takes no payment."}.get(
                invoice.status, "A payment is recorded against an invoice that was sent."),
            status=409)
    amount = money.cents(amount_cents, what="A payment")
    if amount == 0:
        raise BillingError("A payment is more than nothing.")
    if amount > invoice.balance_cents:
        raise BillingError(f"That is more than the {money.dollars(invoice.balance_cents)} "
                           "still owed on it.")
    method = method or ClientPayment.Method.OTHER
    if method not in ClientPayment.Method.values:
        raise BillingError("method is card, ach, check, wire or other.")
    paid_on = _a_date(paid_on, "The date it was paid")
    if paid_on > timezone.localdate():
        raise BillingError("A payment cannot be dated in the future.")
    before = invoice.status
    payment = ClientPayment.all_objects.create(
        tenant_id=invoice.tenant_id, invoice=invoice, amount_cents=amount, paid_on=paid_on,
        method=method, reference=str(reference or "").strip()[:120],
        note=str(note or "").strip(), recorded_by=actor)
    _recount(invoice)
    audit(invoice, "payment_recorded", actor, payment=str(payment.pk), amount_cents=amount,
          paid_on=paid_on.isoformat(), method=method, before=before, after=invoice.status)
    return payment


@transaction.atomic
def remove_payment(payment, *, actor, reason) -> ClientInvoice:
    reason = str(reason or "").strip()
    if not reason:
        raise BillingError("Say why the payment is being removed.")
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=payment.invoice_id)
    payment = ClientPayment.all_objects.select_for_update().get(pk=payment.pk)
    if payment.removed_at is not None:
        raise BillingError("That payment was already removed.", status=409)
    if invoice.status == S.VOID:
        raise BillingError("The invoice is void.", status=409)
    before = invoice.status
    payment.removed_at = timezone.now()
    payment.removed_by = actor
    payment.remove_reason = reason
    payment.save(update_fields=["removed_at", "removed_by", "remove_reason", "updated_at"])
    _recount(invoice)
    audit(invoice, "payment_removed", actor, payment=str(payment.pk),
          amount_cents=payment.amount_cents, reason=reason, before=before,
          after=invoice.status)
    return invoice


@transaction.atomic
def void(invoice, *, actor, reason) -> ClientInvoice:
    from apps.crm.services import outbox

    reason = str(reason or "").strip()
    if not reason:
        raise BillingError("Say why the invoice is being voided.")
    invoice = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == S.VOID:
        raise BillingError(f"Invoice {invoice.number} is already void.", status=409)
    if not invoice.number:
        raise BillingError("A draft with no number is deleted, not voided.", status=409)
    if invoice.paid_cents > 0:
        # Money received is never hidden by a void.
        raise BillingError(
            f"Invoice {invoice.number} has {money.dollars(invoice.paid_cents)} recorded "
            "against it. Remove the payment first if it was recorded in error.",
            status=409)
    message = _waiting(invoice)
    if message is not None:
        outbox.reject(message, actor=actor)
    before = invoice.status
    invoice.status = S.VOID
    invoice.voided_at = timezone.now()
    invoice.void_reason = reason
    invoice.save(update_fields=["status", "voided_at", "void_reason", "updated_at"])
    audit(invoice, "invoice_voided", actor, before=before, after=S.VOID, reason=reason)
    return invoice


# ------------------------------------------------------------------ totals

def totals(queryset, today=None) -> dict:
    """Over exactly the invoices given, so an associate's totals are the
    totals of what they may see. A draft, a ready one and a void one are not
    money owed."""
    today = today or timezone.localdate()
    counted = queryset.filter(status__in=(S.SENT, S.PARTIALLY_PAID, S.PAID))
    sums = counted.aggregate(invoiced=Sum("total_cents"), paid=Sum("paid_cents"))
    late = counted.filter(status__in=ClientInvoice.OPEN, due_date__lt=today).aggregate(
        total=Sum(F("total_cents") - F("paid_cents")))
    invoiced, paid = sums["invoiced"] or 0, sums["paid"] or 0
    return {"invoiced_cents": invoiced, "paid_cents": paid,
            "outstanding_cents": invoiced - paid, "overdue_cents": late["total"] or 0}


# --------------------------------------------------------------- schedules

def _next_month(day: date, day_of_month: int) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))


def _schedule_lines(tenant, lines) -> list[dict]:
    cleaned = _clean_lines(tenant, lines)
    if not cleaned:
        raise BillingError("A schedule needs at least one line.")
    return [{"description": line["description"], "quantity": str(line["quantity"]),
             "unit_price_cents": line["unit_price_cents"]} for line in cleaned]


@transaction.atomic
def save_schedule(tenant, *, actor, schedule=None, client_company=None, contact=None,
                  day_of_month=None, starts_on=None, ends_on=..., lines=None, notes=None,
                  terms=None, is_active=None) -> ClientInvoiceSchedule:
    made = schedule is None
    if made:
        _recipient(tenant, kind=K.RECURRING, company=client_company, contact=contact)
        schedule = ClientInvoiceSchedule(tenant=tenant, client_company=client_company,
                                         contact=contact, created_by=actor,
                                         day_of_month=0, next_on=timezone.localdate())
        if lines is None or day_of_month is None:
            raise BillingError("A schedule needs its lines and a day of the month.")
    elif contact is not None:
        _recipient(tenant, kind=K.RECURRING, company=schedule.client_company,
                   contact=contact)
        schedule.contact = contact
    if day_of_month is not None:
        if isinstance(day_of_month, bool) or not isinstance(day_of_month, int) \
                or not 1 <= day_of_month <= 28:
            raise BillingError("The day of the month is from 1 to 28.")
        schedule.day_of_month = day_of_month
    if made or starts_on is not None or day_of_month is not None:
        # The first draft is written on the next such day, today included.
        start = _a_date(starts_on, "The first date") if starts_on else timezone.localdate()
        first = start.replace(day=schedule.day_of_month)
        schedule.next_on = first if first >= start else _next_month(start,
                                                                   schedule.day_of_month)
    if ends_on is not ...:
        schedule.ends_on = _a_date(ends_on, "The last date") if ends_on else None
    if lines is not None:
        schedule.lines = _schedule_lines(tenant, lines)
    if notes is not None:
        schedule.notes = str(notes).strip()
    if terms is not None:
        schedule.terms = str(terms).strip()
    if is_active is not None:
        schedule.is_active = bool(is_active)
    schedule.save()
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor,
        verb="billing.schedule_created" if made else "billing.schedule_changed",
        target_type="client_invoice_schedule", target_id=schedule.pk,
        payload={"company": str(schedule.client_company_id)})
    return schedule


def run_schedules(tenant, today=None) -> list[ClientInvoice]:
    """One draft for each schedule whose day has come. It numbers nothing and
    sends nothing. A day missed while the worker was down is made up once, not
    once per missed day."""
    today = today or timezone.localdate()
    made = []
    due = ClientInvoiceSchedule.all_objects.filter(tenant=tenant, is_active=True,
                                                   next_on__lte=today)
    for row in due:
        with transaction.atomic():
            schedule = ClientInvoiceSchedule.all_objects.select_for_update().get(pk=row.pk)
            if not schedule.is_active or schedule.next_on > today:
                continue
            company = schedule.client_company
            if company.deleted_at is not None or not company.is_client_company or \
                    (schedule.ends_on and schedule.next_on > schedule.ends_on):
                schedule.is_active = False
                schedule.save(update_fields=["is_active", "updated_at"])
                continue
            # Its own notes and terms where it has them; the practice's
            # defaults where it does not.
            own = {field: value for field, value in (("notes", schedule.notes),
                                                     ("terms", schedule.terms)) if value}
            made.append(create_draft(
                tenant, actor=None, kind=K.RECURRING, client_company=company,
                contact=schedule.contact, schedule=schedule, lines=list(schedule.lines),
                issue_date=today, **own))
            upcoming = schedule.next_on
            while upcoming <= today:
                upcoming = _next_month(upcoming, schedule.day_of_month)
            schedule.next_on = upcoming
            if schedule.ends_on and upcoming > schedule.ends_on:
                schedule.is_active = False
            schedule.save(update_fields=["next_on", "is_active", "updated_at"])
    return made
