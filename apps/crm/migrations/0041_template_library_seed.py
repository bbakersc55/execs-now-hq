"""Seed each practice's template library with the app's own wording, and move
partners on the old fixed "AI-drafted" touch to "My template", which now
holds the same words (owner, 2026-10-20). Adds rows and rewrites one
column's value; nothing is deleted. `manage.py seed_email_templates
--dry-run` shows what it does on a database before it runs."""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.crm import template_seed

    Tenant = apps.get_model("tenancy", "Tenant")
    for tenant in Tenant.objects.all():
        template_seed.seed_tenant(tenant, apps=apps)
    template_seed.touch_modes(apps=apps)


def backwards(apps, schema_editor):
    """The seeded rows go with 0040's tables and columns; the touch mode
    returns to the old default name."""
    Contact = apps.get_model("crm", "Contact")
    Contact.objects.filter(referral_touch_mode="template",
                           referral_template__isnull=True).update(referral_touch_mode="ai")
    apps.get_model("crm", "EmailTemplateUse").objects.all().delete()
    apps.get_model("crm", "EmailTemplate").objects.exclude(original="").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0040_template_library"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
