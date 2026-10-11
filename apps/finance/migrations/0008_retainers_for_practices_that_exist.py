"""Recurring invoices post to "Retainers" from release on, without the owner
touching the settings (owner, 2026-10-11).

0007 pointed each kind of invoice at the practice's own category of that
name. A practice whose chart was made before the chart had two levels has no
"Retainers" at all, so its recurring invoices would have gone on posting to
the general category. For each practice whose books exist and whose recurring
invoices still go nowhere of their own, this adds a "Retainers" sub-category
under the category its paid invoices go to, and points recurring invoices at
it.

It is the one thing added to an existing practice's chart without that
practice asking in the app, and the owner asked for it by name. Nothing is
renamed, moved or removed, and **no entry moves**: only payments recorded
from now on are affected. What it did is printed as it runs and kept in the
practice's audit trail (`finance.retainers_category_added`).
"""

from django.db import migrations
from django.db.models import Max

NAME = "Retainers"


def add_retainers(apps, schema_editor):
    Settings = apps.get_model("finance", "FinanceSettings")
    Category = apps.get_model("finance", "FinanceCategory")
    Audit = apps.get_model("tenancy", "AuditEvent")

    for row in Settings._base_manager.filter(recurring_income_category__isnull=True):
        general = row.invoice_income_category
        if general is None or general.type != "income" or general.archived_at is not None:
            print(f"\n  practice {row.tenant_id}: paid invoices go to no live income "
                  "category, so nothing was added.")
            continue
        mine = Category._base_manager.filter(tenant_id=row.tenant_id)
        found = mine.filter(type="income", name__iexact=NAME,
                            archived_at__isnull=True).first()
        made = found is None
        if made:
            # Under the category paid invoices go to; beside it where that is
            # itself a sub-category, since there are two levels and no more.
            parent = general if general.parent_id is None else general.parent
            last = mine.filter(type="income", parent=parent).aggregate(
                last=Max("position"))["last"]
            found = Category._base_manager.create(
                tenant_id=row.tenant_id, name=NAME, type="income", parent=parent,
                position=(last + 1) if last is not None else 0)
        row.recurring_income_category = found
        row.save(update_fields=["recurring_income_category", "updated_at"])
        under = Category._base_manager.get(pk=found.parent_id).name if found.parent_id else ""
        Audit._base_manager.create(
            tenant_id=row.tenant_id, verb="finance.retainers_category_added",
            target_type="finance_category", target_id=found.pk,
            payload={"created": made, "under": under,
                     "recurring_invoices_go_to": found.name})
        print(f"\n  practice {row.tenant_id}: recurring invoices now go to “{found.name}”"
              + (f", under “{under}”" if under else "")
              + (" (added)." if made else " (it was already in the chart)."))


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0007_invoice_income_by_kind"),
        ("tenancy", "0013_getting_started_dismissal"),
    ]

    operations = [
        migrations.RunPython(add_retainers, migrations.RunPython.noop),
    ]
