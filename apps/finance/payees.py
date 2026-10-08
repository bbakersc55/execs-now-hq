"""1099 tracking (owner, 2026-10-08): who the practice may owe a 1099, what
each was paid in a calendar year, and who is over the threshold.

A payee is a contact with the 1099 flag. An expense entry names its payee;
the year's total is those entries, less refunds.

**Two things here are tax rules as this module understands them, and the
practice's CPA has the last word on both:**

- **The threshold.** $600 for payments made through 2025; $2,000 for payments
  made in 2026 and after. The report takes another figure if given one.
- **Card payments are left out of the reportable total.** A payment made by
  credit card is reported by the card company, not by the payer. Both figures
  are shown, so nothing is hidden by the rule.

W-2 tracking is not here; it belongs to the HRIS module.
"""

from __future__ import annotations

import csv
import io

from django.db.models import Q, Sum

from apps.crm.models import Contact
from apps.finance.models import FinanceAccount, FinanceEntry
from apps.finance.reports import SIGNED, live

K = FinanceEntry.Kind


def default_threshold_cents(year: int) -> int:
    return 60000 if year <= 2025 else 200000


def payees(tenant):
    return (Contact.all_objects.filter(tenant=tenant, is_1099_payee=True,
                                       deleted_at__isnull=True)
            .select_related("company").order_by("last_name", "first_name"))


def report(tenant, *, year: int, threshold_cents: int | None = None) -> dict:
    threshold = default_threshold_cents(year) if threshold_cents is None else threshold_cents
    paid = live(tenant).filter(kind=K.EXPENSE, on_date__year=year,
                               payee_contact__isnull=False)
    totals = {row["payee_contact_id"]: row for row in paid.values("payee_contact_id").annotate(
        total=Sum(SIGNED),
        by_card=Sum(SIGNED, filter=Q(account__kind=FinanceAccount.Kind.CARD)))}
    rows = []
    for contact in payees(tenant):
        found = totals.pop(contact.pk, None) or {}
        total, by_card = found.get("total") or 0, found.get("by_card") or 0
        rows.append(_row(contact, total, by_card, threshold, flagged=True))
    # Paid as a payee this year, and since unflagged: still shown, and marked.
    for contact in Contact.all_objects.filter(tenant=tenant, pk__in=list(totals)):
        found = totals[contact.pk]
        rows.append(_row(contact, found["total"] or 0, found["by_card"] or 0, threshold,
                         flagged=False))
    rows.sort(key=lambda row: (-row["reportable_cents"], row["name"]))
    return {"year": year, "threshold_cents": threshold,
            "default_threshold_cents": default_threshold_cents(year),
            "payees": rows, "over": sum(1 for row in rows if row["over_threshold"])}


def _row(contact, total, by_card, threshold, *, flagged) -> dict:
    reportable = total - by_card
    return {
        "contact": str(contact.pk),
        "name": f"{contact.first_name} {contact.last_name}".strip(),
        "company": contact.company.name if contact.company_id else "",
        "is_payee": flagged, "total_cents": total, "by_card_cents": by_card,
        "reportable_cents": reportable, "over_threshold": reportable >= threshold > 0,
    }


def export(data: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    plain = lambda cents: f"{cents / 100:.2f}"  # noqa: E731
    writer.writerow([f"1099 payees, {data['year']}, threshold "
                     f"{plain(data['threshold_cents'])}"])
    writer.writerow(["Payee", "Company", "Paid in the year", "Of which by card",
                     "Reportable (not by card)", "At or over the threshold"])
    for row in data["payees"]:
        writer.writerow([row["name"], row["company"], plain(row["total_cents"]),
                         plain(row["by_card_cents"]), plain(row["reportable_cents"]),
                         "yes" if row["over_threshold"] else ""])
    return out.getvalue()
