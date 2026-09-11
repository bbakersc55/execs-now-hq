"""Step 1 of 3 — empty the old single-pipeline tables before reshaping them.

The owner's real CRM runs two pipelines (sales, and a nurture pipeline for
referral partners) and the app had collapsed them into one fixed six-stage
funnel. That funnel was a guess; it is removed rather than migrated.

**This is destructive and deliberately so.** It is safe only because it runs
before any real contact exists: at the time it was written the database held 0
contacts, 0 stage changes and 0 stage automations. The guard below re-checks
that at run time rather than trusting the comment — on a database with real
positions it refuses instead of silently deleting history.
"""

from django.db import migrations


def purge(apps, schema_editor):
    Contact = apps.get_model("crm", "Contact")
    PipelineStage = apps.get_model("crm", "PipelineStage")
    StageAutomation = apps.get_model("crm", "StageAutomation")
    StageChange = apps.get_model("crm", "StageChange")

    changes = StageChange.objects.count()
    if changes:
        raise RuntimeError(
            f"{changes} stage_change rows exist. This migration drops the old "
            "single-pipeline seed and would destroy that history. Migrate the "
            "data deliberately instead of running this."
        )

    StageAutomation.objects.all().delete()
    Contact.objects.update(stage=None)
    PipelineStage.objects.all().delete()


def unpurge(apps, schema_editor):
    """Nothing to restore: the rows this removed were seed data, and 0011
    reseeds their replacement."""


class Migration(migrations.Migration):
    dependencies = [("crm", "0008_importbatch_mapping_importbatch_value_mapping_and_more")]
    operations = [migrations.RunPython(purge, unpurge)]
