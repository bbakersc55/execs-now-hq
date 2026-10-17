"""A demo visitor's own controls in their copy (2026-10-17): "Reset my demo"."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm.permissions import IsFF, IsTenantStaff


class DemoResetView(APIView):
    """POST: empty this copy and seed it again. The copy's practice owner
    only, and only in a visitor's copy."""

    permission_classes = [IsTenantStaff, IsFF]

    def post(self, request):
        from apps.tenancy.demo import visitors

        visitor = visitors.of(request.tenant)
        if visitor is None:
            return Response({"detail": "Only a demo visitor's copy can be reset."}, status=404)
        try:
            visitors.reset(visitor, actor=request.user)
        except visitors.VisitorRefused as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({"demo_visitor": visitors.describe(request.tenant)})
