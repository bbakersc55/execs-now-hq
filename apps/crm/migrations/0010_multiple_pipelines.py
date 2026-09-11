"""Step 2 of 3 — the schema. Runs on tables 0009 has already emptied.

`pipeline` is added non-nullable to pipeline_stage, stage_change and
stage_automation without a default, which is only safe because 0009 deleted
every row in those tables first.
"""

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0001_initial"),
        ("crm", "0009_purge_single_pipeline_seed"),
    ]

    operations = [
        migrations.CreateModel(
            name="Pipeline",
            fields=[
                ("id", models.UUIDField(default=__import__("uuid").uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("kind", models.CharField(choices=[("sales", "Sales"),
                                                   ("referral", "Referral partners"),
                                                   ("custom", "Custom")],
                                          default="custom", max_length=16)),
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="%(app_label)s_%(class)s_set", to="tenancy.tenant")),
            ],
            options={"db_table": "pipeline", "ordering": ["position", "name"],
                     "abstract": False, "base_manager_name": "all_objects"},
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="pipelinestage", name="pipeline_stage_code_unique",
        ),
        migrations.RemoveField(model_name="pipelinestage", name="is_terminal"),
        migrations.AddField(
            model_name="pipelinestage", name="pipeline",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stages", to="crm.pipeline"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="pipelinestage", name="semantic",
            field=models.CharField(
                choices=[("entry", "Entry"), ("working", "Working"),
                         ("qualified", "Qualified"), ("won", "Won"), ("lost", "Lost"),
                         ("parked", "Parked"), ("none", "No semantic")],
                default="none", max_length=12),
        ),
        migrations.AddConstraint(
            model_name="pipeline",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"), name="pipeline_name_unique"),
        ),
        migrations.AddConstraint(
            model_name="pipelinestage",
            constraint=models.UniqueConstraint(
                fields=("tenant", "pipeline", "code"), name="pipeline_stage_code_unique"),
        ),
        migrations.AddConstraint(
            model_name="pipelinestage",
            constraint=models.UniqueConstraint(
                condition=models.Q(("semantic", "won")), fields=("tenant", "pipeline"),
                name="pipeline_stage_one_won"),
        ),
        migrations.RemoveIndex(model_name="contact", name="contact_tenant__a547c5_idx"),
        migrations.RemoveField(model_name="contact", name="stage"),
        migrations.AddField(
            model_name="stagechange", name="pipeline",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stage_changes", to="crm.pipeline"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="stageautomation", name="pipeline",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="automations", to="crm.pipeline"),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="ContactPipelinePosition",
            fields=[
                ("id", models.UUIDField(default=__import__("uuid").uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("entered_at", models.DateTimeField(auto_now_add=True)),
                ("contact", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="pipeline_positions", to="crm.contact")),
                ("pipeline", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="positions", to="crm.pipeline")),
                ("stage", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="positions", to="crm.pipelinestage")),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="%(app_label)s_%(class)s_set", to="tenancy.tenant")),
            ],
            options={"db_table": "contact_pipeline_position", "abstract": False,
                     "base_manager_name": "all_objects"},
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name="contactpipelineposition",
            index=models.Index(fields=["tenant", "pipeline", "stage"],
                               name="contact_pip_tenant__46f1aa_idx"),
        ),
        migrations.AddConstraint(
            model_name="contactpipelineposition",
            constraint=models.UniqueConstraint(
                fields=("tenant", "contact", "pipeline"),
                name="contact_pipeline_position_unique"),
        ),
    ]
