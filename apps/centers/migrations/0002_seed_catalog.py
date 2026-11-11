"""The platform's catalog of Command Centers (P8), and each one's $50 add-on
on the billing side. Additive: rows only, written once, never rewritten."""

from django.db import migrations


def seed(apps, schema_editor):
    from apps.centers.catalog import CENTERS, PRICE_CENTS, addon_code

    CommandCenter = apps.get_model("centers", "CommandCenter")
    BillingAddon = apps.get_model("billing", "BillingAddon")
    for position, (code, name, short, discipline, status, description) in enumerate(CENTERS):
        CommandCenter.objects.get_or_create(code=code, defaults={
            "name": name, "short_name": short, "discipline": discipline,
            "price_cents": PRICE_CENTS, "status": status, "description": description,
            "position": position})
        BillingAddon.objects.get_or_create(code=addon_code(code), defaults={
            "name": name, "price_cents": PRICE_CENTS, "is_placeholder": False})


class Migration(migrations.Migration):
    dependencies = [
        ("centers", "0001_initial"),
        ("billing", "0012_card_payment_hold"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
