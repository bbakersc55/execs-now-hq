"""Personal finance's routes (P6 M4 stop 1), all under /api/personal/.

**Who reaches them** (decision 24): the practice owner, in a practice with the
Personal finance module, and only ever their own ledger. Everyone else gets
404, as if the routes were not there: an associate, an assistant, a client
user, the platform owner in the Practices area, and anyone acting as a client.
Every query below goes through `ledger`, which is the signed-in person's.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import permissions as crm_perms
from apps.finance import services as books
from apps.finance.models import FinanceAccount, FinanceCategory, FinanceEntry
from apps.personal import services
from apps.personal.models import PersonalAccount, PersonalCategory, PersonalLine
from apps.tenancy import modules
from apps.tenancy.models import Role

LIST_MOST = 500


def represent_category(row) -> dict:
    return {"id": str(row.pk), "name": row.name, "type": row.type,
            "parent": str(row.parent_id) if row.parent_id else None,
            "position": row.position, "system": bool(row.system_code),
            "tax_group": row.tax_group, "tax_group_label": row.get_tax_group_display()
            if row.tax_group else "", "archived": row.archived_at is not None}


def represent_account(row) -> dict:
    return {"id": str(row.pk), "name": row.name, "kind": row.kind,
            "kind_label": row.get_kind_display(), "last4": row.last4,
            "opening_balance_cents": row.opening_balance_cents,
            "opening_on": row.opening_on.isoformat(), "closed": row.closed_at is not None,
            "side": "personal", "in_books": False}


def represent_mixed(row) -> dict:
    """One of the practice's accounts marked Mixed: listed on the personal
    side too, because its personal lines are the owner's."""
    return {"id": str(row.pk), "name": row.name, "kind": row.kind,
            "kind_label": row.get_kind_display(), "last4": row.last4,
            "closed": row.closed_at is not None, "side": "mixed", "in_books": True}


def represent_line(row) -> dict:
    entry = row.finance_entry
    return {"id": str(row.pk), "kind": "line", "on_date": row.on_date.isoformat(),
            "amount_cents": row.amount_cents, "direction": row.direction,
            "description": row.description,
            "category": ({"id": str(row.category_id), "name": row.category.name,
                          "tax_group": row.category.tax_group}
                         if row.category_id else None),
            "account": ({"id": str(row.account_id), "name": row.account.name}
                        if row.account_id else
                        {"id": str(entry.account_id), "name": entry.account.name}
                        if entry is not None and entry.account_id else None),
            "from_books": entry is not None, "source": row.source,
            "to_sort": row.category_id is None}


def represent_waiting(entry) -> dict:
    """A Mixed account's line no rule placed: it waits for a side."""
    return {"id": str(entry.pk), "kind": "entry", "on_date": entry.on_date.isoformat(),
            "amount_cents": entry.amount_cents, "direction": entry.direction,
            "description": entry.description, "category": None,
            "account": {"id": str(entry.account_id), "name": entry.account.name},
            "from_books": True, "source": "books", "to_sort": True}


class OwnerOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if crm_perms.role_of(request) != Role.FF or getattr(request, "acting_as", None):
            raise Http404
        if not modules.has(getattr(request, "tenant", None), modules.PERSONAL):
            raise Http404
        return True


class PersonalView(APIView):
    permission_classes = [permissions.IsAuthenticated, OwnerOnly]

    @property
    def ledger(self):
        if not hasattr(self, "_ledger"):
            self._ledger = services.ledger_for(self.request.user)
        return self._ledger

    @staticmethod
    def refusal(exc):
        return Response({"detail": str(exc)}, status=getattr(exc, "status", 400))

    def category(self, pk):
        return services.personal_category(self.ledger, pk) if pk else None

    def mixed_accounts(self):
        return FinanceAccount.all_objects.filter(tenant=self.request.tenant,
                                                 side=FinanceAccount.Side.MIXED)


class LedgerView(PersonalView):
    """GET/PATCH /api/personal/ledger — the threshold (decision 5)."""

    def get(self, request):
        return Response({"to_sort_threshold_cents": self.ledger.to_sort_threshold_cents})

    def patch(self, request):
        if "to_sort_threshold_cents" in request.data:
            try:
                cents = books._cents(request.data["to_sort_threshold_cents"], "The threshold")
            except books.FinanceError as exc:
                return self.refusal(exc)
            self.ledger.to_sort_threshold_cents = cents
            self.ledger.save(update_fields=["to_sort_threshold_cents", "updated_at"])
        return self.get(request)


class CategoryListView(PersonalView):
    """GET/POST /api/personal/categories — the personal chart (decision 4)."""

    def get(self, request):
        rows = PersonalCategory.objects.filter(ledger=self.ledger)
        if request.query_params.get("archived") != "1":
            rows = rows.filter(archived_at__isnull=True)
        return Response({"categories": [represent_category(row) for row in rows],
                         "tax_groups": [{"code": code, "label": label} for code, label
                                        in PersonalCategory.TaxGroup.choices if code]})

    def post(self, request):
        data = request.data
        try:
            name = books._clean_name(data.get("name"), "A category")
            parent = self.category(data.get("parent")) if data.get("parent") else None
            if parent is not None and parent.parent_id:
                raise services.PersonalError("A sub-category's parent is a top-level category.")
            type_ = parent.type if parent else data.get("type") or "expense"
            if type_ not in PersonalCategory.Type.values:
                raise services.PersonalError("type is expense, income or transfer.")
            tax = data.get("tax_group") or ""
            if tax not in PersonalCategory.TaxGroup.values:
                raise services.PersonalError("That is not one of the CPA's groups.")
            if PersonalCategory.objects.filter(ledger=self.ledger, name__iexact=name,
                                               archived_at__isnull=True).exists():
                raise services.PersonalError(f"There is already a category called “{name}”.",
                                             status=409)
            row = PersonalCategory.objects.create(
                ledger=self.ledger, name=name, type=type_, parent=parent, tax_group=tax,
                position=PersonalCategory.objects.filter(ledger=self.ledger,
                                                         parent=parent).count())
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_category(row), status=201)


class CategoryView(PersonalView):
    """PATCH /api/personal/categories/<id> — rename, the Tax-deductible mark,
    archive and restore."""

    def patch(self, request, pk):
        data = request.data
        row = PersonalCategory.objects.filter(ledger=self.ledger, pk=pk).first()
        if row is None:
            raise Http404
        try:
            if "name" in data:
                name = books._clean_name(data["name"], "A category")
                if PersonalCategory.objects.filter(
                        ledger=self.ledger, name__iexact=name,
                        archived_at__isnull=True).exclude(pk=row.pk).exists():
                    raise services.PersonalError(
                        f"There is already a category called “{name}”.", status=409)
                row.name = name
            if "tax_group" in data:
                tax = data["tax_group"] or ""
                if tax not in PersonalCategory.TaxGroup.values:
                    raise services.PersonalError("That is not one of the CPA's groups.")
                row.tax_group = tax
            if "archived" in data:
                if row.system_code and data["archived"]:
                    raise services.PersonalError(
                        f"“{row.name}” is one this module relies on; it stays.", status=409)
                row.archived_at = timezone.now() if data["archived"] else None
            row.save()
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_category(row))


class AccountListView(PersonalView):
    """GET/POST /api/personal/accounts — the household's own accounts, and the
    practice's Mixed ones beside them."""

    def get(self, request):
        own = PersonalAccount.objects.filter(ledger=self.ledger)
        return Response([represent_account(row) for row in own]
                        + [represent_mixed(row) for row in self.mixed_accounts()])

    def post(self, request):
        return self._save(request, None)

    def _save(self, request, row):
        data = request.data
        try:
            if row is None:
                row = PersonalAccount(ledger=self.ledger, opening_on=timezone.localdate())
                if not data.get("name"):
                    raise services.PersonalError("An account needs a name.")
            if "name" in data:
                row.name = books._clean_name(data["name"], "An account")
            if "kind" in data:
                if data["kind"] not in PersonalAccount.Kind.values:
                    raise services.PersonalError("kind is bank, card or cash.")
                if row.pk and data["kind"] != row.kind and row.lines.exists():
                    raise services.PersonalError("An account with lines keeps its kind.",
                                                 status=409)
                row.kind = data["kind"]
            if "last4" in data:
                last4 = str(data["last4"] or "").strip()
                if last4 and (len(last4) != 4 or not last4.isdigit()):
                    raise services.PersonalError("The last four digits are four digits.")
                row.last4 = last4
            if "opening_balance_cents" in data:
                row.opening_balance_cents = books._cents(
                    data["opening_balance_cents"], "An opening balance", signed=True)
            if "opening_on" in data:
                row.opening_on = books._a_date(data["opening_on"], "The opening date")
            if "closed" in data and row.pk:
                row.closed_at = timezone.now() if data["closed"] else None
            row.save()
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_account(row), status=200 if "id" in data else 201)


class AccountView(AccountListView):
    def patch(self, request, pk):
        row = PersonalAccount.objects.filter(ledger=self.ledger, pk=pk).first()
        if row is None:
            raise Http404
        return self._save(request, row)


class LineListView(PersonalView):
    """GET /api/personal/lines — the personal side's entries. `to_sort=1`:
    only what waits (decision 5), with a Mixed account's lines not yet given
    a side first. `category`, `account`, `from`, `to` narrow it."""

    def get(self, request):
        params = request.query_params
        rows = (PersonalLine.objects.filter(ledger=self.ledger, removed_at__isnull=True)
                .select_related("category", "account", "finance_entry__account"))
        waiting = []
        if params.get("to_sort") == "1":
            rows = rows.filter(category__isnull=True)
            waiting = list(FinanceEntry.all_objects.filter(
                tenant=request.tenant, side=FinanceEntry.Side.TO_SORT,
                removed_at__isnull=True).select_related("account").order_by("-on_date"))
        try:
            if params.get("category"):
                rows = rows.filter(category=self.category(params["category"]))
            if params.get("account"):
                rows = rows.filter(account_id=params["account"]) \
                    | rows.filter(finance_entry__account_id=params["account"])
            if params.get("from"):
                rows = rows.filter(on_date__gte=books._a_date(params["from"], "from"))
            if params.get("to"):
                rows = rows.filter(on_date__lte=books._a_date(params["to"], "to"))
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        lines = [represent_waiting(e) for e in waiting] + [represent_line(r) for r in
                                                            rows[:LIST_MOST]]
        to_sort = (PersonalLine.objects.filter(ledger=self.ledger, removed_at__isnull=True,
                                               category__isnull=True).count()
                   + FinanceEntry.all_objects.filter(
                       tenant=request.tenant, side=FinanceEntry.Side.TO_SORT,
                       removed_at__isnull=True).count())
        return Response({"lines": lines, "to_sort": to_sort,
                         "threshold_cents": self.ledger.to_sort_threshold_cents})


class LineView(PersonalView):
    """PATCH /api/personal/lines/<id> — a line's category; `remember` keeps
    it as a rule (decision 5: rules learn from every choice)."""

    def patch(self, request, pk):
        row = PersonalLine.objects.filter(ledger=self.ledger, pk=pk,
                                          removed_at__isnull=True).first()
        if row is None:
            raise Http404
        try:
            with transaction.atomic():
                row.category = self.category(request.data.get("category"))
                row.save(update_fields=["category", "updated_at"])
                if request.data.get("remember") and row.finance_entry_id:
                    services.remember_rule(
                        request.tenant, actor=request.user,
                        contains=request.data["remember"], side="personal",
                        personal_category=row.category)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_line(row))


class BulkView(PersonalView):
    """POST /api/personal/lines/bulk {lines, category} — several at once
    (decision 5, "bulk actions as on business Entries")."""

    def post(self, request):
        ids = request.data.get("lines")
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "lines is a list of lines."}, status=400)
        try:
            category = self.category(request.data.get("category"))
            rows = PersonalLine.objects.filter(ledger=self.ledger, pk__in=ids,
                                               removed_at__isnull=True)
            if rows.count() != len(set(ids)):
                raise services.PersonalError("One of those lines is not yours, or was removed.",
                                             status=404)
            count = rows.update(category=category, updated_at=timezone.now())
        except (services.PersonalError, books.FinanceError, ValueError) as exc:
            return self.refusal(exc)
        return Response({"updated": count})


class SortView(PersonalView):
    """POST /api/personal/sort {entry, side, category?, personal_category?,
    remember?} — a line of one of the practice's accounts, put on a side
    (decisions 2 and 3)."""

    def post(self, request):
        data = request.data
        entry = FinanceEntry.all_objects.filter(tenant=request.tenant,
                                                pk=data.get("entry")).first() \
            if data.get("entry") else None
        if entry is None:
            raise Http404
        try:
            category = None
            if data.get("category"):
                category = FinanceCategory.all_objects.filter(
                    tenant=request.tenant, pk=data["category"]).first()
                if category is None:
                    raise services.PersonalError("That category is not in this practice.",
                                                 status=404)
            entry = services.sort_entry(
                entry, actor=request.user, side=data.get("side"), category=category,
                personal_category=self.category(data.get("personal_category")),
                remember=data.get("remember") or None)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response({"id": str(entry.pk), "side": entry.side, "kind": entry.kind})
