"""Stop 3's routes (P6 M4 decisions 15–19), under /api/personal/, behind the
same door as the rest of the personal side (`views.OwnerOnly`): the practice
owner, in a practice with the module, and only their own ledger.

Every change answers with the page it changed, worked out again, so the
screen never holds a figure the server did not give it.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response

from apps.personal import debts, forecast, household, networth, retirement
from apps.personal.models import (
    PersonalAsset, PersonalDebt, PersonalForecastAdjustment, PersonalHolding, PersonalPlanned,
)
from apps.personal.services import PersonalError
from apps.personal.views import PersonalView


def _day(value, what="The date") -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PersonalError(f"{what} is YYYY-MM-DD.") from None


class WhoseView(PersonalView):
    """`?whose=<member id>` narrows a page to one person; none, the
    household."""

    def whose(self):
        pk = self.request.query_params.get("whose")
        return household.member(self.ledger, pk) if pk else "all"


# ----------------------------------------------------------------- forecast

class ForecastView(PersonalView):
    """GET /api/personal/forecast — the whole personal forecast (decision 15).
    POST .../what-if {off, on, amounts} — a look, nothing saved."""

    def get(self, request):
        return Response(forecast.build(self.ledger))

    def post(self, request):
        try:
            return Response(forecast.build(self.ledger, what_if=dict(request.data),
                                           snapshot=False))
        except PersonalError as exc:
            return self.refusal(exc)


class ForecastFloorView(PersonalView):
    def post(self, request):
        try:
            forecast.set_floor(self.ledger, request.data.get("floor_cents"))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger))


class ForecastPlannedView(PersonalView):
    """POST a planned line or a what-if; PATCH/DELETE one."""

    FIELDS = ("name", "direction", "amount_cents", "on_date", "repeat", "is_what_if")

    def _row(self, pk):
        row = PersonalPlanned.objects.filter(ledger=self.ledger, pk=pk,
                                             archived_at__isnull=True).first()
        if row is None:
            raise Http404
        return row

    def post(self, request, pk=None):
        try:
            forecast.save_planned(self.ledger, **{k: request.data[k] for k in self.FIELDS
                                                  if k in request.data})
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger), status=201)

    def patch(self, request, pk):
        try:
            forecast.save_planned(self.ledger, planned=self._row(pk),
                                  **{k: request.data[k] for k in self.FIELDS
                                     if k in request.data})
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger))

    def delete(self, request, pk):
        try:
            forecast.remove_planned(self._row(pk))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger))


class ForecastAdjustView(PersonalView):
    """POST {group, kind, amount_cents, from_date, source}; DELETE /<id> undoes."""

    def post(self, request, pk=None):
        data = request.data
        try:
            forecast.adjust(self.ledger, group=data.get("group"), kind=data.get("kind"),
                            amount_cents=data.get("amount_cents"),
                            from_date=data.get("from_date"),
                            source="review" if data.get("source") == "review" else "")
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger), status=201)

    def delete(self, request, pk):
        row = PersonalForecastAdjustment.objects.filter(ledger=self.ledger, pk=pk).first()
        if row is None:
            raise Http404
        try:
            forecast.undo(row)
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(forecast.build(self.ledger))


class ForecastAskView(PersonalView):
    """GET the price of both buttons (asks nothing); POST .../explain {view};
    POST .../review."""

    def get(self, request, what=None):
        from apps.personal import forecast_ai

        return Response(forecast_ai.status(request.tenant))

    def post(self, request, what):
        from apps.personal import forecast_ai

        try:
            if what == "explain":
                return Response(forecast_ai.explain_forecast(
                    self.ledger, request.tenant, view=str(request.data.get("view") or "90")))
            if what == "review":
                return Response(forecast_ai.review(self.ledger, request.tenant))
        except PersonalError as exc:
            return self.refusal(exc)
        raise Http404


class SidesView(PersonalView):
    """GET /api/personal/sides — both sides' cash at the end of 90 days, for
    the Overview (decision 15): numbers side by side, never one chart."""

    def get(self, request):
        from apps.finance import forecast as business
        from apps.tenancy import modules

        mine = forecast.ending(self.ledger)
        theirs = None
        if modules.has(request.tenant, modules.FORECAST):
            found = business.build(request.tenant, snapshot=False)
            view = found["views"]["90"]
            theirs = {"ready": found["ready"], "cash_today_cents": found["cash_today_cents"],
                      "end_cents": view["end_cents"], "low_cents": view["low_cents"],
                      "low_start": view["low_start"]}
        return Response({"days": 90, "personal": mine, "business": theirs})


# -------------------------------------------------------------------- debts

class DebtListView(WhoseView):
    """GET the debts and the plan (`?order=&extra=` tries another, saving
    nothing); POST a debt."""

    def get(self, request):
        try:
            order = request.query_params.get("order") or None
            if order and order not in debts.ORDERS:
                raise PersonalError(debts.BAD_ORDER)
            extra = request.query_params.get("extra")
            if extra not in (None, "") and not extra.isdigit():
                raise PersonalError("extra is a whole number of cents.")
            return Response(debts.represent(self.ledger, whose=self.whose(), order=order,
                                            extra=int(extra) if extra else None))
        except PersonalError as exc:
            return self.refusal(exc)

    def post(self, request):
        try:
            debts.save(self.ledger, data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(debts.represent(self.ledger), status=201)


class DebtView(PersonalView):
    """PATCH a debt; POST .../balance {on_date, balance_cents}; DELETE closes it."""

    def _debt(self, pk):
        row = PersonalDebt.objects.filter(ledger=self.ledger, pk=pk,
                                          closed_at__isnull=True).first()
        if row is None:
            raise Http404
        return row

    def patch(self, request, pk):
        try:
            debts.save(self.ledger, debt=self._debt(pk), data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(debts.represent(self.ledger))

    def post(self, request, pk):
        try:
            debts.add_balance(self._debt(pk), cents=request.data.get("balance_cents"),
                              on_date=_day(request.data.get("on_date")) or timezone.localdate())
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(debts.represent(self.ledger), status=201)

    def delete(self, request, pk):
        debts.close(self._debt(pk))
        return Response(debts.represent(self.ledger))


class DebtPlanView(PersonalView):
    """POST {order, extra_cents}: save the payoff plan. The extra is an
    envelope in Debt payments."""

    def post(self, request):
        try:
            debts.set_plan(self.ledger, order=request.data.get("order"),
                           extra=request.data.get("extra_cents"))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(debts.represent(self.ledger))


# --------------------------------------------------------------- retirement

class HoldingListView(WhoseView):
    """GET retirement and investments; POST one; POST .../return {percent}."""

    def get(self, request):
        try:
            return Response(retirement.summary(self.ledger, whose=self.whose()))
        except PersonalError as exc:
            return self.refusal(exc)

    def post(self, request):
        try:
            if "assumed_return_percent" in request.data:
                retirement.set_return(self.ledger, request.data["assumed_return_percent"])
            else:
                retirement.save(self.ledger, data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(retirement.summary(self.ledger), status=201)


class HoldingView(PersonalView):
    def _holding(self, pk):
        row = PersonalHolding.objects.filter(ledger=self.ledger, pk=pk,
                                             closed_at__isnull=True).first()
        if row is None:
            raise Http404
        return row

    def patch(self, request, pk):
        try:
            retirement.save(self.ledger, holding=self._holding(pk), data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(retirement.summary(self.ledger))

    def post(self, request, pk):
        try:
            retirement.add_balance(self._holding(pk), cents=request.data.get("balance_cents"),
                                   on_date=_day(request.data.get("on_date")) or timezone.localdate())
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(retirement.summary(self.ledger), status=201)

    def delete(self, request, pk):
        retirement.close(self._holding(pk))
        return Response(retirement.summary(self.ledger))


# ---------------------------------------------------------------- household

class HouseholdView(PersonalView):
    """GET the household, whose is what, and each person's income; POST a
    person; POST .../whose {thing, id, whose}."""

    def payload(self):
        return {"members": [household.represent(m) for m in household.members(self.ledger)],
                "things": household.whose_is_what(self.ledger),
                "income": household.income_by_person(self.ledger)}

    def get(self, request, what=None):
        return Response(self.payload())

    def post(self, request, what=None):
        try:
            if what == "whose":
                household.set_whose(self.ledger, thing=request.data.get("thing"),
                                    pk=request.data.get("id"),
                                    whose=request.data.get("whose"))
            else:
                household.save(self.ledger, data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(self.payload(), status=201 if what is None else 200)


class MemberView(HouseholdView):
    def patch(self, request, pk):
        try:
            household.save(self.ledger, row=household.member(self.ledger, pk),
                           data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(self.payload())

    def delete(self, request, pk):
        try:
            household.remove(household.member(self.ledger, pk))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(self.payload())


# ---------------------------------------------------------------- net worth

class NetWorthView(WhoseView):
    """GET net worth over time; POST a thing owned {name, kind, whose, debt,
    value_cents, value_on}."""

    def get(self, request):
        try:
            return Response(networth.summary(self.ledger, whose=self.whose()))
        except PersonalError as exc:
            return self.refusal(exc)

    def post(self, request):
        try:
            networth.save_asset(self.ledger, data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(networth.summary(self.ledger), status=201)


class AssetView(PersonalView):
    """PATCH a thing owned (a new value with value_cents); DELETE puts it away."""

    def _asset(self, pk):
        row = PersonalAsset.objects.filter(ledger=self.ledger, pk=pk,
                                           closed_at__isnull=True).first()
        if row is None:
            raise Http404
        return row

    def patch(self, request, pk):
        try:
            networth.save_asset(self.ledger, asset=self._asset(pk), data=dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(networth.summary(self.ledger))

    def delete(self, request, pk):
        networth.close_asset(self._asset(pk))
        return Response(networth.summary(self.ledger))
