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
    from apps.personal import reconcile

    last = row.reconciliations.filter(state="finished").order_by("-statement_on").first()
    return {"id": str(row.pk), "name": row.name, "kind": row.kind,
            "kind_label": row.get_kind_display(), "last4": row.last4,
            "opening_balance_cents": row.opening_balance_cents,
            "opening_on": row.opening_on.isoformat(), "closed": row.closed_at is not None,
            "side": "personal", "in_books": False,
            "balance_cents": reconcile.balance(row),
            "reconciled_through": last.statement_on.isoformat() if last else None}


def represent_mixed(row) -> dict:
    """One of the practice's accounts marked Mixed: listed on the personal
    side too, because its personal lines are the owner's."""
    return {"id": str(row.pk), "name": row.name, "kind": row.kind,
            "kind_label": row.get_kind_display(), "last4": row.last4,
            "closed": row.closed_at is not None, "side": "mixed", "in_books": True}


def represent_line(row) -> dict:
    entry, paid = row.finance_entry, row.paid_entry
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
            "to_sort": row.category_id is None,
            # Decision 3: the practice's, paid from this personal account.
            "paid_for": ({"entry": str(paid.pk), "category": paid.category.name
                          if paid.category_id else ""} if paid is not None else None),
            # Decision 7: one side of a move between the household's accounts.
            "transfer": row.transfer_pair_id is not None}


def represent_waiting(entry) -> dict:
    """A Mixed account's line no rule placed: it waits for a side."""
    return {"id": str(entry.pk), "kind": "entry", "on_date": entry.on_date.isoformat(),
            "amount_cents": entry.amount_cents, "direction": entry.direction,
            "description": entry.description, "category": None,
            "account": {"id": str(entry.account_id), "name": entry.account.name},
            "from_books": True, "source": "books", "to_sort": True, "paid_for": None,
            "transfer": False}


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

    def business_category(self, pk):
        if not pk:
            return None
        found = FinanceCategory.all_objects.filter(tenant=self.request.tenant, pk=pk).first()
        if found is None:
            raise services.PersonalError("That category is not in this practice.", status=404)
        return found

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
                .select_related("category", "account", "finance_entry__account",
                                "paid_entry__category"))
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
                if row.paid_entry_id:
                    raise services.PersonalError(
                        "That line is the practice's, paid personally. Sort it to the "
                        "personal side to give it a personal category.", status=409)
                row.category = self.category(request.data.get("category"))
                row.save(update_fields=["category", "updated_at"])
                if request.data.get("remember") and row.category is not None:
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
                                               removed_at__isnull=True,
                                               paid_entry__isnull=True)
            if rows.count() != len(set(ids)):
                raise services.PersonalError("One of those lines is not yours, or was removed.",
                                             status=404)
            count = rows.update(category=category, updated_at=timezone.now())
        except (services.PersonalError, books.FinanceError, ValueError) as exc:
            return self.refusal(exc)
        return Response({"updated": count})


class SortView(PersonalView):
    """POST /api/personal/sort {entry | line, side, category?,
    personal_category?, remember?} — a line put on a side (decisions 2 and 3):
    `entry`, a line of one of the practice's accounts; `line`, a line of one of
    the household's own, which on the business side is paid personally."""

    def post(self, request):
        data = request.data
        try:
            category = self.business_category(data.get("category"))
            personal = self.category(data.get("personal_category"))
            if data.get("line"):
                line = PersonalLine.objects.filter(ledger=self.ledger, pk=data["line"],
                                                   removed_at__isnull=True).first()
                if line is None:
                    raise Http404
                if line.finance_entry_id is not None:
                    entry = services.sort_entry(
                        line.finance_entry, actor=request.user, side=data.get("side"),
                        category=category, personal_category=personal,
                        remember=data.get("remember") or None)
                    return Response({"id": str(entry.pk), "side": entry.side,
                                     "kind": entry.kind})
                line = services.sort_line(
                    line, tenant=request.tenant, actor=request.user, side=data.get("side"),
                    category=category, personal_category=personal,
                    remember=data.get("remember") or None)
                return Response(represent_line(line))
            entry = FinanceEntry.all_objects.filter(tenant=request.tenant,
                                                    pk=data.get("entry")).first() \
                if data.get("entry") else None
            if entry is None:
                raise Http404
            entry = services.sort_entry(
                entry, actor=request.user, side=data.get("side"), category=category,
                personal_category=personal, remember=data.get("remember") or None)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response({"id": str(entry.pk), "side": entry.side, "kind": entry.kind})


class SortWithClaudeView(PersonalView):
    """GET/POST /api/personal/sort-with-claude (decision 6). GET is the
    price, and says nothing to Claude; POST asks, and returns proposals the
    owner accepts through /api/personal/sort."""

    def get(self, request):
        from apps.personal import sort_ai

        return Response(sort_ai.status(self.ledger, request.tenant))

    def post(self, request):
        from apps.personal import sort_ai

        try:
            return Response(sort_ai.propose(self.ledger, request.tenant))
        except services.PersonalError as exc:
            return self.refusal(exc)


# --------------------------------------------- importing a personal account

def represent_import_row(row) -> dict:
    matched = row.matched_line
    return {
        "id": str(row.pk), "row_number": row.row_number,
        "on_date": row.on_date.isoformat() if row.on_date else None,
        "amount_cents": row.amount_cents, "direction": row.direction,
        "description": row.description, "outcome": row.outcome,
        "outcome_label": row.get_outcome_display(), "side": row.side,
        "category": ({"id": str(row.category_id), "name": row.category.name}
                     if row.category_id else None),
        "business_category": ({"id": str(row.business_category_id),
                               "name": row.business_category.name}
                              if row.business_category_id else None),
        "split_business_cents": row.split_business_cents,
        "matched": ({"id": str(matched.pk), "on_date": matched.on_date.isoformat(),
                     "description": matched.description,
                     "account": (matched.account.name if matched.account_id
                                 else "a Mixed account")} if matched else None),
        "rule": ({"id": str(row.rule_id), "contains": row.rule.contains}
                 if row.rule_id else None),
        "error": row.error_text, "raw": row.raw if row.outcome == "error" else None,
    }


def represent_import(batch, *, rows=False) -> dict:
    from apps.personal import imports

    out = {"id": str(batch.pk), "account": {"id": str(batch.account_id),
                                            "name": batch.account.name},
           "filename": batch.filename, "status": batch.status,
           "status_label": batch.get_status_display(), "counts": batch.counts,
           "created_at": batch.created_at.isoformat(),
           "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
           "source": batch.source,
           "statement": ({
               "period_start": batch.period_start.isoformat() if batch.period_start
               else None,
               "period_end": batch.period_end.isoformat() if batch.period_end else None,
               "opening_balance_cents": batch.opening_balance_cents,
               "closing_balance_cents": batch.last_balance_cents,
               "adds_up": imports.adds_up(batch),
               "cost_usd": str(batch.cost_usd) if batch.cost_usd is not None else None,
           } if batch.source == "pdf" else None)}
    if rows:
        from apps.personal.models import PersonalImportRow

        out["rows"] = [represent_import_row(row) for row in PersonalImportRow.objects.filter(
            batch=batch).select_related("category", "business_category", "rule",
                                        "matched_line__account")]
    return out


class ImportView(PersonalView):
    def batch(self, pk):
        from apps.personal.models import PersonalImport

        found = PersonalImport.objects.filter(ledger=self.ledger, pk=pk) \
            .select_related("account").first()
        if found is None:
            raise Http404
        return found

    def account(self, pk):
        found = PersonalAccount.objects.filter(ledger=self.ledger, pk=pk).first() \
            if pk else None
        if found is None:
            raise services.PersonalError("Choose one of your personal accounts.", status=404)
        return found


class ImportListView(ImportView):
    """GET /api/personal/imports — this ledger's imports, newest first."""

    def get(self, request):
        from apps.personal.models import PersonalImport

        return Response([represent_import(batch) for batch in PersonalImport.objects.filter(
            ledger=self.ledger).select_related("account")[:50]])


class ImportDetectView(ImportView):
    """POST /api/personal/imports/detect {file, account}: the file's columns
    and a first guess at the mapping, or the account's saved one. Writes
    nothing; a PDF is priced, not read."""

    def post(self, request):
        from apps.finance import importer, statement_pdf

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose the file your bank gave you."}, status=400)
        try:
            account = self.account(request.data.get("account"))
            content = upload.read()
            if content and statement_pdf.is_pdf(content, upload.name):
                found = statement_pdf.inspect(content)
                return Response({
                    "kind": statement_pdf.KIND, "fixed": True, "header": [], "sample": [],
                    "lines": 0, "mapping": statement_pdf.MAPPING, "from_saved": False,
                    "date_formats": [], **statement_pdf.status(request.tenant,
                                                               found["pages"])})
            parsed = importer.parse(content, upload.name)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        header, rows = parsed["header"], parsed["rows"]
        saved = account.import_mapping if parsed["mapping"] is None else None
        usable = saved if saved and all(
            not saved.get(key) or saved[key] in header
            for key in ("date", "description", "amount", "debit", "credit")) else None
        return Response({
            "header": header, "sample": rows[:5], "lines": len(rows), "kind": parsed["kind"],
            "fixed": parsed["mapping"] is not None,
            "mapping": parsed["mapping"] or usable or importer.suggest(header, rows),
            "from_saved": usable is not None,
            "date_formats": [{"value": fmt, "label": label}
                             for fmt, label in importer.DATE_FORMATS]})


class ImportDryRunView(ImportView):
    """POST /api/personal/imports/dry-run {file, account, mapping}."""

    def post(self, request):
        import json

        from apps.personal import imports

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose the file your bank gave you."}, status=400)
        mapping = request.data.get("mapping")
        try:
            if isinstance(mapping, str):
                try:
                    mapping = json.loads(mapping)
                except ValueError:
                    raise services.PersonalError("mapping could not be read.") from None
            batch = imports.dry_run(request.tenant, ledger=self.ledger,
                                    account=self.account(request.data.get("account")),
                                    filename=upload.name, file_bytes=upload.read(),
                                    mapping=mapping)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_import(batch, rows=True), status=201)


class ImportDetailView(ImportView):
    """GET /api/personal/imports/<id> — with its rows."""

    def get(self, request, pk):
        return Response(represent_import(self.batch(pk), rows=True))


class ImportRowView(ImportView):
    """POST /api/personal/imports/<id>/rows/<row> {decision, side?, category?,
    business_category?, split_business_cents?, remember?}."""

    def post(self, request, pk, row_id):
        from apps.personal import imports
        from apps.personal.models import PersonalImportRow

        batch = self.batch(pk)
        row = PersonalImportRow.objects.filter(batch=batch, pk=row_id).first()
        if row is None:
            raise Http404
        data = request.data
        try:
            split = data.get("split_business_cents")
            imports.decide(
                row, tenant=request.tenant, actor=request.user,
                decision=data.get("decision"), side=data.get("side"),
                category=self.category(data.get("category")),
                business_category=self.business_category(data.get("business_category")),
                split_business_cents=books._cents(split, "The business part")
                if split not in (None, "") else None,
                remember=data.get("remember") or None)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_import(self.batch(pk), rows=True))


class ImportCommitView(ImportView):
    def post(self, request, pk):
        from apps.personal import imports

        try:
            batch = imports.commit(self.batch(pk), tenant=request.tenant, actor=request.user)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_import(self.batch(batch.pk)))


class ImportRollbackView(ImportView):
    def post(self, request, pk):
        from apps.personal import imports

        try:
            result = imports.rollback(self.batch(pk), actor=request.user)
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response({**represent_import(self.batch(pk)), "rolled_back": result})


# ----------------------------------------- reconciling a personal account

def represent_reconciliation(rec, *, lines=False) -> dict:
    from apps.personal import reconcile

    rows = reconcile.lines(rec)
    out = {"id": str(rec.pk), "account": {"id": str(rec.account_id), "name": rec.account.name,
                                          "kind": rec.account.kind},
           "statement_on": rec.statement_on.isoformat(),
           "statement_balance_cents": rec.statement_balance_cents, "state": rec.state,
           "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
           **reconcile.totals(rec, rows)}
    if lines:
        out["lines"] = [{"id": str(line.pk), "on_date": line.on_date.isoformat(),
                         "amount_cents": line.amount_cents, "direction": line.direction,
                         "description": line.description,
                         "cleared": line.cleared_in_id == rec.pk} for line in rows]
    return out


class ReconciliationListView(ImportView):
    """GET/POST /api/personal/accounts/<id>/reconciliations (decision 8)."""

    def get(self, request, pk):
        account = PersonalAccount.objects.filter(ledger=self.ledger, pk=pk).first()
        if account is None:
            raise Http404
        return Response([represent_reconciliation(rec)
                         for rec in account.reconciliations.order_by("-statement_on")])

    def post(self, request, pk):
        from apps.personal import reconcile

        account = PersonalAccount.objects.filter(ledger=self.ledger, pk=pk).first()
        if account is None:
            raise Http404
        try:
            rec = reconcile.start(
                account, statement_on=books._a_date(request.data.get("statement_on"),
                                                    "The statement's ending date"),
                statement_balance_cents=books._cents(
                    request.data.get("statement_balance_cents"),
                    "The statement's ending balance", signed=True))
        except (services.PersonalError, books.FinanceError) as exc:
            return self.refusal(exc)
        return Response(represent_reconciliation(rec, lines=True), status=201)


class ReconciliationView(PersonalView):
    """GET/DELETE /api/personal/reconciliations/<id>; POST
    /api/personal/reconciliations/<id>/<tick|finish|reopen>."""

    def rec(self, pk):
        from apps.personal.models import PersonalReconciliation

        found = PersonalReconciliation.objects.filter(ledger=self.ledger, pk=pk) \
            .select_related("account").first()
        if found is None:
            raise Http404
        return found

    def get(self, request, pk, step=None):
        return Response(represent_reconciliation(self.rec(pk), lines=True))

    def delete(self, request, pk, step=None):
        from apps.personal import reconcile

        try:
            reconcile.discard(self.rec(pk))
        except services.PersonalError as exc:
            return self.refusal(exc)
        return Response(status=204)

    def post(self, request, pk, step=None):
        from apps.personal import reconcile

        rec = self.rec(pk)
        try:
            if step == "tick":
                ids = request.data.get("lines")
                if not isinstance(ids, list):
                    raise services.PersonalError("lines is a list of lines.")
                reconcile.tick(rec, line_ids=ids, cleared=bool(request.data.get("cleared",
                                                                                 True)))
            elif step == "finish":
                reconcile.finish(rec)
            elif step == "reopen":
                reconcile.reopen(rec)
            else:
                raise Http404
        except (services.PersonalError, ValueError) as exc:
            return self.refusal(exc)
        return Response(represent_reconciliation(self.rec(pk), lines=True))
