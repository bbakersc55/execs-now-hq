"""Switch owner agreements on or off for one client company (owner,
2026-11-23), as intake forms are switched: SkyRun Park City's alone, no switch
in the app.

    python manage.py owner_agreements <company-id>          says whether it's on
    python manage.py owner_agreements <company-id> on
    python manage.py owner_agreements <company-id> off

On needs intake forms on for the company (an agreement starts the owner's
intake). It makes the company's settings the first time, with the sender on
"ENHQ's own sender (testing)". Off hides everything again: the menu item, the
screens, the notification choice, the owner's links and pages. Signed
agreements and their PDFs are kept. Either way it is in the audit log.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Switch owner agreements on or off for one client company."

    def add_arguments(self, parser):
        parser.add_argument("company_id")
        parser.add_argument("state", nargs="?", choices=["on", "off"])

    def handle(self, *args, company_id, state, **options):
        from apps.crm.models import Company
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import AuditEvent

        from ... import services

        try:
            pk = uuid.UUID(str(company_id))
        except ValueError:
            raise CommandError(f"{company_id!r} isn't a company id.") from None
        company = (Company.all_objects.select_related("tenant")
                   .filter(pk=pk, deleted_at__isnull=True).first())
        if company is None:
            raise CommandError("No company has that id.")
        where = f"{company.name} (practice: {company.tenant.name})"
        program = services.program_for(company)
        on_now = bool(program and program.enabled)
        if state is None:
            self.stdout.write(f"Owner agreements are {'on' if on_now else 'off'} for {where}.")
            return
        enabled = state == "on"
        if enabled and not company.intake_forms_enabled:
            raise CommandError(f"{where} doesn't have intake forms on: an agreement starts the "
                               "owner's intake. Run `manage.py intake_forms <id> on` first.")
        if on_now == enabled:
            self.stdout.write(f"Owner agreements were already {state} for {where}. Nothing "
                              "changed.")
            return
        with tenant_context(company.tenant_id):
            program = services.program_for(company, create=True)
            program.enabled = enabled
            program.save(update_fields=["enabled", "updated_at"])
            AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=None,
                                          verb="agreements.switched", target_type="company",
                                          target_id=company.pk,
                                          payload={"enabled": enabled,
                                                   "by": "manage.py owner_agreements"})
        self.stdout.write(f"Owner agreements are now {state} for {where}.")
