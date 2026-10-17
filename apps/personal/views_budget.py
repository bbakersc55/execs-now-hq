"""The budget's routes (P6 M4 stop 2), under /api/personal/, behind the same
door as the rest of the personal side (`views.OwnerOnly`): the practice
owner, in a practice with the module, and only their own ledger."""

from __future__ import annotations

from datetime import date

from rest_framework.response import Response

from apps.personal import budget, questions
from apps.personal.models import PersonalAccount, PersonalGoal, PersonalQuestion
from apps.personal.services import PersonalError
from apps.personal.views import PersonalView, represent_category


def _cents(value, what: str, *, allow_zero=True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PersonalError(f"{what} is a whole number of cents.")
    if value < 0 or (value == 0 and not allow_zero):
        raise PersonalError(f"{what} is more than zero.")
    return value


def _month(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(f"{value}-01" if len(value) == 7 else value).replace(day=1)
    except ValueError:
        raise PersonalError("month is YYYY-MM.") from None


def _day(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PersonalError("A date is YYYY-MM-DD.") from None


class BudgetView(PersonalView):
    """GET /api/personal/budget[?month=YYYY-MM]: the Overview. Before there
    is a budget, the proposal (decision 9), which sets nothing."""

    def get(self, request):
        try:
            month = _month(request.query_params.get("month"))
        except PersonalError as exc:
            return self.refusal(exc)
        ledger = self.ledger
        have = budget.has_budget(ledger)
        view = budget.month_view(ledger, month) if have else None
        found = None if have else budget.proposal(ledger)
        goals = PersonalGoal.of(request.user).filter(archived_at__isnull=True)\
            .select_related("account")
        return Response({
            "has_budget": have,
            "proposal": None if found is None else {
                "ready": found["ready"], "least_months": budget.LEAST_MONTHS,
                "months": [m.isoformat() for m in found["months"]],
                "envelopes": [{"category": represent_category(row["category"]),
                               "kind": row["kind"], "amounts": row["amounts"],
                               "proposed_cents": row["proposed_cents"]}
                              for row in found["envelopes"]]},
            "month": view,
            "goals": [budget.represent_goal(goal, view) for goal in goals],
            "coming_up": budget.coming_up(ledger),
            "cash_flow": budget.cash_flow(ledger),
            "questions_waiting": len(questions.waiting(ledger)) if have else 0,
        })


class BudgetAcceptView(PersonalView):
    """POST: use the proposal. Then the questions are waiting."""

    def post(self, request):
        try:
            made = budget.accept(self.ledger)
        except PersonalError as exc:
            return self.refusal(exc)
        return Response({"envelopes": len(made),
                         "questions_waiting": len(questions.waiting(self.ledger))})


class EnvelopeListView(PersonalView):
    """POST {category, planned_cents}: an envelope for a category."""

    def post(self, request):
        try:
            env = budget.add(self.ledger, category=self.category(request.data.get("category")),
                             planned_cents=_cents(request.data.get("planned_cents", 0),
                                                  "The amount"))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response({"id": str(env.pk)}, status=201)


class EnvelopeView(PersonalView):
    """PATCH {planned_cents, rolls}; POST .../cover {from_envelope,
    amount_cents} or {stand: true} (decision 10)."""

    def patch(self, request, pk):
        try:
            env = budget.envelope(self.ledger, pk)
            planned = request.data.get("planned_cents")
            budget.update(env, planned_cents=None if planned is None else _cents(
                planned, "The amount"), rolls=request.data.get("rolls"))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(budget.month_view(self.ledger))

    def post(self, request, pk):
        try:
            env = budget.envelope(self.ledger, pk)
            month = _month(request.data.get("month")) or budget.this_month()
            source = request.data.get("from_envelope")
            amount = request.data.get("amount_cents")
            budget.cover(env, month=month, stand=bool(request.data.get("stand")),
                         from_envelope=budget.envelope(self.ledger, source) if source else None,
                         amount_cents=None if amount is None else _cents(
                             amount, "The amount", allow_zero=False))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(budget.month_view(self.ledger, month))


class AssignView(PersonalView):
    """POST {goal, amount_cents}: some of what is unassigned, toward a goal."""

    def post(self, request):
        try:
            goal = self._goal(request.data.get("goal"))
            budget.assign_to_goal(self.ledger, goal=goal, amount_cents=_cents(
                request.data.get("amount_cents"), "The amount", allow_zero=False))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(budget.month_view(self.ledger))

    def _goal(self, pk):
        goal = PersonalGoal.of(self.request.user).filter(pk=pk, archived_at__isnull=True)\
            .first() if pk else None
        if goal is None:
            raise PersonalError("There is no such goal.", status=404)
        return goal


class QuestionListView(PersonalView):
    """GET: the questions waiting, in order. POST {ask: "coming"}: ask
    "Anything coming?" again."""

    def get(self, request):
        return Response([questions.represent(q) for q in questions.waiting(self.ledger)])

    def post(self, request):
        questions.ask_again(self.ledger)
        return Response([questions.represent(q) for q in questions.waiting(self.ledger)])


class QuestionView(PersonalView):
    """POST: an answer, or {skip: true}."""

    def post(self, request, pk):
        q = PersonalQuestion.of(request.user).filter(pk=pk).first()
        if q is None:
            return Response({"detail": "There is no such question."}, status=404)
        try:
            said = questions.answer(q, dict(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response({**said, "waiting": [questions.represent(x)
                                             for x in questions.waiting(self.ledger)]})


class GoalListView(AssignView):
    """GET the goals; POST one (decision 14)."""

    def get(self, request, pk=None):
        view = budget.month_view(self.ledger) if budget.has_budget(self.ledger) else None
        return Response([budget.represent_goal(g, view) for g in PersonalGoal.of(
            request.user).filter(archived_at__isnull=True).select_related("account")])

    def post(self, request, pk=None):
        try:
            goal = budget.save_goal(self.ledger, **self._fields(request.data))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(budget.represent_goal(goal, self._view()), status=201)

    def _view(self):
        return budget.month_view(self.ledger) if budget.has_budget(self.ledger) else None

    def _fields(self, data, goal=None) -> dict:
        account = None
        if data.get("account"):
            account = PersonalAccount.of(self.request.user).filter(pk=data["account"]).first()
            if account is None:
                raise PersonalError("There is no such account.", status=404)
        months = data.get("months_of_envelopes")
        target = data.get("target_cents")
        monthly = data.get("monthly_cents")
        return {"name": data.get("name", goal.name if goal else ""),
                "target_cents": None if target in (None, "") else _cents(target, "The target"),
                "target_on": _day(data.get("target_on")),
                "saved_cents": _cents(data.get("saved_cents", 0) or 0, "What is saved"),
                "account": account,
                "months_of_envelopes": int(months) if months not in (None, "") else None,
                "monthly_cents": None if monthly in (None, "") else _cents(monthly,
                                                                           "The amount")}


class GoalView(GoalListView):
    """PATCH a goal; DELETE puts it away (its envelope and planned line go)."""

    def patch(self, request, pk):
        try:
            goal = self._goal(pk)
            budget.save_goal(self.ledger, goal=goal, **self._fields(request.data, goal))
        except PersonalError as exc:
            return self.refusal(exc)
        goal.refresh_from_db()
        return Response(budget.represent_goal(goal, self._view()))

    def delete(self, request, pk):
        try:
            budget.archive_goal(self._goal(pk))
        except PersonalError as exc:
            return self.refusal(exc)
        return Response(status=204)


class ExplainBudgetView(PersonalView):
    """GET the price (asks nothing); POST asks Claude to read the budget."""

    def get(self, request):
        from apps.personal import budget_ai

        return Response(budget_ai.status(request.tenant))

    def post(self, request):
        from apps.personal import budget_ai

        try:
            return Response(budget_ai.explain_budget(self.ledger, request.tenant))
        except PersonalError as exc:
            return self.refusal(exc)
