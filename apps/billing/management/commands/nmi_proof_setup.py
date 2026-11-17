"""The portal proof's practice (P4 part 2), in its own throwaway database.

    DATABASE_URL=postgres:///execsnowhq_nmi_proof NMI_LIVE_CALLS=true \\
        .venv/bin/python manage.py nmi_proof_setup

**Not product code, and laptop only.** It refuses unless APP_ENVIRONMENT is
local, NMI_ENVIRONMENT is sandbox, real calls are on, and the database's
name ends in `_nmi_proof`, so it can never touch `execsnowhq_local`, the
demo or production. `scripts/nmi_token_proof.py --portal` makes that database
fresh, runs this, and drives the portal.

It makes one practice whose NMI account is connected with the platform's
sandbox keys (tested with NMI as Settings → Billing does), a client company
with a client owner, and one sent invoice: to the company, or with
`--contact` to a contact alone (paid only by its link). It prints, as JSON,
the client owner's one-time sign-in path, the invoice's pay link path (part
3), and its id and number. Nothing is emailed: the invoice is marked sent
without its email.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.billing import gateway as gw


class Command(BaseCommand):
    help = "Make the portal proof's practice, client and invoice (laptop, sandbox only)."

    def add_arguments(self, parser):
        parser.add_argument("--contact", action="store_true",
                            help="Invoice a contact rather than the client company.")
        parser.add_argument("--subscription", action="store_true",
                            help="Part 5: the platform owner's own practice (platform mail "
                                 "is sent from it), the agreement accepted by the proof "
                                 "practice's owner, and a signed-in session for that owner.")
        parser.add_argument("--subscription-charge", action="store_true",
                            help="Part 5, after the owner saved the practice's card: run the "
                                 "subscription job on the card's first charge day, twice.")
        parser.add_argument("--autopay-charge", action="store_true",
                            help="Part 4, after the client saved a card and turned auto-pay "
                                 "on: send a new invoice through the practice's approval, "
                                 "make it due today, and run the auto-pay job.")
        # 2026-11-16: refunds, voids and Test Mode (`nmi_token_proof.py --refunds`).
        parser.add_argument("--another-invoice", action="store_true",
                            help="A second sent invoice to the proof contact; its pay path.")
        parser.add_argument("--read-back", action="store_true",
                            help="Run the morning read-back of the proof practice now.")
        parser.add_argument("--portal-refund", nargs=2, metavar=("INVOICE", "CENTS"),
                            help="Refund an invoice's card payment straight at NMI, as the "
                                 "merchant portal would: the app makes no record of it.")
        parser.add_argument("--refund-facts", action="store_true",
                            help="What the database holds: invoices, payments, refunds, "
                                 "entries in the books, the read-back's flags, cards, mail.")
        # 2026-11-17: automatic billing (`nmi_token_proof.py --automatic`).
        parser.add_argument("--billing-run", metavar="DAY",
                            help="With the clock moved to DAY (YYYY-MM-DD): the 5:00 job "
                                 "that makes and emails automatic invoices, then the 9:00 "
                                 "job that charges them, as the worker runs them.")
        parser.add_argument("--vary", action="store_true",
                            help="With --billing-run: first raise the recurring invoice's "
                                 "price by one cent, because NMI refuses the same card for "
                                 "the same amount within minutes as a duplicate, and the "
                                 "proof runs billing dates seconds apart.")
        parser.add_argument("--billing-facts", action="store_true",
                            help="What the database holds of automatic billing: the "
                                 "recurring invoice, its agreements, invoices, charges, mail.")

    def handle(self, *args, **options):
        database = connection.settings_dict["NAME"] or ""
        if not (settings.APP_ENVIRONMENT == "local" and settings.NMI_ENVIRONMENT == "sandbox"
                and gw.live_calls_allowed() and database.endswith("_nmi_proof")):
            raise CommandError("Only on the laptop, against NMI's sandbox with NMI_LIVE_CALLS "
                               "on, in a database whose name ends in _nmi_proof.")
        if options["autopay_charge"]:
            return self.autopay_charge()
        if options["another_invoice"]:
            return self.another_invoice()
        if options["read_back"]:
            return self.read_back()
        if options["portal_refund"]:
            return self.portal_refund(*options["portal_refund"])
        if options["refund_facts"]:
            return self.refund_facts()
        if options["billing_run"]:
            return self.billing_run(options["billing_run"], vary=options["vary"])
        if options["billing_facts"]:
            return self.billing_facts()
        if options["subscription"]:
            return self.subscription()
        if options["subscription_charge"]:
            return self.subscription_charge()
        from apps.accounts.models import MagicLinkToken, User
        from apps.billing import pay_links, payment_accounts, services
        from apps.billing.models import ClientInvoice
        from apps.crm.models import Company, Contact, ContactEmail
        from apps.platform import provisioning
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Membership, Role, Tenant

        tenant = provisioning.provision_practice(
            legal_name="Proof Practice LLC", display_name="Proof Practice",
            domain="proof-practice.invalid", owner_email="owner@proof-practice.invalid",
            actor=None, pricing_program="interchange_plus")
        Tenant.objects.filter(pk=tenant.pk).update(status=Tenant.Status.ACTIVE)
        owner = Membership.all_objects.get(tenant=tenant, role=Role.FF).user
        with tenant_context(tenant.pk):
            payment_accounts.connect(tenant, environment="sandbox",
                                     private_key=settings.NMI_PRIVATE_API_KEY,
                                     public_key=settings.NMI_PUBLIC_TOKENIZATION_KEY,
                                     actor=owner)
            services.update_settings(tenant, {"pay_instructions": "Pay by card in the portal."})
            company = Company.objects.create(tenant=tenant, name="Proof Client Co",
                                             is_client_company=True, seat_count=3)
            contact = Contact.objects.create(tenant=tenant, first_name="Casey",
                                             last_name="Client", company=company)
            ContactEmail.objects.create(tenant=tenant, contact=contact, is_primary=True,
                                        address="casey@proof-client.invalid")
            client = User.objects.create(email="casey@proof-client.invalid",
                                         full_name="Casey Client")
            Membership.objects.create(tenant=tenant, user=client, role=Role.FCC,
                                      client_company=company)
            # NMI refuses the same card for the same amount twice within
            # minutes: each run's amount differs.
            cents = 2000 + timezone.now().microsecond % 3000
            to_contact = options["contact"]
            if to_contact:
                contact = Contact.objects.create(tenant=tenant, first_name="Robin",
                                                 last_name="Solo")
                ContactEmail.objects.create(tenant=tenant, contact=contact, is_primary=True,
                                            address="robin@proof-contact.invalid")
            invoice = services.create_draft(
                tenant, actor=owner, kind=("contact" if to_contact else "one_off"),
                client_company=None if to_contact else company, contact=contact,
                lines=[{"description": "Operations retainer (proof)", "quantity": "1",
                        "unit_price_cents": cents}])
            services.make_ready(invoice, actor=owner, role=Role.FF)
            ClientInvoice.all_objects.filter(pk=invoice.pk).update(
                status=ClientInvoice.Status.SENT, sent_at=timezone.now())
            invoice.refresh_from_db()
            _, raw = MagicLinkToken.issue(tenant=tenant, user=client, redirect_to="/invoices")
        link = pay_links.url_of(invoice)
        self.stdout.write(json.dumps({
            "sign_in_path": f"/auth/magic/{raw}", "invoice_id": str(invoice.pk),
            "pay_path": link[link.index("/pay/"):] if link else "",
            "number": invoice.number, "amount_cents": invoice.total_cents}))

    def autopay_charge(self):
        from apps.billing import autopay, services
        from apps.billing.models import ClientInvoice
        from apps.crm.models import Company, Contact, OutboxMessage
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Membership, Role, Tenant

        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        owner = Membership.all_objects.get(tenant=tenant, role=Role.FF).user
        with tenant_context(tenant.pk):
            company = Company.objects.get(name="Proof Client Co")
            contact = Contact.objects.get(first_name="Casey")
            cents = 4000 + timezone.now().microsecond % 3000
            invoice = services.create_draft(
                tenant, actor=owner, client_company=company, contact=contact,
                lines=[{"description": "Operations retainer (auto-pay proof)",
                        "quantity": "1", "unit_price_cents": cents}])
            services.make_ready(invoice, actor=owner, role=Role.FF)
            services.send(invoice, actor=owner, role=Role.FF)
            invoice.refresh_from_db()
            email = OutboxMessage.all_objects.filter(
                source_type="client_invoice", source_id=invoice.pk).order_by(
                    "-created_at").first()
            line = next((part for part in email.body_text.split("\n\n")
                         if "will be charged" in part), "")
            ClientInvoice.all_objects.filter(pk=invoice.pk).update(
                due_date=timezone.localdate())
            ran = autopay.run(tenant)
            ran_again = autopay.run(tenant)
        self.stdout.write(json.dumps({
            "invoice_id": str(invoice.pk), "number": invoice.number,
            "invoice_status_after_send": invoice.status, "email_state": email.state,
            "email_says": line, "job": ran, "job_again": ran_again}))

    def subscription(self):
        from django.conf import settings as dj
        from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.backends.db import SessionStore

        from apps.accounts.models import User
        from apps.platform import agreement, provisioning
        from apps.platform.models import AgreementAcceptance
        from apps.tenancy.models import Membership, Role, Tenant

        if not Tenant.objects.filter(legal_name="Proof Platform LLC").exists():
            platform = provisioning.provision_practice(
                legal_name="Proof Platform LLC", display_name="Proof Platform",
                domain="proof-platform.invalid", owner_email="platform@proof-platform.invalid",
                actor=None, pricing_program="interchange_plus")
            Tenant.objects.filter(pk=platform.pk).update(status=Tenant.Status.ACTIVE)
        User.objects.filter(email="platform@proof-platform.invalid").update(
            is_platform_owner=True)
        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        owner = Membership.all_objects.get(tenant=tenant, role=Role.FF).user
        terms = agreement.current()
        AgreementAcceptance.all_objects.get_or_create(
            user=owner, version=terms["version"],
            defaults={"tenant": tenant, "text_sha256": terms["sha256"]})
        session = SessionStore()
        session[SESSION_KEY] = str(owner.pk)
        session[BACKEND_SESSION_KEY] = dj.AUTHENTICATION_BACKENDS[0]
        session[HASH_SESSION_KEY] = owner.get_session_auth_hash()
        session.create()
        self.stdout.write(json.dumps({"cookie": dj.SESSION_COOKIE_NAME,
                                      "session": session.session_key}))

    def billing_run(self, raw, *, vary=False):
        """The two daily jobs on DAY, the clock moved as the demo moves it."""
        from datetime import date

        from apps.billing import recurring
        from apps.billing.models import ClientInvoiceSchedule
        from apps.tenancy.context import tenant_context
        from apps.tenancy.demo.clock import at, moment
        from apps.tenancy.models import Tenant

        day = date.fromisoformat(raw)
        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        if vary:
            for row in ClientInvoiceSchedule.all_objects.filter(tenant=tenant, mode="auto"):
                for lines in (row.lines, row.pending_lines or []):
                    if lines:
                        lines[0]["unit_price_cents"] += 1
                row.save(update_fields=["lines", "pending_lines", "updated_at"])
        with tenant_context(tenant.pk):
            with at(moment(day, 5, 0)):
                made = recurring.make_due(tenant, today=day)
            with at(moment(day, 9, 0)):
                charged = recurring.charge_due(tenant, today=day)
        self.stdout.write(json.dumps({
            "day": raw, "made": [(i.number, str(i.billing_date), i.total_cents, i.status)
                                 for i in made], "charged": charged}))

    def billing_facts(self):
        from apps.billing import recurring
        from apps.billing.models import BillingAgreement, ClientInvoiceSchedule, PaymentAttempt
        from apps.crm.models import OutboxMessage
        from apps.tenancy.models import AuditEvent, Tenant

        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        schedule = ClientInvoiceSchedule.all_objects.get(tenant=tenant, mode="auto")
        from apps.billing.models import ClientInvoice

        invoices = []
        for invoice in ClientInvoice.all_objects.filter(schedule=schedule).order_by(
                "billing_date"):
            mail = OutboxMessage.all_objects.filter(source_type="client_invoice",
                                                    source_id=invoice.pk).first()
            invoices.append({
                "number": invoice.number, "billing_date": str(invoice.billing_date),
                "issue_date": str(invoice.issue_date), "total_cents": invoice.total_cents,
                "status": invoice.status, "paid_cents": invoice.paid_cents,
                "email": mail and {"state": mail.state, "to": mail.to_address,
                                   "says_charged": next((line for line in mail.body_text
                                                         .splitlines() if "will be charged"
                                                         in line), "")},
                "attempts": [(a.status, a.via, a.nmi_transaction_id, a.amount_cents, a.is_test)
                             for a in PaymentAttempt.all_objects.filter(invoice=invoice)],
                "passed_over": [e.payload.get("reason") for e in AuditEvent.all_objects.filter(
                    target_id=invoice.pk, verb="billing.autopay_passed_over")]})
        agreements = [{
            "agreed_by": a.agreed_by.email, "version": a.wording_version,
            "address_kept": bool(a.ip_address), "browser_kept": "Chrome" in a.user_agent,
            "card": a.card.last4 if a.card else "", "wording": a.wording.splitlines()[:4],
            "notice_given": bool(a.notice_given_at), "ends_on": str(a.ends_on or ""),
            "ends_set_by": a.ends_set_by, "ended": bool(a.ended_at)}
            for a in BillingAgreement.all_objects.filter(schedule=schedule).order_by("agreed_at")]
        mail = list(OutboxMessage.all_objects.filter(tenant=tenant).exclude(
            source_type="client_invoice").order_by("created_at").values_list(
                "subject", "to_address", "state"))
        from apps.tenancy.context import tenant_context

        with tenant_context(tenant.pk):
            state = recurring.state_of(schedule)
        self.stdout.write(json.dumps({
            "state": state, "days": schedule.days_of_month,
            "first_billing_on": str(schedule.first_billing_on),
            "lines": schedule.lines, "pending": [schedule.pending_lines,
                                                 str(schedule.pending_from or "")],
            "agreements": agreements, "invoices": invoices, "mail": mail}))

    def subscription_charge(self):
        from apps.billing import subscriptions
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Tenant

        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        with tenant_context(tenant.pk):
            row = subscriptions.subscription_for(tenant)
            # A different amount each run, as the invoices above have: NMI
            # refuses the same card for the same amount again within its
            # duplicate window, which stopped a second run (2026-11-13).
            row.amount_override_cents = 2000 + timezone.now().microsecond % 3000
            row.save(update_fields=["amount_override_cents", "updated_at"])
            day = row.first_charge_on
            before = subscriptions.run(tenant, today=day - timedelta(days=1))
            ran = subscriptions.run(tenant, today=day)
            again = subscriptions.run(tenant, today=day)
        self.stdout.write(json.dumps({"first_charge_on": day.isoformat(),
                                      "day_before": before, "job": ran, "job_again": again}))


    # ------------------------------------------- refunds and Test Mode (11-16)

    def _practice(self):
        from apps.tenancy.models import Membership, Role, Tenant

        tenant = Tenant.objects.get(legal_name="Proof Practice LLC")
        return tenant, Membership.all_objects.get(tenant=tenant, role=Role.FF).user

    def another_invoice(self):
        from apps.billing import pay_links, services
        from apps.billing.models import ClientInvoice
        from apps.crm.models import Contact
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Role

        tenant, owner = self._practice()
        with tenant_context(tenant.pk):
            contact = Contact.objects.get(first_name="Robin")
            cents = 5000 + timezone.now().microsecond % 3000
            invoice = services.create_draft(
                tenant, actor=owner, kind="contact", contact=contact,
                lines=[{"description": "Workshop (proof)", "quantity": "1",
                        "unit_price_cents": cents}])
            services.make_ready(invoice, actor=owner, role=Role.FF)
            ClientInvoice.all_objects.filter(pk=invoice.pk).update(
                status=ClientInvoice.Status.SENT, sent_at=timezone.now())
            invoice.refresh_from_db()
        link = pay_links.url_of(invoice)
        self.stdout.write(json.dumps({
            "invoice_id": str(invoice.pk), "pay_path": link[link.index("/pay/"):],
            "number": invoice.number, "amount_cents": invoice.total_cents}))

    def read_back(self):
        from apps.billing import readback
        from apps.tenancy.context import tenant_context

        tenant, _ = self._practice()
        with tenant_context(tenant.pk):
            counts = readback.read_back(tenant)
        self.stdout.write(json.dumps(counts))

    def portal_refund(self, invoice_id, cents):
        from apps.billing import payment_accounts
        from apps.billing.gateway.nmi import NmiGateway
        from apps.billing.models import ClientPayment

        tenant, _ = self._practice()
        payment = ClientPayment.all_objects.get(invoice_id=invoice_id, removed_at__isnull=True)
        txn = NmiGateway().refund(payment_accounts.practice_account(tenant),
                                  transaction_id=payment.nmi_transaction_id,
                                  amount_cents=int(cents))
        self.stdout.write(json.dumps({"refund_transaction_id": txn.id,
                                      "approved": txn.approved,
                                      "sale_transaction_id": payment.nmi_transaction_id}))

    def refund_facts(self):
        from apps.billing import gateway_mode, payment_accounts
        from apps.billing.gateway.nmi import NmiGateway
        from apps.billing.models import (
            CardRefund, ClientInvoice, ClientPayment, ClientPaymentMethod, NmiEvent,
        )
        from apps.crm.models import OutboxMessage
        from apps.finance.models import FinanceEntry

        tenant, _ = self._practice()
        account = payment_accounts.practice_account(tenant)
        cards = []
        for card in ClientPaymentMethod.all_objects.filter(tenant=tenant):
            # Still in the sandbox's vault? (GET answers 200, or refuses.)
            status, _ = NmiGateway()._send(account, "GET", f"/customers/{card.vault_id}", None,
                                           raise_for_status=False)
            cards.append({"last4": card.last4, "is_test": card.is_test,
                          "removed": card.removed_at is not None,
                          "vault_answers": status})
        self.stdout.write(json.dumps({
            "gateway_mode": gateway_mode.practice_state(tenant),
            "invoices": [{
                "number": i.number, "status": i.status, "total_cents": i.total_cents,
                "paid_cents": i.paid_cents, "test_paid_cents": i.test_paid_cents,
                "payments": [{
                    "amount_cents": p.amount_cents, "nmi_transaction_id": p.nmi_transaction_id,
                    "is_test": p.is_test, "removed": p.removed_at is not None,
                    "remove_reason": p.remove_reason[:60],
                    "books": list(FinanceEntry.all_objects.filter(client_payment=p).values_list(
                        "kind", "direction", "amount_cents", "removed_at"))}
                    for p in ClientPayment.all_objects.filter(invoice=i).order_by("created_at")],
                "refunds": [{
                    "kind": r.kind, "status": r.status, "source": r.source,
                    "amount_cents": r.amount_cents, "nmi_transaction_id": r.nmi_transaction_id,
                    "against": r.against_transaction_id, "is_test": r.is_test,
                    "void_invoice": r.void_invoice, "cleared": r.cleared_at is not None,
                    "problem": r.problem,
                    "books": list(FinanceEntry.all_objects.filter(client_refund=r).values_list(
                        "kind", "direction", "amount_cents", "on_date"))}
                    for r in CardRefund.all_objects.filter(invoice=i).order_by("created_at")]}
                for i in ClientInvoice.all_objects.filter(tenant=tenant).order_by("created_at")],
            "flags": list(NmiEvent.all_objects.filter(tenant=tenant).values_list(
                "kind", "outcome", "amount_cents", "transaction_id")),
            "cards": cards,
            "mail": list(OutboxMessage.all_objects.filter(source_type="card_refund").values_list(
                "producer", "subject")),
            "receipts_saying_test": OutboxMessage.all_objects.filter(
                producer="payment_receipt", body_text__contains="test mode").count(),
        }, default=str))
