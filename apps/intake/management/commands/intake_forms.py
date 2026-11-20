"""Switch intake forms on or off for one client company (owner, 2026-11-20).

    python manage.py intake_forms <company-id>          says whether it's on
    python manage.py intake_forms <company-id> on
    python manage.py intake_forms <company-id> off

Intake forms are SkyRun Park City's alone: not a feature offered to other
clients or practices. So there is no switch in the app, for any practice
owner; it is switched here, by the owner, in the Railway shell. The company's
id is the last part of its page's address (/companies/<id>).

On needs a client company with a Track connection (intake forms write to
Track), and makes the company's form the first time. Off hides everything
again: the company card, the menu item, the notification choice, and the
owner's links and form page. Either way it is recorded in the audit log.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Switch intake forms on or off for one client company."

    def add_arguments(self, parser):
        parser.add_argument("company_id")
        parser.add_argument("state", nargs="?", choices=["on", "off"])

    def handle(self, *args, company_id, state, **options):
        from apps.crm.models import Company
        from apps.scorecard.models import TrackConnection
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
        if state is None:
            self.stdout.write(f"Intake forms are {'on' if company.intake_forms_enabled else 'off'}"
                              f" for {where}.")
            return
        if not company.is_client_company:
            raise CommandError(f"{where} isn't a client company.")
        enabled = state == "on"
        if enabled and not TrackConnection.all_objects.filter(company=company).exists():
            raise CommandError(f"{where} has no Track connection: intake forms write to Track. "
                               "Connect it on the company's page first.")
        if company.intake_forms_enabled == enabled:
            self.stdout.write(f"Intake forms were already {state} for {where}. Nothing changed.")
            return
        with tenant_context(company.tenant_id):
            company.intake_forms_enabled = enabled
            company.save(update_fields=["intake_forms_enabled"])
            if enabled:
                services.form_for(company)
            AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=None,
                                          verb="intake.switched", target_type="company",
                                          target_id=company.pk,
                                          payload={"enabled": enabled,
                                                   "by": "manage.py intake_forms"})
        self.stdout.write(f"Intake forms are now {state} for {where}.")
