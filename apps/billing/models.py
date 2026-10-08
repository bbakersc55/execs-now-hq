"""Client invoicing without a processor (`docs/p4a_client_invoicing.md`).

A practice writes an invoice, sends it through the Sending queue, and records
by hand that it was paid. No payment is taken in the app: `pay_url` stays
empty until P4's NMI work fills it.

Three things these models hold to:

- **Money is integer cents.** Never a float, anywhere.
- **A number, once given, is never cleared and never reused.** It is given
  when the invoice is made ready; from then the invoice is voided, not deleted.
- **An invoice is the document as sent.** What is printed (who it bills, the
  lines, the wording) is copied onto it, so nothing edited later changes it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.tenancy.models import TenantScopedModel


class InvoiceSettings(TenantScopedModel):
    """One row per practice: its numbering and what a new invoice starts with."""

    prefix = models.CharField(max_length=12, default="INV-", db_default="INV-")
    #: The next number to give. Raised by the practice owner, never lowered.
    next_value = models.PositiveIntegerField(default=1, db_default=1)
    terms_days = models.PositiveSmallIntegerField(default=15, db_default=15)
    default_notes = models.TextField(blank=True, default="", db_default="")
    default_terms = models.TextField(blank=True, default="", db_default="")
    #: "How to pay", printed on every invoice. Required before the first one
    #: can be made ready: with no processor it is how a client knows.
    pay_instructions = models.TextField(blank=True, default="", db_default="")
    email_subject = models.CharField(max_length=200, blank=True, default="", db_default="")
    email_body = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "invoice_settings"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="invoice_settings_one_per_practice"),
        ]


class ClientInvoiceSchedule(TenantScopedModel):
    """Writes a draft each month for one client company. It numbers nothing
    and sends nothing: a person makes the draft ready."""

    client_company = models.ForeignKey("crm.Company", on_delete=models.PROTECT,
                                       related_name="invoice_schedules")
    contact = models.ForeignKey("crm.Contact", on_delete=models.PROTECT, related_name="+")
    day_of_month = models.PositiveSmallIntegerField()
    next_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    #: [{description, quantity, unit_price_cents}, ...] — the template.
    lines = models.JSONField(default=list)
    notes = models.TextField(blank=True, default="", db_default="")
    terms = models.TextField(blank=True, default="", db_default="")
    is_active = models.BooleanField(default=True, db_default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "client_invoice_schedule"
        constraints = [
            models.CheckConstraint(condition=Q(day_of_month__gte=1, day_of_month__lte=28),
                                   name="invoice_schedule_day_1_to_28"),
        ]


class ClientInvoice(TenantScopedModel):
    class Kind(models.TextChoices):
        ONE_OFF = "one_off", "One-off"
        RECURRING = "recurring", "Recurring"
        #: To any one contact, client or not. Email only; in no portal.
        CONTACT = "contact", "To a contact"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        #: Numbered, its PDF stored, waiting for the send to be approved.
        READY = "ready", "Ready to send"
        SENT = "sent", "Sent"
        PARTIALLY_PAID = "partially_paid", "Partly paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    #: Owed on: what "outstanding" and "overdue" are worked out over.
    OPEN = (Status.SENT, Status.PARTIALLY_PAID)
    #: What a client user may see: what they were sent.
    SEEN_BY_CLIENT = (Status.SENT, Status.PARTIALLY_PAID, Status.PAID, Status.VOID)

    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.ONE_OFF)
    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="invoices")
    #: Who it is addressed and emailed to.
    contact = models.ForeignKey("crm.Contact", on_delete=models.PROTECT,
                                related_name="invoices")
    schedule = models.ForeignKey(ClientInvoiceSchedule, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="invoices")
    number = models.CharField(max_length=40, null=True, blank=True)
    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT,
                              db_default=Status.DRAFT)
    #: As printed: {name, company, email, address}. Copied when made ready.
    bill_to = models.JSONField(default=dict)
    subtotal_cents = models.BigIntegerField(default=0, db_default=0)
    tax_cents = models.BigIntegerField(default=0, db_default=0)
    total_cents = models.BigIntegerField(default=0, db_default=0)
    paid_cents = models.BigIntegerField(default=0, db_default=0)
    currency = models.CharField(max_length=3, default="usd", db_default="usd")
    notes = models.TextField(blank=True, default="", db_default="")
    terms = models.TextField(blank=True, default="", db_default="")
    pay_instructions = models.TextField(blank=True, default="", db_default="")
    email_to = models.EmailField(blank=True, default="", db_default="")
    email_subject = models.CharField(max_length=200, blank=True, default="", db_default="")
    email_body = models.TextField(blank=True, default="", db_default="")
    #: Empty until P4's NMI phase. Nothing prints or shows for it while empty.
    pay_url = models.URLField(max_length=500, blank=True, default="", db_default="")
    pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                            on_delete=models.PROTECT, related_name="+")
    outbox_message = models.ForeignKey("crm.OutboxMessage", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    ready_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "client_invoice"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"],
                                    name="client_invoice_number_unique_per_practice"),
            # A contact invoice has no client company, and only it has none.
            models.CheckConstraint(
                condition=(Q(kind="contact", client_company__isnull=True)
                           | (~Q(kind="contact") & Q(client_company__isnull=False))),
                name="client_invoice_company_unless_contact"),
            # Every status but draft has a number. (A reopened draft keeps its
            # own, which this allows: it only forbids the reverse.)
            models.CheckConstraint(
                condition=Q(status="draft") | Q(number__isnull=False),
                name="client_invoice_numbered_once_ready"),
            models.CheckConstraint(
                condition=Q(subtotal_cents__gte=0, tax_cents__gte=0, total_cents__gte=0,
                            paid_cents__gte=0),
                name="client_invoice_amounts_not_negative"),
            models.CheckConstraint(condition=Q(paid_cents__lte=F("total_cents")),
                                   name="client_invoice_not_overpaid"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "due_date"]),
            models.Index(fields=["tenant", "client_company", "-issue_date"]),
        ]

    @property
    def balance_cents(self) -> int:
        return self.total_cents - self.paid_cents


class ClientInvoiceLine(TenantScopedModel):
    invoice = models.ForeignKey(ClientInvoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price_cents = models.BigIntegerField(default=0)
    amount_cents = models.BigIntegerField(default=0)
    project = models.ForeignKey("work.Project", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    goal = models.ForeignKey("work.Goal", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "client_invoice_line"
        ordering = ["position", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gte=0, unit_price_cents__gte=0,
                                               quantity__gte=0),
                                   name="client_invoice_line_not_negative"),
        ]


class ClientPayment(TenantScopedModel):
    """Money received against an invoice, recorded by hand. One recorded in
    error is marked removed, with a reason, and stops counting; it is kept."""

    class Method(models.TextChoices):
        CARD = "card", "Card"
        BANK_TRANSFER = "ach", "Bank transfer"
        CHECK = "check", "Check"
        WIRE = "wire", "Wire"
        OTHER = "other", "Other"

    invoice = models.ForeignKey(ClientInvoice, on_delete=models.PROTECT,
                                related_name="payments")
    amount_cents = models.BigIntegerField()
    paid_on = models.DateField()
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.OTHER)
    reference = models.CharField(max_length=120, blank=True, default="", db_default="")
    note = models.TextField(blank=True, default="", db_default="")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    remove_reason = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "client_payment"
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="client_payment_amount_positive"),
        ]
