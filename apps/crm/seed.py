"""Seeding a NEW tenant. The data migration covers tenants that already exist;
this covers every tenant created afterwards."""

from __future__ import annotations

from apps.crm.migrations import __name__ as _  # noqa: F401

PIPELINE_STAGES = [
    ("contact", "Contact", 0, False),
    ("lead", "Lead", 1, False),
    ("qualified_lead", "Qualified lead", 2, False),
    ("client", "Client", 3, False),
    ("lost", "Lost", 4, True),
    ("dormant", "Dormant", 5, True),
]

CONTACT_TYPES = [
    ("prospect", "Prospect", 0),
    ("client", "Client", 1),
    ("referral_partner", "Referral partner", 2),
    ("vendor", "Vendor", 3),
    ("coworker", "Coworker", 4),
]


def seed_tenant(tenant):
    """Idempotent. Safe to call on an already-seeded tenant."""
    from apps.crm.models import ContactType, PipelineStage

    for code, label, position, is_terminal in PIPELINE_STAGES:
        PipelineStage.all_objects.get_or_create(
            tenant=tenant, code=code,
            defaults={"label": label, "position": position, "is_terminal": is_terminal},
        )
    for code, label, position in CONTACT_TYPES:
        ContactType.all_objects.get_or_create(
            tenant=tenant, code=code,
            defaults={"label": label, "position": position},
        )
