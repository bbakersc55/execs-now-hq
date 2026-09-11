"""Step 3 of 3 — seed the two pipelines and the owner's real stages.

Separate from the schema migration, per assumption G4. Idempotent. The stage
labels here are the owner's own, taken from their live CRM; the FF edits them
afterwards and nothing in the app keys on the label — behaviour keys on
`semantic`.
"""

from django.db import migrations

from apps.crm.seed import PIPELINES


def seed(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    Pipeline = apps.get_model("crm", "Pipeline")
    PipelineStage = apps.get_model("crm", "PipelineStage")

    for tenant in Tenant.objects.all():
        for name, kind, position, stages in PIPELINES:
            pipeline, _ = Pipeline.objects.get_or_create(
                tenant=tenant, name=name,
                defaults={"kind": kind, "position": position},
            )
            for code, label, semantic, stage_position in stages:
                PipelineStage.objects.get_or_create(
                    tenant=tenant, pipeline=pipeline, code=code,
                    defaults={"label": label, "semantic": semantic,
                              "position": stage_position},
                )


def unseed(apps, schema_editor):
    """Only removes stages still exactly as seeded, and only empty pipelines —
    a renamed stage or one holding a contact is the FF's, not ours."""
    Pipeline = apps.get_model("crm", "Pipeline")
    PipelineStage = apps.get_model("crm", "PipelineStage")

    for name, kind, position, stages in PIPELINES:
        for code, label, semantic, stage_position in stages:
            PipelineStage.objects.filter(
                pipeline__name=name, code=code, label=label, semantic=semantic,
                positions__isnull=True,
            ).delete()
    Pipeline.objects.filter(
        name__in=[p[0] for p in PIPELINES], stages__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0010_multiple_pipelines")]
    operations = [migrations.RunPython(seed, unseed)]
