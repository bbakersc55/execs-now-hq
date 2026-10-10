"""Several entries at once (owner, 2026-10-10): change their category, or
remove them.

Both say first how many they would act on and how many they would leave out,
and why (`plan`), and then act on exactly those (`apply`). Entries in a
locked period are always left out. Each entry keeps its own line of history,
as when it is changed one at a time; and the action as a whole is one more
audit event, with its count and its dates, as a combine is.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.finance import services
from apps.finance.models import FinanceCleared, FinanceEntry, FinanceReconciliation
from apps.finance.services import FinanceError
from apps.tenancy.models import AuditEvent

RECATEGORIZE, REMOVE = "recategorize", "remove"
VERB = {RECATEGORIZE: "finance.entries_recategorized", REMOVE: "finance.entries_removed"}

#: Why an entry is left out, in the order they are reported.
WHY = {
    "locked": "in a closed or locked month",
    "transfer": "a transfer, which has no category",
    "type": "of a kind that category cannot take",
    "same": "already in that category",
    "invoice": "an invoice payment, removed on its invoice",
    "cleared": "ticked off in a finished reconciliation",
}


def _chosen(tenant, entry_ids):
    if not isinstance(entry_ids, list) or not entry_ids:
        raise FinanceError("entries is a list of entries.")
    try:
        rows = list(FinanceEntry.all_objects.filter(
            tenant=tenant, pk__in=entry_ids, removed_at__isnull=True)
            .select_related("category").order_by("on_date", "created_at"))
    except (ValueError, TypeError, ValidationError):
        raise FinanceError("entries is a list of entries.") from None
    if len(rows) != len({str(pk) for pk in entry_ids}):
        raise FinanceError("One of those entries is not in this practice, or was removed.",
                           status=404)
    return rows


def _sort(tenant, rows, action, category):
    """Each entry: acted on, or left out and why."""
    locked = services.settings_for(tenant).locked_through
    cleared = set()
    if action == REMOVE:
        cleared = set(FinanceCleared.all_objects.filter(
            tenant=tenant, entry__in=rows,
            reconciliation__state=FinanceReconciliation.State.FINISHED)
            .values_list("entry_id", flat=True))
    acting, left = [], {}
    for entry in rows:
        why = ""
        if locked is not None and entry.on_date <= locked:
            why = "locked"
        elif action == RECATEGORIZE:
            if entry.kind == FinanceEntry.Kind.TRANSFER:
                why = "transfer"
            elif services.TYPE_FOR_KIND.get(entry.kind) != category.type:
                why = "type"
            elif entry.category_id == category.pk:
                why = "same"
        elif entry.source == FinanceEntry.Source.INVOICE:
            why = "invoice"
        elif entry.pk in cleared:
            why = "cleared"
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            acting.append(entry)
    return acting, left


def _check(tenant, action, category):
    if action not in (RECATEGORIZE, REMOVE):
        raise FinanceError("action is recategorize or remove.")
    if action == RECATEGORIZE:
        services._own(tenant, category, "category")
        if category is None or category.archived_at is not None:
            raise FinanceError("Choose a category that is in use.")


def plan(tenant, *, action, entry_ids, category=None) -> dict:
    """What it would do, counted, before it does anything."""
    _check(tenant, action, category)
    rows = _chosen(tenant, entry_ids)
    acting, left = _sort(tenant, rows, action, category)
    dates = [entry.on_date for entry in acting]
    return {
        "action": action, "chosen": len(rows), "count": len(acting),
        "first_on": min(dates).isoformat() if dates else None,
        "last_on": max(dates).isoformat() if dates else None,
        "to": category.name if action == RECATEGORIZE else "",
        "left_out": [{"why": code, "label": WHY[code], "count": left[code]}
                     for code in WHY if code in left],
    }


@transaction.atomic
def apply(tenant, *, actor, action, entry_ids, category=None, reason="") -> dict:
    """Act on exactly what `plan` counted. Nothing in a locked period is
    touched; what is left out is left alone."""
    _check(tenant, action, category)
    reason = str(reason or "").strip()
    if action == REMOVE and not reason:
        raise FinanceError("Say why the entries are being removed.")
    rows = _chosen(tenant, entry_ids)
    done = plan(tenant, action=action, entry_ids=entry_ids, category=category)
    acting, _left = _sort(tenant, rows, action, category)
    if not acting:
        raise FinanceError("None of the chosen entries can be "
                           + ("moved to that category." if action == RECATEGORIZE
                              else "removed."), status=409)
    if action == RECATEGORIZE:
        services.recategorize(tenant, actor=actor, entries=acting, category=category)
    else:
        for entry in acting:
            services.remove_entry(entry, actor=actor, reason=reason)
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb=VERB[action], target_type="finance_entry",
        payload={"count": done["count"], "chosen": done["chosen"],
                 "first_on": done["first_on"], "last_on": done["last_on"],
                 "to": done["to"], "category": str(category.pk) if category else "",
                 "reason": reason, "left_out": done["left_out"]})
    return done


def history(tenant) -> list[dict]:
    """Every bulk change, newest first: what it was, how many, between which
    dates, and who."""
    events = (AuditEvent.all_objects.filter(tenant=tenant, verb__in=list(VERB.values()))
              .select_related("actor").order_by("-created_at")[:50])
    return [{
        "id": str(event.pk), "at": event.created_at.isoformat(),
        "action": RECATEGORIZE if event.verb == VERB[RECATEGORIZE] else REMOVE,
        "count": event.payload.get("count", 0), "to": event.payload.get("to", ""),
        "first_on": event.payload.get("first_on"), "last_on": event.payload.get("last_on"),
        "reason": event.payload.get("reason", ""),
        "by": (event.actor.full_name or event.actor.email) if event.actor else "",
    } for event in events]

