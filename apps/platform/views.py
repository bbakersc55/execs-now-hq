"""The Practices area's endpoints (P2). Nothing here reads a practice's rows:
the numbers come from `stats.py`, feedback from `feedback.py`."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform import provisioning, stats
from apps.platform.permissions import IsPlatformOwner, IsPlatformOwnerInPracticesArea
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


class PracticesView(APIView):
    """GET: every practice, numbers only (stats.py). POST: create one."""

    permission_classes = [IsPlatformOwnerInPracticesArea]

    def get(self, request):
        return Response(stats.practice_rows())

    def post(self, request):
        data = request.data
        try:
            tenant = provisioning.provision_practice(
                legal_name=data.get("legal_name", ""), display_name=data.get("display_name", ""),
                domain=data.get("domain", ""), owner_email=data.get("owner_email", ""),
                actor=request.user)
        except provisioning.ProvisioningRefused as exc:
            return Response({"detail": str(exc), "errors": exc.errors}, status=400)
        row = next(r for r in stats.practice_rows() if r["id"] == str(tenant.pk))
        return Response(row, status=201)


class PracticeView(APIView):
    """PATCH the platform's record of a practice (names, domain); POST
    `archive` or `unarchive`."""

    permission_classes = [IsPlatformOwnerInPracticesArea]

    def _tenant(self, pk):
        from apps.tenancy.models import Tenant

        return Tenant.objects.filter(pk=pk).first()

    def patch(self, request, pk):
        tenant = self._tenant(pk)
        if tenant is None:
            return Response({"detail": "No such practice."}, status=404)
        try:
            provisioning.update_identity(
                tenant, legal_name=request.data.get("legal_name"),
                display_name=request.data.get("display_name"),
                domain=request.data.get("domain"))
        except provisioning.ProvisioningRefused as exc:
            return Response({"detail": str(exc), "errors": exc.errors}, status=400)
        return Response(next(r for r in stats.practice_rows() if r["id"] == str(tenant.pk)))

    def post(self, request, pk, action=None):
        if action not in ("archive", "unarchive"):
            return Response({"detail": "Archive or unarchive."}, status=405)
        tenant = self._tenant(pk)
        if tenant is None:
            return Response({"detail": "No such practice."}, status=404)
        if action == "archive":
            # Archiving your own practice would sign you out of it, with no
            # practice left to switch back to.
            if _is_own(tenant, request.user):
                return Response({"detail": "You can't archive your own practice."}, status=400)
            provisioning.archive(tenant, actor=request.user)
        else:
            provisioning.unarchive(tenant, actor=request.user)
        return Response(next(r for r in stats.practice_rows() if r["id"] == str(tenant.pk)))


def _is_own(tenant, user) -> bool:
    from apps.tenancy.models import Membership

    return Membership.all_objects.filter(tenant=tenant, user=user,
                                         revoked_at__isnull=True).exists()
