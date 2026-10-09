"""The chart of categories, and changing its shape (P6 M1, §5).

Two levels: a category may have sub-categories, and a sub-category has none.
An entry may sit on either. **Combine** folds one category into another;
**split** moves some of a category's entries to a new or another one;
**"Add the starting chart"** adds what a practice does not have and never
touches what it does.

Combine and split move entries in closed months too. They change no total,
balance or net: only which of two categories a figure is under. Each is
recorded (`finance_category_change`) with how many entries it moved and
between which dates, so a closed month that reads differently from the export
that was sent has an answer.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max, Min, Q
from django.utils import timezone

from apps.finance.models import (
    FinanceCategory, FinanceCategoryChange, FinanceEntry, FinanceImportRow, FinanceRule,
)
from apps.finance.services import (
    CLIENT_FEES, SALES_TAX, FinanceError, T, _clean_name, audit, settings_for,
)

#: The chart a practice starts with (§5.4): **a placeholder** until the
#: owner's CPA's list replaces it. Each row is a category and its
#: sub-categories. Names are unique across the whole chart.
STARTING_CHART = (
    (T.INCOME, (
        ("Client fees", ("Retainers", "Project fees", "Workshops and speaking")),
        ("Referral fees received", ()),
        ("Reimbursed expenses", ()),
        ("Interest income", ()),
        ("Other income", ()),
    )),
    (T.EXPENSE, (
        ("Contractors and associates", ("Associates", "Assistants", "Other contractors")),
        ("Payroll", ("Wages", "Payroll taxes", "Benefits", "Payroll service fees")),
        ("Software and subscriptions", ("Software", "AI and API usage")),
        ("Marketing and advertising", ("Advertising", "Website", "Events and sponsorships")),
        ("Travel", ("Airfare", "Lodging", "Ground transport")),
        ("Meals", ()),
        ("Vehicle", ("Mileage and fuel", "Parking and tolls")),
        ("Professional services", ("Accounting", "Legal", "Coaching and consulting")),
        ("Insurance", ("Business liability", "Health")),
        ("Office", ("Supplies", "Equipment", "Postage and printing")),
        ("Rent and coworking", ()),
        ("Phone and internet", ()),
        ("Education and training", ()),
        ("Dues and memberships", ()),
        ("Bank and merchant fees", ()),
        ("Referral fees paid", ()),
        ("Taxes and licenses", ()),
        ("Interest paid", ()),
        ("Charitable giving", ()),
        ("Other expenses", ()),
    )),
    (T.OWNER, (
        ("Owner contribution", ()),
        ("Owner draw", ("Draws", "Estimated tax payments")),
    )),
    (T.HELD, (
        ("Sales tax collected", ()),
    )),
)
SYSTEM_CODES = {"Client fees": CLIENT_FEES, "Sales tax collected": SALES_TAX}
#: Paid to contractors: each entry wants a person named for the 1099 report.
CONTRACTOR = ("Contractors and associates",)

NOTE = ("Ask your CPA what they want to see, then add, remove or combine. These are "
        "common names, not a recommendation.")


def create_starting_chart(tenant) -> None:
    """The whole chart, for a practice that has no categories at all."""
    for kind, rows in STARTING_CHART:
        for position, (name, subs) in enumerate(rows):
            parent = FinanceCategory.all_objects.create(
                tenant=tenant, name=name, type=kind, position=position,
                system_code=SYSTEM_CODES.get(name, ""), is_contractor=name in CONTRACTOR)
            for sub_position, sub in enumerate(subs):
                FinanceCategory.all_objects.create(
                    tenant=tenant, name=sub, type=kind, position=sub_position,
                    parent=parent)


# ----------------------------------------------------------------- the tree

def live_children(category):
    return FinanceCategory.all_objects.filter(parent=category, archived_at__isnull=True)


def set_parent(category, parent) -> None:
    """Make `category` a sub-category of `parent`, or top-level when `parent`
    is None. Checks only; the caller saves."""
    if parent is None:
        category.parent = None
        return
    if parent.tenant_id != category.tenant_id:
        raise FinanceError("That category is not in this practice.", status=404)
    if category.system_code:
        raise FinanceError(f"“{category.name}” is one the books rely on, and stays "
                           "where it is.", status=409)
    if parent.pk == category.pk:
        raise FinanceError("A category cannot be its own sub-category.")
    if parent.archived_at is not None:
        raise FinanceError(f"“{parent.name}” is archived.")
    if parent.parent_id is not None:
        raise FinanceError(f"“{parent.name}” is itself a sub-category, and there are "
                           "two levels, not three.")
    if category.pk and live_children(category).exists():
        raise FinanceError(f"“{category.name}” has sub-categories of its own, and there "
                           "are two levels, not three. Move or combine them first.")
    if category.pk and parent.type != category.type:
        raise FinanceError(f"“{parent.name}” is {parent.get_type_display().lower()} and "
                           f"“{category.name}” is {category.get_type_display().lower()}. "
                           "A sub-category has its parent's type.")
    category.parent = parent
    category.type = parent.type


@transaction.atomic
def delete_category(category, *, actor) -> None:
    """Remove a category nothing has ever used. One with entries is archived
    instead, so what was entered stays readable."""
    if category.system_code:
        raise FinanceError(f"“{category.name}” is one the books rely on, and stays.",
                           status=409)
    if FinanceEntry.all_objects.filter(category=category).exists():
        raise FinanceError(f"“{category.name}” has entries, so it is archived, not "
                           "removed. Combine it into another to move them.", status=409)
    if FinanceCategory.all_objects.filter(parent=category).exists():
        raise FinanceError(f"“{category.name}” has sub-categories. Move, combine or "
                           "remove them first.", status=409)
    rules = FinanceRule.all_objects.filter(category=category).count()
    if rules:
        raise FinanceError(f"{rules} import rule{'s' if rules != 1 else ''} put lines in "
                           f"“{category.name}”. Change or remove them first.", status=409)
    if settings_for(category.tenant).invoice_income_category_id == category.pk:
        raise FinanceError(f"Paid invoices go to “{category.name}”. Choose another "
                           "category for them first.", status=409)
    audit(category.tenant, "category_removed", actor, category, name=category.name,
          type=category.type)
    category.delete()


# ------------------------------------------------------------------ combine

def _span(entries) -> dict:
    """How many of these entries would move, and between which dates."""
    found = entries.aggregate(first=Min("on_date"), last=Max("on_date"))
    return {"entries": entries.count(),
            "first_on": found["first"].isoformat() if found["first"] else None,
            "last_on": found["last"].isoformat() if found["last"] else None}


def _check_merge(source, target) -> None:
    if target is None or target.tenant_id != source.tenant_id:
        raise FinanceError("That category is not in this practice.", status=404)
    if target.pk == source.pk:
        raise FinanceError("Choose a different category to combine it into.")
    if source.archived_at is not None:
        raise FinanceError(f"“{source.name}” is archived already.", status=409)
    if target.archived_at is not None:
        raise FinanceError(f"“{target.name}” is archived. Restore it first.", status=409)
    if source.system_code:
        raise FinanceError(f"“{source.name}” is one the books rely on. Combine the other "
                           "one into it instead.", status=409)
    if source.type != target.type:
        raise FinanceError(f"“{source.name}” is {source.get_type_display().lower()} and "
                           f"“{target.name}” is {target.get_type_display().lower()}. "
                           "Only categories of the same type combine.")
    if target.parent_id == source.pk:
        raise FinanceError(f"“{target.name}” is a sub-category of “{source.name}”. Move "
                           "it out first, or combine the other way.")
    if live_children(source).exists() and target.parent_id is not None:
        raise FinanceError(f"“{source.name}” has sub-categories and “{target.name}” is "
                           "one itself. Combine it into a top-level category.")


def merge_preview(source, target) -> dict:
    _check_merge(source, target)
    entries = FinanceEntry.all_objects.filter(category=source, removed_at__isnull=True)
    return {**_span(entries),
            "rules": FinanceRule.all_objects.filter(category=source).count(),
            "sub_categories": live_children(source).count(),
            "from": source.name, "to": target.name}


@transaction.atomic
def merge(source, target, *, actor) -> FinanceCategory:
    """Fold `source` into `target`: every entry, rule and import line that
    named it now names the other, its sub-categories go with it, and it is
    archived remembering where it went. Closed months included."""
    source = FinanceCategory.all_objects.select_for_update().get(pk=source.pk)
    target = FinanceCategory.all_objects.select_for_update().get(pk=target.pk)
    counted = merge_preview(source, target)
    now = timezone.now()
    # Straight to the rows: this is not an edit of an entry (its money, date
    # and account are untouched), so the lock on a closed month does not apply.
    FinanceEntry.all_objects.filter(category=source).update(category=target, updated_at=now)
    FinanceRule.all_objects.filter(category=source).update(category=target, updated_at=now)
    FinanceImportRow.all_objects.filter(category=source).update(category=target,
                                                                updated_at=now)
    last = live_children(target).aggregate(last=Max("position"))["last"]
    for offset, child in enumerate(live_children(source).order_by("position"), start=1):
        child.parent, child.position = target, (last or 0) + offset
        child.save(update_fields=["parent", "position", "updated_at"])
    FinanceCategory.all_objects.filter(parent=source).update(parent=target, updated_at=now)
    config = settings_for(source.tenant)
    if config.invoice_income_category_id == source.pk:
        config.invoice_income_category = target
        config.save(update_fields=["invoice_income_category", "updated_at"])
    source.archived_at, source.merged_into = now, target
    source.save(update_fields=["archived_at", "merged_into", "updated_at"])
    FinanceCategoryChange.all_objects.create(
        tenant=source.tenant, kind=FinanceCategoryChange.Kind.MERGE, from_category=source,
        to_category=target, entries_moved=counted["entries"],
        first_on=counted["first_on"], last_on=counted["last_on"], by=actor)
    audit(source.tenant, "categories_combined", actor, source, into=str(target.pk),
          **{"from": source.name, "to": target.name}, entries=counted["entries"],
          first_on=counted["first_on"], last_on=counted["last_on"])
    return target


# -------------------------------------------------------------------- split

def _chosen(source, *, contains, entry_ids):
    entries = FinanceEntry.all_objects.filter(category=source, removed_at__isnull=True)
    contains = " ".join(str(contains or "").split())
    if contains:
        if len(contains) < 2:
            raise FinanceError("The text to choose entries by is two characters or more.")
        if len(contains) > 120:
            raise FinanceError("The text to choose entries by is 120 characters at most.")
        entries = entries.filter(Q(description__icontains=contains)
                                 | Q(counterparty__icontains=contains))
    if entry_ids:
        if not isinstance(entry_ids, list):
            raise FinanceError("entries is a list.")
        entries = entries.filter(pk__in=entry_ids)
        if entries.count() != len(set(str(i) for i in entry_ids)) and not contains:
            raise FinanceError(f"Some of those entries are not in “{source.name}”.",
                               status=409)
    if not contains and not entry_ids:
        raise FinanceError("Say which entries move: the ones whose description or payee "
                           "contains some text, or the ones you tick.")
    return entries, contains


def _split_target(source, *, name, to, as_sub):
    """Where the entries go: a category that exists, or what a new one would
    be. Returns `(existing or None, name, parent)`."""
    if to is not None:
        if to.tenant_id != source.tenant_id:
            raise FinanceError("That category is not in this practice.", status=404)
        if to.pk == source.pk:
            raise FinanceError("Choose a different category to move them to.")
        if to.archived_at is not None:
            raise FinanceError(f"“{to.name}” is archived. Restore it first.", status=409)
        if to.type != source.type:
            raise FinanceError(f"“{to.name}” is {to.get_type_display().lower()} and "
                               f"“{source.name}” is {source.get_type_display().lower()}.")
        return to, to.name, to.parent
    name = _clean_name(name, "The new category")
    if FinanceCategory.all_objects.filter(tenant=source.tenant, name__iexact=name,
                                          archived_at__isnull=True).exists():
        raise FinanceError(f"There is already a category called “{name}”. Choose it to "
                           "move the entries there.", status=409)
    if as_sub and source.parent_id is not None:
        raise FinanceError(f"“{source.name}” is a sub-category, and there are two levels, "
                           "not three. Make the new one beside it.")
    return None, name, (source if as_sub else source.parent)


def split_preview(source, *, name=None, to=None, as_sub=True, contains="",
                  entry_ids=None) -> dict:
    if source.archived_at is not None:
        raise FinanceError(f"“{source.name}” is archived.", status=409)
    existing, name, parent = _split_target(source, name=name, to=to, as_sub=as_sub)
    entries, contains = _chosen(source, contains=contains, entry_ids=entry_ids)
    return {**_span(entries), "from": source.name, "to": name,
            "new": existing is None, "under": parent.name if parent else None,
            "contains": contains,
            "left": FinanceEntry.all_objects.filter(
                category=source, removed_at__isnull=True).count() - entries.count()}


@transaction.atomic
def split(source, *, actor, name=None, to=None, as_sub=True, contains="",
          entry_ids=None) -> FinanceCategory:
    """Move some of a category's entries to a new category (a sub-category of
    it, or one beside it) or to another that exists. Closed months included."""
    source = FinanceCategory.all_objects.select_for_update().get(pk=source.pk)
    counted = split_preview(source, name=name, to=to, as_sub=as_sub, contains=contains,
                            entry_ids=entry_ids)
    existing, name, parent = _split_target(source, name=name, to=to, as_sub=as_sub)
    entries, contains = _chosen(source, contains=contains, entry_ids=entry_ids)
    if counted["entries"] == 0:
        raise FinanceError("No entry matches, so there is nothing to move.", status=409)
    target = existing
    if target is None:
        siblings = FinanceCategory.all_objects.filter(tenant=source.tenant,
                                                      type=source.type, parent=parent)
        last = siblings.aggregate(last=Max("position"))["last"]
        target = FinanceCategory.all_objects.create(
            tenant=source.tenant, name=name, type=source.type, parent=parent,
            position=(last + 1) if last is not None else 0,
            is_contractor=source.is_contractor)
        audit(source.tenant, "category_created", actor, target, name=target.name,
              type=target.type, cpa_code="", split_from=str(source.pk))
    entries.update(category=target, updated_at=timezone.now())
    FinanceCategoryChange.all_objects.create(
        tenant=source.tenant, kind=FinanceCategoryChange.Kind.SPLIT, from_category=source,
        to_category=target, entries_moved=counted["entries"], contains=contains,
        first_on=counted["first_on"], last_on=counted["last_on"], by=actor)
    audit(source.tenant, "category_split", actor, source, to=str(target.pk),
          **{"from": source.name}, to_name=target.name, entries=counted["entries"],
          first_on=counted["first_on"], last_on=counted["last_on"], contains=contains)
    return target


def represent_change(row) -> dict:
    return {"id": str(row.pk), "kind": row.kind, "kind_label": row.get_kind_display(),
            "from": row.from_category.name, "to": row.to_category.name,
            "entries_moved": row.entries_moved,
            "first_on": row.first_on.isoformat() if row.first_on else None,
            "last_on": row.last_on.isoformat() if row.last_on else None,
            "contains": row.contains, "at": row.created_at.isoformat(),
            "by": (row.by.full_name or row.by.email) if row.by_id else ""}


# ------------------------------------------------- "Add the starting chart"

def starting_chart_plan(tenant) -> dict:
    """What "Add the starting chart" would add to this practice: every
    category and sub-category of the chart it does not already have, by name
    and type, without regard to case. **Nothing that exists is renamed, moved,
    re-typed, archived or removed, and no entry moves.** A category the
    practice archived counts as one it has: it was removed on purpose."""
    have = {}
    for row in FinanceCategory.all_objects.filter(tenant=tenant):
        key = (row.type, row.name.casefold())
        # A live one wins over an archived one of the same name.
        if key not in have or row.archived_at is None:
            have[key] = row
    add, skipped = [], []
    for kind, rows in STARTING_CHART:
        for name, subs in rows:
            parent = have.get((kind, name.casefold()))
            if parent is None:
                add.append({"name": name, "type": kind, "parent": None})
            for sub in subs:
                if (kind, sub.casefold()) in have:
                    continue                      # they have it, wherever it sits
                if parent is not None and parent.archived_at is not None:
                    skipped.append({"name": sub, "why": f"“{parent.name}” is archived"})
                elif parent is not None and parent.parent_id is not None:
                    skipped.append({"name": sub, "why": f"“{parent.name}” is a "
                                    "sub-category here, and there are two levels"})
                else:
                    add.append({"name": sub, "type": kind, "parent": name})
    return {"add": add, "skipped": skipped, "note": NOTE}


@transaction.atomic
def add_starting_chart(tenant, *, actor) -> dict:
    plan = starting_chart_plan(tenant)
    live = {(row.type, row.name.casefold()): row for row in
            FinanceCategory.all_objects.filter(tenant=tenant, archived_at__isnull=True)}

    def next_position(kind, parent):
        last = FinanceCategory.all_objects.filter(
            tenant=tenant, type=kind, parent=parent).aggregate(last=Max("position"))["last"]
        return (last + 1) if last is not None else 0

    for item in plan["add"]:
        parent = live.get((item["type"], item["parent"].casefold())) if item["parent"] \
            else None
        row = FinanceCategory.all_objects.create(
            tenant=tenant, name=item["name"], type=item["type"], parent=parent,
            position=next_position(item["type"], parent),
            is_contractor=item["name"] in CONTRACTOR)
        live[(row.type, row.name.casefold())] = row
    if plan["add"]:
        config = settings_for(tenant)
        audit(tenant, "starting_chart_added", actor, config,
              added=[item["name"] for item in plan["add"]],
              skipped=[item["name"] for item in plan["skipped"]])
    return plan
