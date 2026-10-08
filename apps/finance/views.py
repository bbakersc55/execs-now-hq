"""The books over the API (matrix 13.1, 13.6–13.10): the practice owner's.

Every route here answers one role. An associate and an assistant get 403; a
client user gets 404; another practice gets 404 through the tenant manager.
"""

from __future__ import annotations

from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Company
from apps.finance import reports, services
from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceEntry,
)
from apps.tenancy.models import CLIENT_ROLES, AuditEvent, Role

OWNER_ONLY = "The books are the practice owner's."
K = FinanceEntry.Kind
D = FinanceEntry.Direction


def represent_account(row) -> dict:
    return {"id": str(row.pk), "name": row.name, "kind": row.kind,
            "kind_label": row.get_kind_display(), "last4": row.last4,
            "opening_balance_cents": row.opening_balance_cents,
            "opening_on": row.opening_on.isoformat(), "closed": row.closed_at is not None}


def represent_category(row, used=None) -> dict:
    return {"id": str(row.pk), "name": row.name, "type": row.type,
            "type_label": row.get_type_display(), "cpa_code": row.cpa_code,
            "position": row.position, "archived": row.archived_at is not None,
            "system": bool(row.system_code),
            **({"used": row.pk in used} if used is not None else {})}


def represent_entry(entry) -> dict:
    payment = entry.client_payment if entry.client_payment_id else None
    return {
        "id": str(entry.pk), "kind": entry.kind, "kind_label": entry.get_kind_display(),
        "direction": entry.direction, "on_date": entry.on_date.isoformat(),
        "amount_cents": entry.amount_cents,
        "category": ({"id": str(entry.category_id), "name": entry.category.name}
                     if entry.category_id else None),
        "account": ({"id": str(entry.account_id), "name": entry.account.name}
                    if entry.account_id else None),
        "to_account": ({"id": str(entry.to_account_id), "name": entry.to_account.name}
                       if entry.to_account_id else None),
        "description": entry.description, "counterparty": entry.counterparty,
        "client_company": ({"id": str(entry.client_company_id),
                            "name": entry.client_company.name}
                           if entry.client_company_id else None),
        "reference": entry.reference, "source": entry.source,
        "source_label": entry.get_source_display(),
        "invoice": ({"id": str(payment.invoice_id), "number": payment.invoice.number}
                    if payment else None),
        "removed": entry.removed_at is not None, "remove_reason": entry.remove_reason,
    }


class FinanceViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        role = crm_perms.role_of(request)
        if role in CLIENT_ROLES or role is None:
            raise Http404
        if role != Role.FF:
            self.permission_denied(request, message=OWNER_ONLY)

    @staticmethod
    def _refusal(exc):
        return Response({"detail": str(exc)}, status=exc.status)

    def _one(self, model, pk, what):
        """A row of this practice, or a refusal that names what was asked for."""
        row = model.objects.filter(pk=pk).first() if pk else None
        if row is None:
            raise services.FinanceError(f"That {what} is not in this practice.", status=404)
        return row

    def _date(self, name, default):
        value = self.request.query_params.get(name)
        return services._a_date(value, name) if value else default


class EntryViewSet(FinanceViewSet):

    def entries(self):
        return FinanceEntry.objects.select_related(
            "category", "account", "to_account", "client_company", "client_payment__invoice")

    def _filtered(self, request):
        qs = self.entries()
        params = request.query_params
        if params.get("removed") != "1":
            qs = qs.filter(removed_at__isnull=True)
        if params.get("from"):
            qs = qs.filter(on_date__gte=services._a_date(params["from"], "from"))
        if params.get("to"):
            qs = qs.filter(on_date__lte=services._a_date(params["to"], "to"))
        if params.get("kind"):
            qs = qs.filter(kind=params["kind"])
        if params.get("category") == "none":
            qs = qs.filter(category__isnull=True, kind__in=FinanceEntry.EARNED)
        elif params.get("category"):
            qs = qs.filter(category_id=params["category"])
        if params.get("account") == "none":
            qs = qs.filter(account__isnull=True)
        elif params.get("account"):
            qs = qs.filter(Q(account_id=params["account"])
                           | Q(to_account_id=params["account"]))
        if params.get("company"):
            qs = qs.filter(client_company_id=params["company"])
        if params.get("source"):
            qs = qs.filter(source=params["source"])
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(description__icontains=q) | Q(counterparty__icontains=q)
                           | Q(reference__icontains=q))
        return qs.order_by("-on_date", "-created_at")

    def list(self, request):
        try:
            qs = self._filtered(request)
        except services.FinanceError as exc:
            return self._refusal(exc)
        services.settings_for(request.tenant)
        counted = qs.filter(removed_at__isnull=True)
        sums = counted.aggregate(
            income=Sum("amount_cents", filter=Q(kind=K.INCOME)),
            expenses=Sum("amount_cents", filter=Q(kind=K.EXPENSE)))
        income, expenses = sums["income"] or 0, sums["expenses"] or 0
        return Response({
            "entries": [represent_entry(entry) for entry in qs[:500]],
            "count": qs.count(),
            "totals": {"income_cents": income, "expenses_cents": expenses,
                       "net_cents": income - expenses},
        })

    def _changes(self, data) -> dict:
        changes = {}
        for field in ("kind", "direction", "on_date", "amount_cents", "description",
                      "counterparty", "reference"):
            if field in data:
                changes[field] = data[field]
        for field, model, what in (("category", FinanceCategory, "category"),
                                   ("account", FinanceAccount, "account"),
                                   ("to_account", FinanceAccount, "account"),
                                   ("client_company", Company, "company")):
            if field in data:
                changes[field] = self._one(model, data[field], what) if data[field] else None
        return changes

    def create(self, request):
        try:
            entry = services.create_entry(request.tenant, actor=request.user,
                                          **self._changes(request.data))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_entry(self.entries().get(pk=entry.pk)), status=201)

    def partial_update(self, request, pk=None):
        entry = self.entries().filter(pk=pk).first()
        if entry is None:
            raise Http404
        try:
            services.update_entry(entry, actor=request.user, **self._changes(request.data))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_entry(self.entries().get(pk=pk)))

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        entry = self.entries().filter(pk=pk).first()
        if entry is None:
            raise Http404
        try:
            services.remove_entry(entry, actor=request.user,
                                  reason=request.data.get("reason"))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_entry(self.entries().get(pk=pk)))

    @action(detail=False, methods=["post"])
    def recategorize(self, request):
        ids = request.data.get("entries")
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "entries is a list of entries."}, status=400)
        try:
            entries = list(FinanceEntry.objects.filter(pk__in=ids))
            if len(entries) != len(set(map(str, ids))):
                raise services.FinanceError("One of those entries is not in this practice.",
                                            status=404)
            count = services.recategorize(
                request.tenant, actor=request.user, entries=entries,
                category=self._one(FinanceCategory, request.data.get("category"),
                                   "category"))
        except (services.FinanceError, ValueError) as exc:
            if isinstance(exc, ValueError):
                return Response({"detail": "entries is a list of entries."}, status=400)
            return self._refusal(exc)
        return Response({"changed": count})

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        entry = self.entries().filter(pk=pk).first()
        if entry is None:
            raise Http404
        events = (AuditEvent.objects.filter(target_type="finance_entry", target_id=entry.pk)
                  .select_related("actor").order_by("created_at"))
        return Response([{
            "at": event.created_at.isoformat(), "what": event.verb.removeprefix("finance."),
            "by": ((event.actor.full_name or event.actor.email) if event.actor
                   else "From the invoice"),
            "before": event.payload.get("before"), "after": event.payload.get("after"),
            "reason": event.payload.get("reason", ""),
        } for event in events])


class AccountViewSet(FinanceViewSet):

    def list(self, request):
        return Response([represent_account(row) for row in FinanceAccount.objects.all()])

    def _save(self, request, account=None):
        data = request.data
        fields = {name: data[name] for name in ("name", "kind", "last4",
                                                "opening_balance_cents", "opening_on")
                  if name in data}
        try:
            row = services.save_account(request.tenant, actor=request.user, account=account,
                                        **fields)
            if "closed" in data and account is not None:
                row = services.set_account_closed(row, actor=request.user,
                                                  closed=bool(data["closed"]))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_account(row), status=201 if account is None else 200)

    def create(self, request):
        return self._save(request)

    def partial_update(self, request, pk=None):
        account = FinanceAccount.objects.filter(pk=pk).first()
        if account is None:
            raise Http404
        return self._save(request, account)


class CategoryViewSet(FinanceViewSet):

    def list(self, request):
        services.ensure_chart(request.tenant)
        used = set(FinanceEntry.objects.exclude(category=None).values_list(
            "category_id", flat=True).distinct())
        return Response([represent_category(row, used)
                         for row in FinanceCategory.objects.order_by("type", "position",
                                                                     "name")])

    def _save(self, request, category=None):
        data = request.data
        fields = {name: data[name] for name in ("name", "type", "cpa_code") if name in data}
        try:
            row = services.save_category(request.tenant, actor=request.user,
                                         category=category, **fields)
            if "archived" in data and category is not None:
                row = services.set_category_archived(row, actor=request.user,
                                                     archived=bool(data["archived"]))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_category(row), status=201 if category is None else 200)

    def create(self, request):
        return self._save(request)

    def partial_update(self, request, pk=None):
        category = FinanceCategory.objects.filter(pk=pk).first()
        if category is None:
            raise Http404
        return self._save(request, category)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        try:
            services.reorder_categories(request.tenant, actor=request.user,
                                        type=request.data.get("type"),
                                        ids=request.data.get("ids"))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self.list(request)


class FinanceSettingsView(FinanceViewSet):

    @staticmethod
    def _represent(row) -> dict:
        return {"locked_through": row.locked_through.isoformat() if row.locked_through
                else None,
                "invoice_income_category": str(row.invoice_income_category_id or "")}

    def list(self, request):
        return Response(self._represent(services.settings_for(request.tenant)))

    def create(self, request):
        data = request.data
        fields = {}
        try:
            if "locked_through" in data:
                fields["locked_through"] = data["locked_through"] or None
            if "invoice_income_category" in data:
                fields["invoice_income_category"] = self._one(
                    FinanceCategory, data["invoice_income_category"], "category")
            row = services.update_settings(request.tenant, actor=request.user, **fields)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(self._represent(row))


class ReportView(FinanceViewSet):

    def _csv(self, request, text, filename, verb, **payload):
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb=f"finance.{verb}",
            target_type="finance_export", payload=payload)
        response = HttpResponse(text, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=["get"])
    def pnl(self, request):
        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year") or today.year)
        except ValueError:
            return Response({"detail": "year is a year."}, status=400)
        if not 2000 <= year <= today.year + 1:
            return Response({"detail": "year is a year."}, status=400)
        report = reports.pnl(request.tenant, year=year,
                             by=request.query_params.get("by") or "month")
        if request.query_params.get("download") == "1":
            return self._csv(request, reports.pnl_csv(report),
                             f"profit-and-loss-{year}.csv", "pnl_downloaded", year=year,
                             by=report["by"])
        return Response(report)

    @action(detail=False, methods=["get"])
    def balance(self, request):
        try:
            as_of = self._date("as_of", timezone.localdate())
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(reports.balance(request.tenant, as_of=as_of))

    def _range(self):
        today = timezone.localdate()
        start = self._date("from", today.replace(month=1, day=1))
        end = self._date("to", today)
        if end < start:
            raise services.FinanceError("The last date cannot be before the first.")
        return start, end

    @action(detail=False, methods=["get"], url_path="export-entries")
    def export_entries(self, request):
        try:
            start, end = self._range()
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self._csv(request, reports.export_entries(request.tenant, start=start, end=end),
                         f"entries-{start}-to-{end}.csv", "cpa_export_downloaded",
                         file="entries", start=start.isoformat(), end=end.isoformat())

    @action(detail=False, methods=["get"], url_path="export-summary")
    def export_summary(self, request):
        try:
            start, end = self._range()
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self._csv(request, reports.export_summary(request.tenant, start=start, end=end),
                         f"summary-{start}-to-{end}.csv", "cpa_export_downloaded",
                         file="summary", start=start.isoformat(), end=end.isoformat())
