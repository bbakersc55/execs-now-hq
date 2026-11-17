"""The People Command Center becomes available (2026-11-17): its security
foundation is built (docs/p9_people_hris.md). One row of the platform's
catalog: its status and description. Reversed, it is "coming" again."""

from django.db import migrations

DESCRIPTION = (
    "For a fractional CHRO: People pages per company, HR permissions by person, two-factor "
    "sign-in for HR access, and an access log of every view, change and export. The "
    "employee records come next.")


def available(apps, schema_editor):
    CommandCenter = apps.get_model("centers", "CommandCenter")
    CommandCenter.objects.filter(code="people").update(status="available",
                                                       description=DESCRIPTION)


def coming(apps, schema_editor):
    CommandCenter = apps.get_model("centers", "CommandCenter")
    CommandCenter.objects.filter(code="people").update(status="coming",
                                                       description="For a fractional CHRO. Next.")


class Migration(migrations.Migration):
    dependencies = [("centers", "0004_sop_studio_choices")]
    operations = [migrations.RunPython(available, coming)]
