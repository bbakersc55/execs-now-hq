"""Give the diagnostic questions their private note field.

AC-4.9 names five things the PDF excludes, and one of them is "a §4 internal
observation" — distinct from the Snapshot's fractional-only note, and with its
own inclusion toggle (`diagnostic_observations`). The data model's walkthrough
has two diagnostic answers carrying one. The seed document spells the note field
out only under §1, which is where this was missed.

Touches only questions still carrying the seeded wording: an FF who has since
reworded one owns it, and this leaves it alone.
"""

from django.db import migrations

from apps.strategy.seed import SECTIONS, TEMPLATE_NAME


def _diagnostic_questions():
    for code, _title, _budget, questions in SECTIONS:
        if code == "diagnostic":
            return questions
    return []


def enable(apps, schema_editor):
    StrategyQuestion = apps.get_model("strategy", "StrategyQuestion")
    for question in _diagnostic_questions():
        StrategyQuestion.objects.filter(
            template__name=TEMPLATE_NAME, key=question["key"],
            prompt=question["prompt"], has_fractional_note=False,
        ).update(has_fractional_note=True)


def disable(apps, schema_editor):
    StrategyQuestion = apps.get_model("strategy", "StrategyQuestion")
    for question in _diagnostic_questions():
        StrategyQuestion.objects.filter(
            template__name=TEMPLATE_NAME, key=question["key"],
            prompt=question["prompt"],
        ).update(has_fractional_note=False)


class Migration(migrations.Migration):

    dependencies = [("strategy", "0003_strategysession_drafted_areas")]

    operations = [migrations.RunPython(enable, disable)]
