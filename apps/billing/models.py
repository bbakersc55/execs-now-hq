"""Client invoicing without a processor (`docs/p4a_client_invoicing.md`).

A practice writes an invoice, sends it through the Sending queue, and records
by hand that it was paid. P4 adds payment by card: in the portal, and by the
signed pay link printed on the PDF and in the email.

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

from apps.tenancy.models import TenantScopedModel, UUIDModel


class InvoiceSettings(TenantScopedModel):
    """One row per practice: its numbering and what a new invoice starts with."""

    prefix = models.CharField(max_length=12, default="INV-", db_default="INV-")
    #: The next number to give. Raised by the practice owner, never lowered.
    next_value = models.PositiveIntegerField(default=1, db_default=1)
    #: The practice's payment terms: 0 is due on receipt, 15 is net 15. What
    #: a new invoice and a schedule that names none of its own start from.
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
    #: Its own payment terms, in days. Empty: the practice's, as they stand
    #: on the day each invoice is written.
    terms_days = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Its own "how to pay" and its own covering email. Each empty: the
    #: practice's, as it stands on the day each invoice is written.
    pay_instructions = models.TextField(blank=True, default="", db_default="")
    email_subject = models.CharField(max_length=200, blank=True, default="", db_default="")
    email_body = models.TextField(blank=True, default="", db_default="")
    is_active = models.BooleanField(default=True, db_default=True)
    #: Where its invoices' payments are entered in the books, when the
    #: practice owner chose something other than what recurring invoices go
    #: to by default (owner, 2026-10-10). Copied onto each draft it writes.
    income_category = models.ForeignKey("finance.FinanceCategory", null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="+")
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
    #: Where its payments are entered in the books, when that is not the
    #: default for its kind: Retainers for a recurring invoice, Project fees
    #: for any other. The practice owner's to choose; it is not on the invoice.
    income_category = models.ForeignKey("finance.FinanceCategory", null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="+")
    number = models.CharField(max_length=40, null=True, blank=True)
    issue_date = models.DateField()
    #: Payment terms, in days: the due date is the issue date and these, and
    #: "overdue" counts from it. Empty on an invoice written before terms
    #: were kept (2026-10-14); `services.terms_days_of` reads it from the dates.
    terms_days = models.PositiveSmallIntegerField(null=True, blank=True)
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
    #: What the PDF prints as the pay link. Never written: it is filled in
    #: memory from `pay_links.url_of` when the PDF is made, because the link
    #: carries its token and only the token's hash is stored (P4 part 3).
    pay_url = models.URLField(max_length=500, blank=True, default="", db_default="")
    #: The signed pay link's token, hashed (`apps/billing/pay_links.py`), and
    #: when it was issued. Empty: no link (the practice's card account was not
    #: ready, or the invoice was voided).
    pay_token_hash = models.CharField(max_length=64, blank=True, default="", db_default="")
    pay_link_issued_at = models.DateTimeField(null=True, blank=True)
    #: Set when its email was queued to a company with auto-pay on (P4 part
    #: 4): the email said the card would be charged on the due date, and the
    #: auto-pay job charges it then, while this consent stands.
    autopay_consent = models.ForeignKey("AutopayConsent", null=True, blank=True,
                                        on_delete=models.PROTECT, related_name="invoices")
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
            models.UniqueConstraint(fields=["pay_token_hash"], condition=~Q(pay_token_hash=""),
                                    name="client_invoice_pay_token_once"),
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
    #: P4 part 2: the NMI transaction a card payment in the portal made. Empty
    #: for one recorded by hand. One transaction is never recorded twice.
    nmi_transaction_id = models.CharField(max_length=40, blank=True, default="",
                                          db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "client_payment"
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="client_payment_amount_positive"),
            models.UniqueConstraint(fields=["tenant", "nmi_transaction_id"],
                                    condition=~Q(nmi_transaction_id=""),
                                    name="client_payment_nmi_transaction_once"),
        ]


class PaymentAccount(TenantScopedModel):
    """The practice's own NMI merchant account (P4 §1.2, §3.3): which of NMI's
    environments its keys are for, and the last connection test. The two keys
    themselves are `tenant_secret` rows (`nmi_private_key`, `nmi_public_key`),
    encrypted and never shown again. The practice owner's alone (12.1)."""

    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox (test)"
        LIVE = "live", "Live"

    environment = models.CharField(max_length=8, choices=Environment.choices,
                                   default=Environment.SANDBOX, db_default=Environment.SANDBOX)
    #: The last test of the keys now stored: when, whether NMI accepted the
    #: private key, and what it said. Cleared whenever a key or the
    #: environment changes, so a pass never outlives what it tested.
    checked_at = models.DateTimeField(null=True, blank=True)
    check_ok = models.BooleanField(null=True, blank=True)
    check_detail = models.TextField(blank=True, default="", db_default="")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "payment_account"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="payment_account_one_per_practice"),
        ]


class PaymentAttempt(TenantScopedModel):
    """One card payment of an invoice, from the portal (P4 part 2) or the pay
    link (part 3), written
    before NMI is asked and finished from its answer.

    **One in flight per invoice:** while an attempt is pending (NMI is being
    asked) or unknown (NMI's answer was lost), no other can start, so a
    double click or a second tab never charges twice. An unknown attempt is
    settled by `card_payments.resolve_unknown`, which looks the sale up by our
    reference; nothing is ever retried by itself. The decline text NMI gave is
    kept. No card data: a brand and the last four, from NMI's answer.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Asking NMI"
        APPROVED = "approved", "Paid"
        DECLINED = "declined", "Declined"
        #: NMI's answer was lost; being looked up.
        UNKNOWN = "unknown", "Checking with NMI"
        #: Never reached NMI, or NMI has no sale for it.
        FAILED = "failed", "Not charged"

    class Via(models.TextChoices):
        PORTAL = "portal", "The portal"
        #: The signed link in the email and on the PDF: no one signed in.
        LINK = "link", "The pay link"
        #: The card on file, on the due date, under the company's consent.
        AUTOPAY = "autopay", "Auto-pay"

    IN_FLIGHT = (Status.PENDING, Status.UNKNOWN)

    invoice = models.ForeignKey(ClientInvoice, on_delete=models.PROTECT,
                                related_name="payment_attempts")
    via = models.CharField(max_length=8, choices=Via.choices, default=Via.PORTAL,
                           db_default=Via.PORTAL)
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    amount_cents = models.BigIntegerField()
    #: Which of NMI's environments the practice's account was in.
    environment = models.CharField(max_length=8, default="sandbox")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING,
                              db_default=Status.PENDING)
    nmi_transaction_id = models.CharField(max_length=40, blank=True, default="",
                                          db_default="")
    #: NMI's own, kept as it said them: "100", "200" … or "E_DUPLICATE".
    response_code = models.CharField(max_length=40, blank=True, default="", db_default="")
    response_text = models.TextField(blank=True, default="", db_default="")
    card_type = models.CharField(max_length=20, blank=True, default="", db_default="")
    last4 = models.CharField(max_length=4, blank=True, default="", db_default="")
    payment = models.OneToOneField(ClientPayment, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="attempt")
    #: Auto-pay's: the card on file it charged.
    payment_method = models.ForeignKey("ClientPaymentMethod", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="attempts")
    #: A charge NMI approved that could not be recorded on the invoice (it was
    #: voided or paid in the meantime). The practice owner is told.
    problem = models.TextField(blank=True, default="", db_default="")
    finished_at = models.DateTimeField(null=True, blank=True)
    looked_up_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "payment_attempt"
        constraints = [
            models.UniqueConstraint(fields=["invoice"],
                                    condition=Q(status__in=["pending", "unknown"]),
                                    name="payment_attempt_one_in_flight"),
            models.CheckConstraint(condition=Q(amount_cents__gt=0),
                                   name="payment_attempt_amount_positive"),
        ]
        indexes = [models.Index(fields=["status", "created_at"])]


class ClientPaymentMethod(TenantScopedModel):
    """A client company's card on file (P4 part 4): a record in the
    practice's own NMI Customer Vault. The app keeps the vault id, the brand,
    the last four and the expiry; never the card. Saved only by a signed-in
    client owner in the portal. Removed, it is deleted from the vault and the
    row kept, marked removed. One card on file per company at a time."""

    client_company = models.ForeignKey("crm.Company", on_delete=models.PROTECT,
                                       related_name="payment_methods")
    #: The record's id in the practice's Customer Vault.
    vault_id = models.CharField(max_length=40)
    #: Which of NMI's environments that vault is in.
    environment = models.CharField(max_length=8, default="sandbox")
    brand = models.CharField(max_length=20, blank=True, default="", db_default="")
    last4 = models.CharField(max_length=4)
    exp_month = models.PositiveSmallIntegerField()
    exp_year = models.PositiveSmallIntegerField()
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                 related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    #: When the client was told the card is about to expire. Once per card.
    expiry_notice_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "client_payment_method"
        constraints = [
            models.UniqueConstraint(fields=["client_company"], condition=Q(removed_at__isnull=True),
                                    name="client_payment_method_one_on_file"),
            models.CheckConstraint(condition=Q(exp_month__gte=1, exp_month__lte=12),
                                   name="client_payment_method_exp_month"),
        ]


class AutopayConsent(TenantScopedModel):
    """A client owner's agreement that the card on file is charged on each
    invoice's due date (P4 part 4, §10 choice 3). Kept as given: who, when,
    the exact wording they saw and its version, their address and browser.
    Revocable at any time, and the revocation is kept too. One standing
    consent per company."""

    client_company = models.ForeignKey("crm.Company", on_delete=models.PROTECT,
                                       related_name="autopay_consents")
    consented_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="+")
    consented_at = models.DateTimeField()
    wording = models.TextField()
    wording_version = models.CharField(max_length=20)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True, default="", db_default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    #: "Turned off", "Card removed", …
    revoke_reason = models.CharField(max_length=120, blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "autopay_consent"
        constraints = [
            models.UniqueConstraint(fields=["client_company"], condition=Q(revoked_at__isnull=True),
                                    name="autopay_consent_one_standing"),
        ]


# ------------------------------------------------- practice subscriptions
# P4 part 5, `docs/p4_billing.md` §2 and §5.1: a practice pays the platform,
# on the platform's own NMI account (the NMI_* keys in the environment).
# Nothing here is a client's: a subscription invoice is told apart from a
# client payment by its own reference ("sub-<id>"), never by the account.

class BillingPlan(UUIDModel):
    """The platform's. "Beta at cost" is the one plan in Beta (D9)."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    interval = models.CharField(max_length=8, default="month", db_default="month")
    price_cents = models.BigIntegerField()
    #: A price not decided yet: never shown to a practice.
    is_placeholder = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = "billing_plan"


class BillingAddon(UUIDModel):
    """The platform's: a monthly price for one module, added to the base.
    None in Beta; the table is here for released pricing (D9)."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    price_cents = models.BigIntegerField()
    is_placeholder = models.BooleanField(default=True, db_default=True)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = "billing_addon"


class PracticeSubscription(TenantScopedModel):
    """A practice's subscription: its plan, its amount, and its card in the
    **platform's** Customer Vault. One per practice."""

    class Status(models.TextChoices):
        #: The platform owner's own practice: never billed.
        NOT_BILLED = "not_billed", "Not billed"
        NEEDS_CARD = "needs_card", "Needs a card"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    plan = models.ForeignKey(BillingPlan, on_delete=models.PROTECT, related_name="+")
    #: The platform owner's figure for this practice; null is the plan's price.
    amount_override_cents = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="usd", db_default="usd")
    #: Where receipts go: the practice owner's address unless changed.
    billing_email = models.EmailField(blank=True, default="", db_default="")
    nmi_vault_id = models.CharField(max_length=40, blank=True, default="", db_default="")
    #: Which of NMI's environments the platform account's vault was in.
    card_environment = models.CharField(max_length=8, blank=True, default="", db_default="")
    card_brand = models.CharField(max_length=20, blank=True, default="", db_default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="", db_default="")
    #: "MM/YY", as shown.
    card_expires = models.CharField(max_length=5, blank=True, default="", db_default="")
    card_added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    card_added_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.NEEDS_CARD, db_default=Status.NEEDS_CARD)
    #: The first 1st on or after the card went on file: no part-month (§2.2).
    first_charge_on = models.DateField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_subscription"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="practice_subscription_one_each"),
            models.CheckConstraint(
                condition=Q(amount_override_cents__isnull=True)
                | Q(amount_override_cents__gte=0),
                name="practice_subscription_override_not_negative"),
        ]


class PracticeSubscriptionAddon(TenantScopedModel):
    subscription = models.ForeignKey(PracticeSubscription, on_delete=models.CASCADE,
                                     related_name="addons")
    addon = models.ForeignKey(BillingAddon, on_delete=models.PROTECT, related_name="+")
    added_at = models.DateTimeField()
    #: The next period's start (D4): the rest of the month it was added in is
    #: included.
    charged_from = models.DateField()
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_subscription_addon"


class PracticeInvoice(TenantScopedModel):
    """The platform's invoice to a practice for one month, made by the app
    for every charge, with its PDF (D8). Never a client invoice."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"
        REFUNDED = "refunded", "Refunded"

    number = models.CharField(max_length=60)
    period_start = models.DateField()
    period_end = models.DateField()
    subtotal_cents = models.BigIntegerField(default=0, db_default=0)
    #: Zero in Beta (D5); the line is there.
    tax_cents = models.BigIntegerField(default=0, db_default=0)
    total_cents = models.BigIntegerField(default=0, db_default=0)
    amount_paid_cents = models.BigIntegerField(default=0, db_default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN,
                              db_default=Status.OPEN)
    issued_at = models.DateTimeField()
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    nmi_transaction_id = models.CharField(max_length=40, blank=True, default="", db_default="")
    pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                            on_delete=models.PROTECT, related_name="+")
    #: A charge under way, or one whose answer was lost ("unknown"): no other
    #: is made until it is settled by the lookup.
    charge_state = models.CharField(max_length=10, blank=True, default="", db_default="")
    charge_started_at = models.DateTimeField(null=True, blank=True)
    charge_tries = models.PositiveSmallIntegerField(default=0, db_default=0)
    #: What NMI said to the last charge that was not approved.
    last_charge_text = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_invoice"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "period_start"],
                                    name="practice_invoice_one_per_period"),
            models.UniqueConstraint(fields=["number"], name="practice_invoice_number_unique"),
            models.CheckConstraint(condition=Q(amount_paid_cents__lte=F("total_cents")),
                                   name="practice_invoice_not_overpaid"),
            models.CheckConstraint(
                condition=Q(subtotal_cents__gte=0, tax_cents__gte=0, total_cents__gte=0,
                            amount_paid_cents__gte=0),
                name="practice_invoice_amounts_not_negative"),
        ]

    @property
    def reference(self) -> str:
        """Our reference at NMI: what tells it from any client payment."""
        return f"sub-{self.pk}"

    @property
    def balance_cents(self) -> int:
        return self.total_cents - self.amount_paid_cents


class PracticeInvoiceLine(TenantScopedModel):
    invoice = models.ForeignKey(PracticeInvoice, on_delete=models.CASCADE,
                                related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=200)
    amount_cents = models.BigIntegerField()
    #: Null for the base plan.
    addon = models.ForeignKey(BillingAddon, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_invoice_line"
        ordering = ["position"]


class NmiEvent(TenantScopedModel):
    """What the daily read-back (P4 §4) found in a practice's NMI account that
    this app did not do itself: a refund, a void or a chargeback made in NMI's
    portal (recorded against the payment it matches), or anything it could
    not match (flagged for the practice owner). Once per action at NMI: the
    `event_id` is the transaction, the action and its time. Nothing here
    charges, refunds or changes an invoice's money; the practice owner acts
    on what it shows. No card data.

    The spec had this as a platform table; it is the practice's, because only
    practice accounts are read back so far (the platform account's
    subscription charges are told apart by their "sub-" reference and left
    out of a practice's read-back)."""

    class Kind(models.TextChoices):
        REFUND = "refund", "Refund"
        VOID = "void", "Void"
        CHARGEBACK = "chargeback", "Chargeback"
        SALE = "sale", "Charge"
        OTHER = "other", "Other"

    class Outcome(models.TextChoices):
        MATCHED = "matched", "Recorded against its payment"
        UNMATCHED = "unmatched", "Couldn't be matched"

    event_id = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    #: NMI's own word for it ("refund", "chargeback", "void", "sale", …).
    action_type = models.CharField(max_length=40)
    transaction_id = models.CharField(max_length=40)
    original_transaction_id = models.CharField(max_length=40, blank=True, default="",
                                               db_default="")
    reference = models.CharField(max_length=60, blank=True, default="", db_default="")
    amount_cents = models.BigIntegerField()
    happened_at = models.DateTimeField()
    payment = models.ForeignKey(ClientPayment, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="nmi_events")
    invoice = models.ForeignKey(ClientInvoice, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="nmi_events")
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    note = models.TextField(blank=True, default="", db_default="")
    #: The practice owner has looked at it ("Mark as seen").
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "nmi_event"
        ordering = ["-happened_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "event_id"], name="nmi_event_once"),
            models.CheckConstraint(condition=Q(amount_cents__gte=0),
                                   name="nmi_event_amount_not_negative"),
        ]
