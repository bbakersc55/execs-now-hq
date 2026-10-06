"""Getting started (P2, §5): the practice owner's checklist, computed from the
practice's own data on every request. Nothing is stored, so an item can never
claim something that is not true, and an item undone (a disconnected Gmail)
shows as open again."""

from __future__ import annotations


def items(tenant) -> list[dict]:
    from apps.crm.models import Company, Contact, GmailConnection, ImportBatch
    from apps.strategy.models import StrategyTemplate
    from apps.tenancy.models import Membership, TenantSecret

    t = tenant.pk
    return [
        {"key": "branding", "label": "Set your branding", "to": "/settings/branding",
         "done": tenant.branding_updated_at is not None},
        {"key": "gmail", "label": "Choose your practice address and connect Gmail",
         "to": "/settings/email",
         "done": GmailConnection.all_objects.filter(
             tenant_id=t, send_as_verified_at__isnull=False).exists()},
        {"key": "anthropic", "label": "Add your Anthropic key", "to": "/ai-usage",
         "done": TenantSecret.all_objects.filter(tenant_id=t,
                                                 kind="anthropic_api_key").exists()},
        # D5: a committed import, or any contact at all.
        {"key": "contacts", "label": "Import your contacts", "to": "/import",
         "done": ImportBatch.all_objects.filter(tenant_id=t, status="committed").exists()
         or Contact.all_objects.filter(tenant_id=t).exists()},
        {"key": "staff", "label": "Invite your staff", "to": "/staff",
         "done": Membership.all_objects.filter(tenant_id=t, role__in=("CF", "VA"),
                                               revoked_at__isnull=True).exists()},
        {"key": "client", "label": "Add your first client", "to": "/companies",
         "done": Company.all_objects.filter(tenant_id=t, is_client_company=True).exists()},
        {"key": "template", "label": "Build your first strategy template",
         "to": "/strategy/template",
         "done": StrategyTemplate.all_objects.filter(tenant_id=t).exists()},
    ]
