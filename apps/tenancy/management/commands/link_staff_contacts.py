"""Attach existing staff memberships to their contact rows (assumption F1).

Staff invited before `invite_member` did this have no `membership.contact`, so
everything that needs to know which contact *is* this person — meeting
ingestion's practice rule above all (FR-5.9e) — has to fall back to matching by
address and then by name. The owner's own membership was the case in point.

Dry-run by default. It links; it **never overwrites** a membership that already
points somewhere, and it never modifies a contact it did not create.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.tenancy import services
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, Membership, Role, Tenant

STAFF_ROLES = (Role.FF, Role.CF, Role.VA)


class Command(BaseCommand):
    help = "Link staff memberships to their contact rows, creating one where needed."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Tenant slug. Default: every tenant.")
        parser.add_argument("--apply", action="store_true",
                            help="Write the links. Without it, nothing is saved.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get("tenant"):
            tenants = tenants.filter(slug=options["tenant"])
        for tenant in tenants:
            with tenant_context(tenant.id):
                self.one(tenant, apply=options["apply"])

    def one(self, tenant, *, apply: bool):
        unlinked = list(Membership.objects.filter(
            role__in=STAFF_ROLES, revoked_at__isnull=True, contact__isnull=True
        ).select_related("user"))
        self.stdout.write(f"\n{tenant.slug}: {len(unlinked)} staff membership(s) "
                          "without a contact")
        if not unlinked:
            return

        with transaction.atomic():
            for membership in unlinked:
                user = membership.user
                contact, made = services.contact_for_staff(
                    tenant, email=user.email, full_name=user.full_name)
                verb = "would create" if made else "would link"
                self.stdout.write(
                    f"  {membership.role} {user.email} -> {verb} "
                    f"{contact.first_name} {contact.last_name} ({contact.pk})")
                if not apply:
                    continue
                membership.contact = contact
                membership.save(update_fields=["contact", "updated_at"])
                AuditEvent.all_objects.create(
                    tenant=tenant, actor=None, verb="member.contact_linked",
                    target_type="membership", target_id=membership.pk,
                    payload={"contact": str(contact.pk), "created": made,
                             "email": user.email})
            if not apply:
                # Including any contact the resolution had to create to answer
                # the question. A dry run writes nothing at all.
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    "  Dry run. Nothing written. Re-run with --apply."))
                return
        self.stdout.write(self.style.SUCCESS(f"  Linked {len(unlinked)}."))
