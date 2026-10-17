"""The household (P6 M4 stop 3, decision 18): the owner and the people they
add. **A person is a label, not a sign-in** (invitations with their own
sign-in come in a later stop, once the external Google client is sorted).

Income (an income category), accounts, debts, retirement and investments,
and things owned each carry *whose*: one person, or nobody, which is joint.
The views are the household, or one person; one person's view is what is
theirs alone, and joint things are in the household's. A spouse's expected
W-2 withholding is kept for the tax estimate (stop 4).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.personal.models import (
    PersonalAccount, PersonalAsset, PersonalCategory, PersonalDebt, PersonalHolding,
    PersonalMember,
)
from apps.personal.services import PersonalError

#: What can carry whose, by the name the routes use.
THINGS = {"account": PersonalAccount, "category": PersonalCategory, "debt": PersonalDebt,
          "holding": PersonalHolding, "asset": PersonalAsset}


def members(ledger):
    """The household, the owner first. The owner is made the first time."""
    rows = PersonalMember.objects.filter(ledger=ledger, removed_at__isnull=True)
    if not rows.filter(relation=PersonalMember.Relation.SELF).exists():
        owner = ledger.owner
        PersonalMember.objects.create(ledger=ledger, relation=PersonalMember.Relation.SELF,
                                      name=(owner.full_name or owner.email).strip()[:120],
                                      position=0)
    return rows.order_by("position", "name")


def member(ledger, pk) -> PersonalMember:
    found = PersonalMember.objects.filter(ledger=ledger, pk=pk,
                                          removed_at__isnull=True).first() if pk else None
    if found is None:
        raise PersonalError("That person is not in your household.", status=404)
    return found


def represent(row) -> dict:
    return {"id": str(row.pk), "name": row.name, "relation": row.relation,
            "relation_label": row.get_relation_display(),
            "expected_withholding_cents": row.expected_withholding_cents,
            "is_you": row.relation == PersonalMember.Relation.SELF}


@transaction.atomic
def save(ledger, *, row=None, data: dict) -> PersonalMember:
    made = row is None
    row = row or PersonalMember(ledger=ledger)
    if "name" in data or made:
        row.name = " ".join(str(data.get("name") or "").split())[:120]
        if not row.name:
            raise PersonalError("Give them a name.")
    if "relation" in data or made:
        relation = data.get("relation") or PersonalMember.Relation.SPOUSE
        if relation not in PersonalMember.Relation.values:
            raise PersonalError("relation is spouse, partner or other.")
        if relation == PersonalMember.Relation.SELF and row.relation != relation:
            raise PersonalError("There is one of you.", status=409)
        if not made and row.relation == PersonalMember.Relation.SELF and relation != row.relation:
            raise PersonalError("You stay you.", status=409)
        row.relation = relation
    if "expected_withholding_cents" in data:
        value = data["expected_withholding_cents"]
        if value in (None, ""):
            row.expected_withholding_cents = None
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PersonalError("The withholding is a whole number of cents, zero or more.")
        else:
            row.expected_withholding_cents = value
    if made:
        row.position = PersonalMember.objects.filter(ledger=ledger).count()
    row.save()
    return row


@transaction.atomic
def remove(row) -> None:
    """Take a person out of the household: what was theirs becomes joint."""
    if row.relation == PersonalMember.Relation.SELF:
        raise PersonalError("You stay in your own household.", status=409)
    for model in THINGS.values():
        model.objects.filter(ledger=row.ledger, whose=row).update(whose=None)
    row.removed_at = timezone.now()
    row.save(update_fields=["removed_at", "updated_at"])


def set_whose(ledger, *, thing: str, pk, whose) -> None:
    model = THINGS.get(thing)
    if model is None:
        raise PersonalError("That cannot belong to someone.")
    found = model.objects.filter(ledger=ledger, pk=pk).first()
    if found is None:
        raise PersonalError("There is no such thing.", status=404)
    if thing == "category" and found.type != PersonalCategory.Type.INCOME:
        raise PersonalError("Whose is for income categories.")
    found.whose = member(ledger, whose) if whose else None
    found.save(update_fields=["whose", "updated_at"])


def whose_is_what(ledger) -> list[dict]:
    """Everything that carries whose, for the Household page."""
    out = []

    def add(thing, row, label, what):
        out.append({"thing": thing, "id": str(row.pk), "name": row.name, "what": what,
                    "label": label, "whose": str(row.whose_id) if row.whose_id else None})

    for row in PersonalCategory.objects.filter(ledger=ledger, type="income",
                                               archived_at__isnull=True,
                                               parent__isnull=False):
        add("category", row, "Income", "income")
    for row in PersonalAccount.objects.filter(ledger=ledger, closed_at__isnull=True):
        add("account", row, row.get_kind_display(), "account")
    for row in PersonalDebt.objects.filter(ledger=ledger, closed_at__isnull=True):
        add("debt", row, row.get_kind_display(), "debt")
    for row in PersonalHolding.objects.filter(ledger=ledger, closed_at__isnull=True):
        add("holding", row, row.get_kind_display(), "holding")
    for row in PersonalAsset.objects.filter(ledger=ledger, closed_at__isnull=True):
        add("asset", row, row.get_kind_display(), "asset")
    return out


def income_by_person(ledger) -> list[dict]:
    """Each income category's monthly median over the last complete months,
    with whose it is: what each person brings in."""
    from statistics import median

    from apps.personal import budget

    months = budget.covered_months(ledger)
    totals = budget.totals_by_month(ledger, months)
    out = []
    for row in PersonalCategory.objects.filter(ledger=ledger, type="income",
                                               archived_at__isnull=True,
                                               pk__in=list(totals)).select_related("whose"):
        amounts = [max(0, totals[row.pk].get(m, 0)) for m in months]
        out.append({"category": row.name, "whose": str(row.whose_id) if row.whose_id else None,
                    "whose_name": row.whose.name if row.whose_id else "Joint",
                    "monthly_cents": int(median(amounts)) if amounts else 0})
    return sorted(out, key=lambda r: -r["monthly_cents"])
