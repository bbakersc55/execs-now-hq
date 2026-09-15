"""Executives Now's branding is data on its own tenant row, not a code default.

White-label (owner ruling, 2026-09-15): a practice that has set nothing gets its
own name over neutral greys, so a V1 tenant can never inherit the product
owner's look. That moved Executives Now's name and palette out of the field
defaults, which is where Beta's one row had been getting them — so this puts
them on the row.

Guarded by `count() == 1`: at this point in history Beta has exactly one tenant
and it is Executives Now. If a database somehow holds more, the migration does
nothing rather than brand somebody else's practice.
"""

from django.db import migrations

BETA_HEADER = "#0A3A65"
BETA_ACCENT = "#F58220"
NEUTRAL_HEADER = "#1F2933"
NEUTRAL_ACCENT = "#52606D"


def stamp(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    tenants = list(Tenant.objects.all())
    for tenant in tenants:
        fields = []
        if not tenant.email_display_name:
            tenant.email_display_name = tenant.name
            fields.append("email_display_name")
        if len(tenants) == 1:
            if tenant.email_header_color == NEUTRAL_HEADER:
                tenant.email_header_color = BETA_HEADER
                fields.append("email_header_color")
            if tenant.email_accent_color == NEUTRAL_ACCENT:
                tenant.email_accent_color = BETA_ACCENT
                fields.append("email_accent_color")
        if fields:
            tenant.save(update_fields=fields)


def unstamp(apps, schema_editor):
    """Reversible: the row keeps its name, the palette returns to neutral."""
    Tenant = apps.get_model("tenancy", "Tenant")
    Tenant.objects.filter(email_header_color=BETA_HEADER).update(
        email_header_color=NEUTRAL_HEADER)
    Tenant.objects.filter(email_accent_color=BETA_ACCENT).update(
        email_accent_color=NEUTRAL_ACCENT)


class Migration(migrations.Migration):

    dependencies = [("tenancy", "0004_tenant_email_branding")]

    operations = [migrations.RunPython(stamp, unstamp)]
