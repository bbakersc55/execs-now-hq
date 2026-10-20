"""Stop 4's routes (P6 M4 decisions 20–23), under /api/personal/, behind the
same door as the rest of the personal side (`views.OwnerOnly`): the practice
owner, in a practice with the module, and only their own ledger.

Every change answers with the page it changed, worked out again.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.response import Response

from apps.personal import cpa, paydays, taxes
from apps.personal.models import PersonalTaxItem
from apps.personal.services import PersonalError
from apps.personal.views import PersonalView


def _year(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        year = int(str(value))
    except ValueError:
        raise PersonalError("The year is a year, like 2026.") from None
    if not 2000 <= year <= 2100:
        raise PersonalError("The year is a year, like 2026.")
    return year


def _day(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PersonalError("The date is YYYY-MM-DD.") from None


class TaxesView(PersonalView):
    """GET /api/personal/taxes?year= — the estimate (decision 21).
    POST .../inputs {year, filing_status, …} — what is entered once a year.
    POST .../set-aside {year, percent_per_draw, saved_cents}.
    POST .../envelope {planned_cents} — the Tax envelope's monthly amount."""

    def year(self):
        raw = self.request.data.get("year") if self.request.method == "POST" else None
        return _year(raw or self.request.query_params.get("year"),
                     taxes.payment_year(timezone.localdate()))

    def payload(self, year):
        return taxes.estimate(self.ledger, self.request.tenant, year)

    def get(self, request, what=None):
        if what is not None:
            raise Http404
        try:
            return Response(self.payload(self.year()))
        except PersonalError as exc:
            return self.refusal(exc)

    def post(self, request, what=None):
        try:
            year = self.year()
            data = {k: v for k, v in request.data.items() if k != "year"}
            if what == "inputs":
                taxes.save_inputs(self.ledger, year=year, **data)
            elif what == "set-aside":
                taxes.save_set_aside(self.ledger, year=year,
                                     percent_per_draw=data.get("percent_per_draw"),
                                     saved_cents=data.get("saved_cents"),
                                     clear_percent=data.get("percent_per_draw") == "")
            elif what == "envelope":
                taxes.use_envelope(self.ledger, planned_cents=data.get("planned_cents"))
            else:
                raise Http404
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(self.payload(year))


class PayYourselfView(PersonalView):
    """GET /api/personal/pay-yourself — decision 20's sentence, in figures.
    POST {amount_cents} — set the business forecast's pay-yourself line."""

    def get(self, request):
        return Response(paydays.loop(self.ledger, request.tenant))

    def post(self, request):
        try:
            return Response(paydays.set_business_line(
                self.ledger, request.tenant, actor=request.user,
                amount_cents=request.data.get("amount_cents")))
        except PersonalError as exc:
            return self.refusal(exc)


class CpaView(PersonalView):
    """GET /api/personal/cpa?year= — both sections (decisions 22 and 23).
    GET .../pdf?year= — the one PDF with both."""

    def get(self, request, what=None):
        try:
            year = _year(request.query_params.get("year"), timezone.localdate().year)
        except PersonalError as exc:
            return self.refusal(exc)
        if what == "pdf":
            response = HttpResponse(cpa.render_pdf(self.ledger, request.tenant, year),
                                    content_type="application/pdf")
            response["Content-Disposition"] = (f'attachment; filename="for-your-cpa-{year}'
                                               '.pdf"')
            return response
        if what is not None:
            raise Http404
        return Response(cpa.both(self.ledger, request.tenant, year))


class CpaItemView(PersonalView):
    """POST /api/personal/cpa/items — a figure for the CPA (a non-cash
    donation naming its charity, an amount from a form); PATCH or DELETE
    one."""

    FIELDS = ("year", "tax_group", "description", "amount_cents", "on_date", "charity")

    def _item(self, pk):
        found = PersonalTaxItem.objects.filter(ledger=self.ledger, pk=pk,
                                               removed_at__isnull=True).first()
        if found is None:
            raise Http404
        return found

    def _answer(self, year):
        return Response(cpa.both(self.ledger, self.request.tenant, year))

    def post(self, request, pk=None):
        if pk is not None:
            raise Http404
        try:
            data = {k: request.data.get(k) for k in self.FIELDS}
            data["on_date"] = _day(data["on_date"])
            data["year"] = _year(data["year"], timezone.localdate().year)
            row = cpa.save_item(self.ledger, **data)
        except PersonalError as exc:
            return self.refusal(exc)
        return self._answer(row.year)

    def patch(self, request, pk):
        row = self._item(pk)
        try:
            data = {k: request.data.get(k, getattr(row, k)) for k in self.FIELDS}
            if "on_date" in request.data:
                data["on_date"] = _day(request.data["on_date"])
            row = cpa.save_item(self.ledger, item=row, **data)
        except PersonalError as exc:
            return self.refusal(exc)
        return self._answer(row.year)

    def delete(self, request, pk):
        row = self._item(pk)
        cpa.remove_item(row)
        return self._answer(row.year)
