"""Bank connections over the API (the practice owner's, as the books are),
and the provider's webhook (`/webhooks/plaid`), which is public and proves
itself by its signature."""

from __future__ import annotations

import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.finance import services
from apps.finance.models import BankConnection
from apps.finance.views import FinanceViewSet

from . import connections, providers

log = logging.getLogger(__name__)


class BankConnectionViewSet(FinanceViewSet):
    def _connection(self, pk):
        return self._one(BankConnection, pk, "bank connection")

    def list(self, request):
        return Response(connections.overview(request.tenant))

    @action(detail=False, methods=["post"], url_path="link-token")
    def link_token(self, request):
        try:
            connection = (self._connection(request.data["connection"])
                          if request.data.get("connection") else None)
            return Response(connections.link_token(request.tenant, actor=request.user,
                                                   connection=connection))
        except services.FinanceError as exc:
            return self._refusal(exc)

    @action(detail=False, methods=["post"])
    def connect(self, request):
        try:
            made = connections.connect(request.tenant, actor=request.user,
                                       public_token=request.data.get("public_token"))
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(connections.represent(made), status=201)

    @action(detail=True, methods=["post"])
    def mapping(self, request, pk=None):
        try:
            made = connections.set_mapping(self._connection(pk), actor=request.user,
                                           mapping=request.data.get("mapping") or {})
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(connections.represent(made))

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        try:
            connection = self._connection(pk)
            counts = connections.check_now(connection, actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        connection.refresh_from_db()
        return Response({**connections.represent(connection), "counts": counts})

    @action(detail=True, methods=["post"])
    def reconnected(self, request, pk=None):
        try:
            made = connections.reconnected(self._connection(pk), actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(connections.represent(made))

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        try:
            connection = self._connection(pk)
            if connection.status == BankConnection.Status.DISCONNECTED:
                raise services.FinanceError("Already disconnected.", status=409)
            made = connections.disconnect(connection, actor=request.user)
        except services.FinanceError as exc:
            return self._refusal(exc)
        return Response(connections.represent(made))


@csrf_exempt
@require_POST
def plaid_webhook(request):
    """Verified before anything is read from it; a refusal says only that."""
    try:
        event = providers.get("plaid").read_webhook(request.body, request.headers)
    except providers.WebhookRefused as exc:
        log.warning("plaid webhook refused: %s", exc)
        return JsonResponse({"ok": False}, status=400)
    except providers.NotConfigured:
        return JsonResponse({"ok": False}, status=404)
    done = connections.webhook(event)
    log.info("plaid webhook %s: %s", event.code or event.kind, done)
    return JsonResponse({"ok": True})
