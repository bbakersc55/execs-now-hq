"""The SOP's eleven sections and its training material (2026-11-14). Additive:
new columns with database defaults, one new table, and a unique number per
company. The one write: each existing SOP gets its number (OPS-01 …), from
its category, in the order the company's SOPs were made; nothing else is
touched."""

import re

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.conf import settings
from django.db import migrations, models


PREFIXES = {"operations": "OPS", "sales": "SAL", "safety": "SAF", "shipping": "SHP",
            "receiving": "RCV", "quality": "QA", "production": "PRD", "maintenance": "MNT",
            "finance": "FIN", "accounting": "ACC", "hiring": "HR", "people": "HR",
            "human resources": "HR", "marketing": "MKT", "purchasing": "PUR",
            "customer service": "CS", "it": "IT", "admin": "ADM", "administration": "ADM"}


def _prefix(category):
    words = " ".join(str(category or "").lower().split())
    if not words:
        return "SOP"
    if words in PREFIXES:
        return PREFIXES[words]
    return (re.sub(r"[^a-z]", "", words)[:3] or "SOP").upper()


def number_existing(apps, schema_editor):
    Sop = apps.get_model("sops", "Sop")
    counts = {}
    for sop in Sop.all_objects.filter(number="").order_by("company_id", "created_at", "pk"):
        prefix = _prefix(sop.category)
        key = (sop.company_id, prefix)
        counts[key] = counts.get(key, 0) + 1
        sop.number = f"{prefix}-{counts[key]:02d}"
        sop.save(update_fields=["number"])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0060_company_sprint_team_tasks'),
        ('sops', '0001_sop_studio'),
        ('tenancy', '0025_sop_studio'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SopTrainingAsset',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('kind', models.CharField(choices=[('quiz', 'Quiz'), ('flashcards', 'Flashcards'), ('slides', 'Slide deck'), ('video', 'Video'), ('audio', 'Audio'), ('other', 'Other')], max_length=12)),
                ('title', models.CharField(max_length=200)),
                ('url', models.CharField(blank=True, db_default='', default='', max_length=1000)),
            ],
            options={
                'db_table': 'sop_training_asset',
                'ordering': ['created_at'],
                'abstract': False,
                'base_manager_name': 'all_objects',
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddField(
            model_name='sop',
            name='definitions',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='sop',
            name='effective_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sop',
            name='metrics',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='sop',
            name='number',
            field=models.CharField(blank=True, db_default='', default='', max_length=20),
        ),
        migrations.AddField(
            model_name='sop',
            name='number_by_hand',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name='sop',
            name='related',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='sop',
            name='review_months',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sop',
            name='training',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.RunPython(number_existing, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='sop',
            constraint=models.UniqueConstraint(condition=models.Q(('number', ''), _negated=True), fields=('company', 'number'), name='sop_number_once_in_company'),
        ),
        migrations.AddField(
            model_name='soptrainingasset',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='soptrainingasset',
            name='file',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenancy.storedfile'),
        ),
        migrations.AddField(
            model_name='soptrainingasset',
            name='sop',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='training_assets', to='sops.sop'),
        ),
        migrations.AddField(
            model_name='soptrainingasset',
            name='tenant',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='%(app_label)s_%(class)s_set', to='tenancy.tenant'),
        ),
        migrations.AddConstraint(
            model_name='soptrainingasset',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('file__isnull', False), ('url', '')), models.Q(('file__isnull', True), models.Q(('url', ''), _negated=True)), _connector='OR'), name='sop_training_asset_file_or_link'),
        ),
    ]
