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
        parser.add_argument("--autopay-charge", action="store_true",
                            help="Part 4, after the client saved a card and turned auto-pay "
                                 "on: send a new invoice through the practice's approval, "
                                 "make it due today, and run the auto-pay job.")

    def handle(self, *args, **options):
        database = connection.settings_dict["NAME"] or ""
        if not (settings.APP_ENVIRONMENT == "local" and settings.NMI_ENVIRONMENT == "sandbox"
                and gw.live_calls_allowed() and database.endswith("_nmi_proof")):
            raise CommandError("Only on the laptop, against NMI's sandbox with NMI_LIVE_CALLS "
                               "on, in a database whose name ends in _nmi_proof.")
        if options["autopay_charge"]:
            return self.autopay_charge()
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
