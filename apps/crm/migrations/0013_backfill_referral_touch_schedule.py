"""Backfill the touch cadence for referral partners imported before the fix.

Found in Check 4: all 40 imported referral partners arrived with the type set
but no `referral_cadence` and no `referral_next_touch_at`, because the importer
wrote `contact_type_link` rows directly and never went through
`referral.add_type`. The scheduled job filters on `referral_next_touch_at`, so
it would have drafted for none of them — silently, forever.

Sets the tenant default cadence and a next touch one cadence period out. It
does NOT set `referral_onboarded_at` and does NOT queue any onboarding email:
these partners were met long before the import, and a backfill is a statement
about history (the same rule the import already follows for stage automations).
"""

from django.db import migrations
from django.utils import timezone

CADENCE_DAYS = {"monthly": 30, "bimonthly": 60, "quarterly": 90}
DEFAULT_CADENCE = "monthly"


def backfill(apps, schema_editor):
    Contact = apps.get_model("crm", "Contact")
    ContactType = apps.get_model("crm", "ContactType")

    now = timezone.now()
    for contact_type in ContactType.objects.filter(code="referral_partner"):
        partners = Contact.objects.filter(
            tenant_id=contact_type.tenant_id, deleted_at__isnull=True,
            type_links__contact_type=contact_type,
        ).distinct()
        for contact in partners:
            fields = []
            if not contact.referral_cadence:
                contact.referral_cadence = DEFAULT_CADENCE
                fields.append("referral_cadence")
            if contact.referral_next_touch_at is None:
                days = CADENCE_DAYS.get(contact.referral_cadence or DEFAULT_CADENCE, 30)
                contact.referral_next_touch_at = now + timezone.timedelta(days=days)
                fields.append("referral_next_touch_at")
            if fields:
                contact.save(update_fields=fields)


def unbackfill(apps, schema_editor):
    """Not reversed: the dates are indistinguishable from ones the FF set by
    hand afterwards, and clearing those would put the partners back out of the
    scheduler's sight."""


class Migration(migrations.Migration):
    dependencies = [("crm", "0012_dev_send_allowlist")]
    operations = [migrations.RunPython(backfill, unbackfill)]
