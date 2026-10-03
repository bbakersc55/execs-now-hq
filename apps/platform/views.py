"""The Practices area's endpoints (P2). Nothing here reads a practice's rows:
the numbers come from `stats.py`, feedback from `feedback.py`."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.permissions import IsPlatformOwner
from apps.tenancy.middleware import AREA_PLATFORM, AREA_PRACTICE, AREA_SESSION_KEY


class AreaView(APIView):
    """POST {"area": "platform" | "practice"}: the switch at the top of the
    sidebar. Kept in the session; the middleware reads it on every request."""

    permission_classes = [IsPlatformOwner]

    def post(self, request):
        area = request.data.get("area")
        if area not in (AREA_PLATFORM, AREA_PRACTICE):
            return Response({"detail": "Choose your practice or Practices."}, status=400)
        request.session[AREA_SESSION_KEY] = area
        return Response({"area": area})
