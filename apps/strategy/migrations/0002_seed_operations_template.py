"""Seed the Operations template, verbatim from `docs/strategy_session_seed.md`.

Separate from the schema migration, per assumption G4, and idempotent: it
creates what is missing and never rewrites a question the FF has since edited.

Nine sections, 47 questions — 13 of them on the pre-call form, which is the
count the build plan's manual check 2 asks about.
"""

from django.db import migrations

from apps.strategy.seed import SECTIONS, TEMPLATE_NAME, seed_tenant


def seed(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    for tenant in Tenant.objects.all():
        seed_tenant(tenant, apps=apps)


def unseed(apps, schema_editor):
    """Removes only what is still exactly as seeded. An edited prompt, a used
    template, or a section holding a question we did not write is the FF's."""
    StrategyTemplate = apps.get_model("strategy", "StrategyTemplate")
    StrategySection = apps.get_model("strategy", "StrategySection")
    StrategyQuestion = apps.get_model("strategy", "StrategyQuestion")

    for code, _title, _budget, questions in SECTIONS:
        for question in questions:
            StrategyQuestion.objects.filter(
                template__name=TEMPLATE_NAME, key=question["key"],
                prompt=question["prompt"],
            ).delete()
        StrategySection.objects.filter(
            template__name=TEMPLATE_NAME, code=code, questions__isnull=True,
        ).delete()
    StrategyTemplate.objects.filter(
        name=TEMPLATE_NAME, sections__isnull=True, sessions__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [("strategy", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
