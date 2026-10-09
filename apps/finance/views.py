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
from apps.crm.models import Company, Contact
from apps.finance import chart, reports, services
from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceCategoryChange, FinanceEntry,
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
            # P6 M1: the level above, where it has one; and where a combined
            # category went.
            "parent": str(row.parent_id) if row.parent_id else None,
            "merged_into": str(row.merged_into_id) if row.merged_into_id else None,
            "is_contractor": row.is_contractor,
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
        # Who it was paid to, where that is a 1099 payee.
        "payee_contact": str(entry.payee_contact_id or ""),
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

    def needs_bookkeeping(self, request) -> None:
        """What only a practice with the Bookkeeping module has (P6 M1 §7):
        to one without it, the route is not there."""
        from apps.tenancy import modules

        if not modules.has(request.tenant, modules.BOOKKEEPING):
            raise Http404


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
        elif params.get("category") and params.get("subs") == "1":
            # A category with its sub-categories: what a parent's figure on
            # the P&L is made of (P6 M1).
            qs = qs.filter(Q(category_id=params["category"])
                           | Q(category__parent_id=params["category"]))
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
            income=Sum(reports.SIGNED, filter=Q(kind=K.INCOME)),
            expenses=Sum(reports.SIGNED, filter=Q(kind=K.EXPENSE)))
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
                                   ("client_company", Company, "company"),
                                   ("payee_contact", Contact, "person")):
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

    def _category(self, pk):
        category = FinanceCategory.objects.filter(pk=pk).first() if pk else None
        if category is None:
            raise Http404
        return category

    def _save(self, request, category=None):
        data = request.data
        fields = {name: data[name] for name in ("name", "type", "cpa_code") if name in data}
        try:
            if "parent" in data:
                # Sub-categories are Bookkeeping's (P6 M1).
                self.needs_bookkeeping(request)
                fields["parent"] = self._one(FinanceCategory, data["parent"], "category") \
                    if data["parent"] else None
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
        return self._save(request, self._category(pk))

    def destroy(self, request, pk=None):
        """Remove a category nothing has used. One with entries is archived."""
        try:
            chart.delete_category(self._category(pk), actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(status=204)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        try:
            parent = self._one(FinanceCategory, request.data["parent"], "category") \
                if request.data.get("parent") else None
            services.reorder_categories(request.tenant, actor=request.user,
                                        type=request.data.get("type"),
                                        ids=request.data.get("ids"), parent=parent)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self.list(request)

    # ------------------------------------ combine, split, the starting chart

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Combine this category into another. `preview: true` only counts."""
        self.needs_bookkeeping(request)
        source = self._category(pk)
        try:
            target = self._one(FinanceCategory, request.data.get("into"), "category")
            if request.data.get("preview"):
                return Response(chart.merge_preview(source, target))
            chart.merge(source, target, actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self.list(request)

    @action(detail=True, methods=["post"])
    def split(self, request, pk=None):
        """Move some of this category's entries to a new category (`name`,
        `as`: "sub" or "beside") or to one that exists (`to`), chosen by
        `contains` or by `entries`. `preview: true` only counts."""
        self.needs_bookkeeping(request)
        source = self._category(pk)
        data = request.data
        try:
            choice = dict(
                name=data.get("name"), as_sub=data.get("as", "sub") != "beside",
                to=self._one(FinanceCategory, data["to"], "category") if data.get("to")
                else None,
                contains=data.get("contains") or "", entry_ids=data.get("entries") or None)
            if data.get("preview"):
                return Response(chart.split_preview(source, **choice))
            chart.split(source, actor=request.user, **choice)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return self.list(request)

    @action(detail=False, methods=["get", "post"], url_path="starting-chart")
    def starting_chart(self, request):
        """GET: what "Add the starting chart" would add. POST: add it. It
        never changes or removes what the practice already has."""
        self.needs_bookkeeping(request)
        services.ensure_chart(request.tenant)
        if request.method == "GET":
            return Response(chart.starting_chart_plan(request.tenant))
        plan = chart.add_starting_chart(request.tenant, actor=request.user)
        return Response({**plan, "added": len(plan["add"])})

    @action(detail=False, methods=["get"])
    def changes(self, request):
        """Every combine and split, newest first."""
        self.needs_bookkeeping(request)
        rows = FinanceCategoryChange.objects.select_related(
            "from_category", "to_category", "by")[:100]
        return Response([chart.represent_change(row) for row in rows])


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


# ------------------------------------------------- the import, rules and 1099

def _json(request, name):
    import json

    value = request.data.get(name)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            raise services.FinanceError(f"{name} could not be read.") from None
    return value


def represent_row(row) -> dict:
    matched = row.matched_entry
    return {
        "id": str(row.pk), "row_number": row.row_number,
        "on_date": row.on_date.isoformat() if row.on_date else None,
        "amount_cents": row.amount_cents, "direction": row.direction,
        "description": row.description, "outcome": row.outcome,
        "outcome_label": row.get_outcome_display(),
        "category": ({"id": str(row.category_id), "name": row.category.name}
                     if row.category_id else None),
        "other_account": ({"id": str(row.other_account_id), "name": row.other_account.name}
                          if row.other_account_id else None),
        "payee_contact": str(row.payee_contact_id or ""),
        # Both sides of a proposed match, so it can be judged before it is accepted.
        "matched": ({"id": str(matched.pk), "on_date": matched.on_date.isoformat(),
                     "description": matched.description,
                     "counterparty": matched.counterparty,
                     "amount_cents": row.amount_cents} if matched else None),
        "rule": ({"id": str(row.rule_id), "contains": row.rule.contains}
                 if row.rule_id else None),
        "error": row.error_text,
        "raw": row.raw if row.outcome == "error" else None,
    }


def represent_batch(batch, *, rows=False) -> dict:
    from apps.finance.models import FinanceImportRow

    out = {
        "id": str(batch.pk), "account": {"id": str(batch.account_id),
                                         "name": batch.account.name},
        "filename": batch.filename, "status": batch.status,
        "status_label": batch.get_status_display(), "counts": batch.counts,
        "created_at": batch.created_at.isoformat(),
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "last_balance_cents": batch.last_balance_cents,
        "last_balance_on": batch.last_balance_on.isoformat() if batch.last_balance_on
        else None,
    }
    if rows:
        out["rows"] = [represent_row(row) for row in FinanceImportRow.objects.filter(
            batch=batch).select_related("category", "other_account", "matched_entry",
                                        "rule").order_by("row_number")]
    return out


class ImportViewSet(FinanceViewSet):
    """Matrix 13.8. Its own tables, so no bank line is ever where an assistant
    reads the contact import."""

    def _batch(self, pk):
        from apps.finance.models import FinanceImportBatch

        batch = FinanceImportBatch.objects.select_related("account").filter(pk=pk).first()
        if batch is None:
            raise Http404
        return batch

    def list(self, request):
        from apps.finance.models import FinanceImportBatch

        return Response([represent_batch(batch) for batch in
                         FinanceImportBatch.objects.select_related("account")
                         .order_by("-created_at")[:50]])

    def retrieve(self, request, pk=None):
        return Response(represent_batch(self._batch(pk), rows=True))

    @action(detail=False, methods=["post"])
    def detect(self, request):
        """Step 1: the file's columns, a few lines, and a first guess at the
        mapping (or the one saved for this account). Writes nothing."""
        from apps.finance import importer

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose the file your bank gave you."}, status=400)
        try:
            account = self._one(FinanceAccount, request.data.get("account"), "account")
            header, rows = importer.read(upload.read())
            saved = importer.profile_for(account)
            usable = saved if saved and all(
                not saved.get(key) or saved[key] in header
                for key in ("date", "description", "amount", "debit", "credit")) else None
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response({
            "header": header, "sample": rows[:5], "lines": len(rows),
            "mapping": usable or importer.suggest(header, rows),
            "from_saved": usable is not None,
            "date_formats": [{"value": fmt, "label": label}
                             for fmt, label in importer.DATE_FORMATS],
        })

    @action(detail=False, methods=["post"], url_path="dry-run")
    def dry_run(self, request):
        from apps.finance import importer

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose the file your bank gave you."}, status=400)
        try:
            account = self._one(FinanceAccount, request.data.get("account"), "account")
            batch = importer.dry_run(
                request.tenant, account=account, filename=upload.name,
                file_bytes=upload.read(), mapping=_json(request, "mapping"),
                actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_batch(batch, rows=True), status=201)

    @action(detail=True, methods=["post"], url_path=r"rows/(?P<row_id>[0-9a-f-]+)")
    def row(self, request, pk=None, row_id=None):
        from apps.crm.models import Contact
        from apps.finance import importer
        from apps.finance.models import FinanceImportRow

        batch = self._batch(pk)
        row = FinanceImportRow.objects.filter(batch=batch, pk=row_id).first()
        if row is None:
            raise Http404
        data = request.data
        try:
            fields = {}
            if "payee_contact" in data:
                fields["payee_contact"] = self._one(Contact, data["payee_contact"], "person") \
                    if data["payee_contact"] else None
            importer.decide(
                row, decision=data.get("decision"), actor=request.user,
                category=self._one(FinanceCategory, data["category"], "category")
                if data.get("category") else None,
                other_account=self._one(FinanceAccount, data["other_account"], "account")
                if data.get("other_account") else None,
                remember=data.get("remember") or None, **fields)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_batch(self._batch(pk), rows=True))

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        from apps.finance import importer

        try:
            batch = importer.commit(self._batch(pk), actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(represent_batch(self._batch(batch.pk)))

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        from apps.finance import importer

        try:
            result = importer.rollback(self._batch(pk), actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response({**represent_batch(self._batch(pk)), "rolled_back": result})


class RuleViewSet(FinanceViewSet):

    @staticmethod
    def _represent(rule) -> dict:
        return {"id": str(rule.pk), "contains": rule.contains, "treat_as": rule.treat_as,
                "category": ({"id": str(rule.category_id), "name": rule.category.name}
                             if rule.category_id else None),
                "other_account": ({"id": str(rule.other_account_id),
                                   "name": rule.other_account.name}
                                  if rule.other_account_id else None),
                "account": ({"id": str(rule.account_id), "name": rule.account.name}
                            if rule.account_id else None),
                "is_active": rule.is_active}

    def _rules(self):
        from apps.finance.models import FinanceRule

        return FinanceRule.objects.select_related("category", "other_account", "account")

    def list(self, request):
        return Response([self._represent(rule) for rule in self._rules()])

    def _save(self, request, rule=None):
        from apps.finance import rules

        data = request.data
        fields = {name: data[name] for name in ("contains", "treat_as", "is_active")
                  if name in data}
        try:
            for name, model, what in (("category", FinanceCategory, "category"),
                                      ("other_account", FinanceAccount, "account"),
                                      ("account", FinanceAccount, "account")):
                if name in data:
                    fields[name] = self._one(model, data[name], what) if data[name] else None
            saved = rules.save_rule(request.tenant, actor=request.user, rule=rule, **fields)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(self._represent(self._rules().get(pk=saved.pk)),
                        status=201 if rule is None else 200)

    def create(self, request):
        return self._save(request)

    def partial_update(self, request, pk=None):
        rule = self._rules().filter(pk=pk).first()
        if rule is None:
            raise Http404
        return self._save(request, rule)

    def destroy(self, request, pk=None):
        from apps.finance import rules

        rule = self._rules().filter(pk=pk).first()
        if rule is None:
            raise Http404
        rules.delete_rule(rule, actor=request.user)
        return Response(status=204)


class PayeeView(FinanceViewSet):
    """1099 tracking: who is a payee, what each was paid in a year, and who is
    over the threshold. The flag is set here and shown on no contact payload."""

    def _report(self, request):
        from apps.finance import payees

        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year") or today.year)
            threshold = request.query_params.get("threshold_cents")
            threshold = int(threshold) if threshold not in (None, "") else None
        except ValueError:
            raise services.FinanceError("year and threshold_cents are whole numbers.") \
                from None
        if not 2000 <= year <= today.year + 1 or (threshold is not None and threshold < 0):
            raise services.FinanceError("That is not a year or a threshold.")
        return payees.report(request.tenant, year=year, threshold_cents=threshold)

    def list(self, request):
        try:
            return Response(self._report(request))
        except services.FinanceError as exc:
            return self._refusal(exc)

    def create(self, request):
        """Flag or unflag a contact as a 1099 payee."""
        from apps.crm.models import Contact

        flag = request.data.get("is_payee")
        if not isinstance(flag, bool):
            return Response({"detail": "is_payee is true or false."}, status=400)
        try:
            contact = self._one(Contact, request.data.get("contact"), "person")
        except services.FinanceError as exc:
            return self._refusal(exc)
        if contact.is_1099_payee != flag:
            contact.is_1099_payee = flag
            contact.save(update_fields=["is_1099_payee", "updated_at"])
            services.audit(request.tenant, "payee_flagged" if flag else "payee_unflagged",
                           request.user, contact)
        return self.list(request)

    @action(detail=False, methods=["get"])
    def export(self, request):
        from apps.finance import payees

        try:
            data = self._report(request)
        except services.FinanceError as exc:
            return self._refusal(exc)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="finance.payees_downloaded",
            target_type="finance_export", payload={"year": data["year"]})
        response = HttpResponse(payees.export(data), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="1099-payees-{data["year"]}.csv"')
        return response
