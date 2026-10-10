"""An estimated tax payment is a mark on an owner draw, and nothing else
(owner, 2026-10-10). The "Estimated tax payments" sub-category of Owner draw
goes.

Any entry sitting on it moves to its parent. Where it is the owner's money
going out and its description says federal or state (one of them, not both),
it gets that mark. Every other one is left unmarked and listed: printed as
the migration runs, and kept in the practice's audit trail
(`finance.estimated_tax_category_removed`). Rules and import lines that named
the sub-category name its parent. The sub-category is then deleted, or
archived where a combine or split on record still names it.

No amount, date, account or total changes. Going back does not put the
sub-category or the old categories back.
"""

import re

from django.db import migrations

NAME = "estimated tax payments"
WORD = {"federal": re.compile(r"\bfederal\b", re.I), "state": re.compile(r"\bstate\b", re.I)}


def mark_for(entry) -> str:
    """`federal` or `state` where the description says exactly one of them and
    the entry can carry the mark; otherwise "" (it is then listed)."""
    if entry.kind != "owner" or entry.direction != "out":
        return ""
    said = [which for which, word in WORD.items() if word.search(entry.description or "")]
    return said[0] if len(said) == 1 else ""


def remove_the_sub_category(apps, schema_editor):
    Category = apps.get_model("finance", "FinanceCategory")
    Entry = apps.get_model("finance", "FinanceEntry")
    Rule = apps.get_model("finance", "FinanceRule")
    ImportRow = apps.get_model("finance", "FinanceImportRow")
    Change = apps.get_model("finance", "FinanceCategoryChange")
    Audit = apps.get_model("tenancy", "AuditEvent")

    subs = Category._base_manager.filter(name__iexact=NAME, type="owner",
                                         parent__isnull=False).select_related("parent")
    for sub in subs:
        parent = sub.parent
        marked, unmarked = {"federal": 0, "state": 0}, []
        for entry in Entry._base_manager.filter(category=sub).order_by("on_date"):
            entry.category = parent
            if not entry.estimated_tax:
                entry.estimated_tax = mark_for(entry)
            if entry.estimated_tax:
                marked[entry.estimated_tax] += 1
            elif entry.removed_at is None:
                unmarked.append({"id": str(entry.pk), "on_date": entry.on_date.isoformat(),
                                 "amount_cents": entry.amount_cents,
                                 "direction": entry.direction,
                                 "description": entry.description})
            entry.save(update_fields=["category", "estimated_tax", "updated_at"])
        Rule._base_manager.filter(category=sub).update(category=parent)
        ImportRow._base_manager.filter(category=sub).update(category=parent)
        kept = Change._base_manager.filter(from_category=sub).exists() \
            or Change._base_manager.filter(to_category=sub).exists()
        Audit._base_manager.create(
            tenant_id=sub.tenant_id, verb="finance.estimated_tax_category_removed",
            target_type="finance_category", target_id=sub.pk,
            payload={"moved_to": parent.name, "marked": marked, "unmarked": unmarked,
                     "category": "archived" if kept else "deleted"})
        if kept:
            from django.utils import timezone

            sub.archived_at = sub.archived_at or timezone.now()
            sub.save(update_fields=["archived_at", "updated_at"])
        else:
            sub.delete()
        print(f"\n  practice {sub.tenant_id}: {marked['federal']} marked federal, "
              f"{marked['state']} marked state, {len(unmarked)} left unmarked"
              + (":" if unmarked else "."))
        for row in unmarked:
            print(f"    {row['on_date']}  {row['amount_cents'] / 100:.2f} {row['direction']}"
                  f"  {row['description'] or '(no description)'}")


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0005_worksheet_export"),
        ("tenancy", "0013_getting_started_dismissal"),
    ]

    operations = [
        migrations.RunPython(remove_the_sub_category, migrations.RunPython.noop),
    ]
