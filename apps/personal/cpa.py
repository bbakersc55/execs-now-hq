"""For your CPA, the personal section (P6 M4 decisions 22 and 23).

- **The Itemized Deduction Worksheet, by the CPA's six groups** (the
  placeholder's table of 2026-10-10): medical and dental, health insurance,
  interest paid, property taxes, charitable contributions, non-cash
  donations by charity. Filled from the year's lines whose category carries
  the group's Tax-deductible mark, every line listed, and from figures typed
  for the CPA (`PersonalTaxItem`: a non-cash donation naming its charity, an
  amount from a form). Medical and charitable miles are year-end facts, like
  M1's business miles.
- **Personal facts**, each with "ask your CPA": estimated payments by
  quarter, health insurance premiums (as a self-employed person, perhaps),
  retirement contributions by account, the HSA, childcare and education.
- **Standard against itemized** (23): the itemized total beside the year's
  standard deduction for the filing status, and no advice beyond "ask your
  CPA".
- **One PDF with both sections**: the business worksheet exactly as the
  CSV has it (`finance.reports.worksheet`), then this. The business CSV is
  unchanged.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.personal import retirement, tax_tables, taxes
from apps.personal.models import PersonalCategory, PersonalLine, PersonalTaxItem
from apps.personal.services import PersonalError

G = PersonalCategory.TaxGroup
ASK = "Ask your CPA."
#: The six groups in the worksheet's order, and what each says beside it.
GROUPS = (
    (G.MEDICAL, "Medical and dental", "medical_miles"),
    (G.HEALTH_INSURANCE, "Health insurance", None),
    (G.INTEREST, "Interest paid", None),
    (G.PROPERTY_TAX, "Property taxes", None),
    (G.CHARITABLE, "Charitable contributions", "charitable_miles"),
    (G.NON_CASH, "Non-cash donations, by charity", None),
)
CHILDCARE = "Childcare and education"
STANDARD_NOTE = ("The itemized total is before any limits your CPA applies. Whether to "
                 "itemize: ask your CPA.")


def _year_lines(ledger, year: int):
    return PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, on_date__year=year,
        category__isnull=False).select_related("category", "account")


def _signed(line) -> int:
    """Spending counts; money back in the same category takes away from it."""
    return line.amount_cents if line.direction == "out" else -line.amount_cents


def items(ledger, year: int):
    return PersonalTaxItem.objects.filter(ledger=ledger, year=year, removed_at__isnull=True)


def groups(ledger, year: int) -> list[dict]:
    """Each of the six groups with every line in it: the year's lines in a
    category with its mark, and the figures typed for it."""
    facts = taxes.inputs(ledger, year)
    by_group: dict = {code: [] for code, _label, _miles in GROUPS}
    for line in _year_lines(ledger, year).exclude(category__tax_group="")\
            .order_by("on_date", "created_at"):
        by_group[line.category.tax_group].append({
            "kind": "line", "id": str(line.pk), "on_date": line.on_date.isoformat(),
            "item": line.category.name, "description": line.description,
            "charity": line.description if line.category.tax_group == G.NON_CASH else "",
            "account": line.account.name if line.account_id else "",
            "amount_cents": _signed(line)})
    for row in items(ledger, year):
        by_group[row.tax_group].append({
            "kind": "item", "id": str(row.pk),
            "on_date": row.on_date.isoformat() if row.on_date else None,
            "item": "Donated goods" if row.tax_group == G.NON_CASH else "Entered for your CPA",
            "description": row.description,
            "charity": row.charity, "account": "", "amount_cents": row.amount_cents})
    out = []
    for code, label, miles in GROUPS:
        rows = sorted(by_group[code], key=lambda r: (r["on_date"] or "9999", r["item"]))
        if code == G.NON_CASH:
            rows.sort(key=lambda r: (r["charity"].lower(), r["on_date"] or "9999"))
        out.append({"group": code, "label": label, "rows": rows,
                    "total_cents": sum(r["amount_cents"] for r in rows),
                    "miles": (getattr(facts, miles) if facts is not None else None)
                    if miles else None,
                    "miles_label": ("Medical miles" if miles == "medical_miles"
                                    else "Charitable miles") if miles else ""})
    return out


def itemized_total(ledger, year: int) -> int:
    """The six groups' money, before any limit (miles are not money)."""
    return sum(group["total_cents"] for group in groups(ledger, year))


def standard_against_itemized(ledger, year: int, found: list[dict] | None = None) -> dict:
    """Decision 23: the itemized total beside the standard deduction for the
    filing status and year."""
    found = groups(ledger, year) if found is None else found
    total = sum(group["total_cents"] for group in found)
    facts = taxes.inputs(ledger, year)
    status = facts.filing_status if facts is not None else ""
    if not status:
        return {"itemized_cents": total, "standard_cents": None, "status": "",
                "status_label": "", "figures_year": None, "note": STANDARD_NOTE,
                "figures_note": ""}
    figures, figures_year, note = tax_tables.for_year(year)
    return {"itemized_cents": total, "standard_cents": figures["standard"][status],
            "status": status, "status_label": tax_tables.STATUSES[status],
            "figures_year": figures_year, "note": STANDARD_NOTE, "figures_note": note}


def _months_of(year: int, today: date) -> int:
    if today.year > year:
        return 12
    if today.year < year:
        return 0
    return today.month - 1


def facts(ledger, tenant, year: int, today: date | None = None,
          found: list[dict] | None = None) -> list[dict]:
    """The Personal facts block, each with "ask your CPA"."""
    today = today or timezone.localdate()
    found = groups(ledger, year) if found is None else found
    out = []
    paid = taxes.payments(ledger, tenant, year)
    quarters = []
    for n, due in enumerate(taxes.due_dates(year)):
        mine = [p for p in paid if p["quarter"] == n]
        quarters.append({"label": due["label"], "due_on": due["on_date"].isoformat(),
                         "payments": [{"on_date": p["on_date"].isoformat(),
                                       "which": p["which"], "from": p["from"],
                                       "amount_cents": p["amount_cents"]} for p in mine],
                         "total_cents": sum(p["amount_cents"] for p in mine)})
    out.append({"key": "estimated", "label": "Estimated tax payments, by quarter",
                "quarters": quarters, "total_cents": sum(p["amount_cents"] for p in paid),
                "note": "Federal and state, from the practice's account or the "
                        "household's. " + ASK})
    health = next(g for g in found if g["group"] == G.HEALTH_INSURANCE)
    out.append({"key": "health", "label": "Health insurance premiums",
                "total_cents": health["total_cents"],
                "note": "Paid as a self-employed person, they may be deducted another "
                        "way than itemizing. " + ASK})
    accounts = []
    months = _months_of(year, today)
    for holding in retirement.holdings(ledger).filter(kind="retirement"):
        seen = _contributed(holding, year)
        if seen:
            accounts.append({"name": holding.name, "cents": seen, "from": "lines",
                             "detail": "From the lines that are its contributions."})
        elif holding.monthly_cents:
            accounts.append({"name": holding.name, "cents": holding.monthly_cents * months,
                             "from": "typed",
                             "detail": f"{months} months at the amount you typed a month: "
                                       "an estimate."})
    out.append({"key": "retirement", "label": "Retirement contributions, by account",
                "accounts": accounts, "total_cents": sum(a["cents"] for a in accounts),
                "note": ASK})
    hsa = taxes.inputs(ledger, year)
    out.append({"key": "hsa", "label": "HSA contributions",
                "total_cents": hsa.hsa_cents if hsa is not None else None, "note": ASK})
    childcare = [line for line in _year_lines(ledger, year)
                 if CHILDCARE in (line.category.name, line.category.parent.name
                                  if line.category.parent_id else "")]
    out.append({"key": "childcare", "label": "Childcare and education",
                "total_cents": sum(_signed(line) for line in childcare),
                "lines": len(childcare), "note": ASK})
    return out


def _contributed(holding, year: int) -> int:
    text = holding.contribution_text.strip()
    if not text:
        return 0
    return sum(PersonalLine.objects.filter(
        ledger=holding.ledger, removed_at__isnull=True, account__isnull=False,
        direction="out", description__icontains=text, on_date__year=year)
        .values_list("amount_cents", flat=True))


def personal_section(ledger, tenant, year: int, today: date | None = None) -> dict:
    found = groups(ledger, year)
    return {"year": year, "groups": found,
            "standard": standard_against_itemized(ledger, year, found),
            "facts": facts(ledger, tenant, year, today, found),
            "inputs": taxes._inputs_out(taxes.inputs(ledger, year), year),
            "confirm": taxes.CONFIRM}


def both(ledger, tenant, year: int, today: date | None = None) -> dict:
    """The page: the business worksheet as built in M1, then the personal
    section."""
    from apps.finance import reports

    return {"year": year, "business": reports.worksheet(tenant, year=year),
            "personal": personal_section(ledger, tenant, year, today)}


# -------------------------------------------- what the owner types for it

@transaction.atomic
def save_item(ledger, *, item=None, year, tax_group, description, amount_cents,
              on_date=None, charity="") -> PersonalTaxItem:
    """A figure for the CPA that is not a line of an account: a non-cash
    donation (which names its charity) or an amount from a form."""
    if tax_group not in {code for code, _label, _miles in GROUPS}:
        raise PersonalError("Choose one of the six groups.")
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise PersonalError("The year is a year, like 2026.")
    description = " ".join(str(description or "").split())[:255]
    charity = " ".join(str(charity or "").split())[:160]
    if not description:
        raise PersonalError("Say what it is.")
    if tax_group == G.NON_CASH and not charity:
        raise PersonalError("A non-cash donation names its charity.")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) \
            or amount_cents <= 0:
        raise PersonalError("The amount is a whole number of cents, more than nothing.")
    row = item or PersonalTaxItem(ledger=ledger)
    row.year, row.tax_group, row.description = year, tax_group, description
    row.charity, row.amount_cents, row.on_date = charity, amount_cents, on_date
    row.save()
    return row


def remove_item(item) -> None:
    item.removed_at = timezone.now()
    item.save(update_fields=["removed_at", "updated_at"])


# ------------------------------------------------------------------ the PDF

def render_html(ledger, tenant, year: int, today: date | None = None) -> str:
    from apps.finance.disclaimer import DISCLAIMER
    from apps.personal.budget_ai import DISCLAIMER as PERSONAL_DISCLAIMER

    page = both(ledger, tenant, year, today)
    return render_to_string("personal/cpa.html", {
        "page": page, "business": page["business"], "personal": page["personal"],
        "practice": tenant.name if tenant is not None else "",
        "made_on": f"{timezone.localdate():%B} {timezone.localdate().day}, "
                   f"{timezone.localdate().year}",
        "business_disclaimer": DISCLAIMER, "personal_disclaimer": PERSONAL_DISCLAIMER,
    })


def render_pdf(ledger, tenant, year: int) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(ledger, tenant, year)).write_pdf()
