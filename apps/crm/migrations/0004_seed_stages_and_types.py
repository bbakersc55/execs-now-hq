"""Seed data migration (data model §11 note 2).

Separate from the schema migration, per assumption G4. Idempotent, and
reversible without deleting a tenant's customisations: the reverse only removes
rows that are still exactly as seeded.
"""

from django.db import migrations

# FR-1.6 + assumption F2. `lost` and `dormant` are the non-linear states
# without which every prospect who says no stays in "qualified lead" forever.
PIPELINE_STAGES = [
    ("contact", "Contact", 0, False),
    ("lead", "Lead", 1, False),
    ("qualified_lead", "Qualified lead", 2, False),
    ("client", "Client", 3, False),
    ("lost", "Lost", 4, True),
    ("dormant", "Dormant", 5, True),
]

# FR-1.2. Multi-type, because a referral partner is frequently also a client.
CONTACT_TYPES = [
    ("prospect", "Prospect", 0),
    ("client", "Client", 1),
    ("referral_partner", "Referral partner", 2),
    ("vendor", "Vendor", 3),
    ("coworker", "Coworker", 4),
]


def seed(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    PipelineStage = apps.get_model("crm", "PipelineStage")
    ContactType = apps.get_model("crm", "ContactType")

    for tenant in Tenant.objects.all():
        for code, label, position, is_terminal in PIPELINE_STAGES:
            PipelineStage.objects.get_or_create(
                tenant=tenant, code=code,
                defaults={"label": label, "position": position, "is_terminal": is_terminal},
            )
        for code, label, position in CONTACT_TYPES:
            ContactType.objects.get_or_create(
                tenant=tenant, code=code,
                defaults={"label": label, "position": position},
            )


def unseed(apps, schema_editor):
    PipelineStage = apps.get_model("crm", "PipelineStage")
    ContactType = apps.get_model("crm", "ContactType")
    # Only remove rows still bearing their seeded labels — a tenant that has
    # renamed a stage keeps it.
    for code, label, _pos, _terminal in PIPELINE_STAGES:
        PipelineStage.objects.filter(code=code, label=label).delete()
    for code, label, _pos in CONTACT_TYPES:
        ContactType.objects.filter(code=code, label=label).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0003_contact_company_primary_contact_contacttype_and_more"),
        ("tenancy", "0002_membership_contact"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
