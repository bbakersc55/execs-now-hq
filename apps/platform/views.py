"""The Practices area's endpoints (P2). Nothing here reads a practice's rows:
the numbers come from `stats.py`, feedback from `feedback.py`."""

from __future__ import annotations

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform import provisioning, stats
from apps.accounts.ratelimit import RateLimit
from apps.crm.permissions import IsTenantStaff
from apps.platform.permissions import IsPlatformOwner, IsPlatformOwnerInPracticesArea

#: Spec §7: ten an hour per person.
FEEDBACK_LIMIT = RateLimit(limit=10, window_seconds=3600, prefix="feedback")
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


class PracticeModuleView(APIView):
    """POST {"module": "bookkeeping", "enabled": true | false}: switch one of
    a practice's modules (P6 M1 §7). The platform's record of the practice;
    nothing inside it is read."""

    permission_classes = [IsPlatformOwnerInPracticesArea]

    def post(self, request, pk):
        from apps.tenancy import modules
        from apps.tenancy.models import Tenant

        tenant = Tenant.objects.filter(pk=pk).first()
        if tenant is None:
            return Response({"detail": "No such practice."}, status=404)
        module, enabled = request.data.get("module"), request.data.get("enabled")
        if module not in modules.MODULES:
            return Response({"detail": "There is no such module."}, status=400)
        if not isinstance(enabled, bool):
            return Response({"detail": "enabled is true or false."}, status=400)
        modules.set_enabled(tenant, module, enabled, actor=request.user)
        return Response(next(r for r in stats.practice_rows() if r["id"] == str(tenant.pk)))


def _is_own(tenant, user) -> bool:
    from apps.tenancy.models import Membership

    return Membership.all_objects.filter(tenant=tenant, user=user,
                                         revoked_at__isnull=True).exists()


class InviteView(APIView):
    """POST: send the practice owner's invitation. Never automatic."""

    permission_classes = [IsPlatformOwnerInPracticesArea]

    def post(self, request, pk):
        from apps.platform import mail
        from apps.tenancy.models import Tenant

        tenant = Tenant.objects.filter(pk=pk).first()
        if tenant is None:
            return Response({"detail": "No such practice."}, status=404)
        if tenant.status == Tenant.Status.ARCHIVED:
            return Response({"detail": "Unarchive the practice before inviting anyone."},
                            status=409)
        try:
            message = mail.send_invitation(tenant, actor=request.user)
        except mail.PlatformMailUnavailable as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({"sent_to": message.to_address, "state": message.state})


class AgreementView(APIView):
    """GET the current beta agreement; POST {version, sha256} to accept it.
    For a signed-in practice member; only a practice owner is asked."""

    def get(self, request):
        from apps.platform import agreement

        if getattr(request, "membership", None) is None:
            return Response({"detail": "Sign in first."}, status=403)
        return Response({**agreement.current(), "required": agreement.required(request)})

    def post(self, request):
        from apps.platform import agreement

        if not agreement.required(request):
            return Response({"detail": "Nothing to accept."}, status=409)
        try:
            agreement.accept(request, version=request.data.get("version", ""),
                             sha256=request.data.get("sha256", ""))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({"accepted": True})



class FeedbackView(APIView):
    """Staff (practice owner, associate, assistant): send feedback, and list
    what you have sent. Clients never see the button or reach this."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.platform import feedback

        return Response(feedback.own(request))

    def post(self, request):
        from apps.accounts.ratelimit import too_many
        from apps.platform import feedback

        if too_many(FEEDBACK_LIMIT, str(request.user.pk)):
            return Response({"detail": "That's a lot of feedback in an hour. Try again later."},
                            status=429)
        data = request.data
        try:
            row = feedback.submit(request, doing=data.get("doing", ""),
                                  happened=data.get("happened", ""),
                                  expected=data.get("expected", ""),
                                  page_url=data.get("page_url", ""),
                                  screenshot=request.FILES.get("screenshot"))
        except feedback.FeedbackInvalid as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"id": str(row.pk)}, status=201)


class PlatformFeedbackView(APIView):
    """The platform owner reads all feedback, and marks it seen or closed."""

    permission_classes = [IsPlatformOwnerInPracticesArea]

    def get(self, request, pk=None):
        from django.http import Http404, HttpResponse

        from apps.platform import feedback
        from apps.tenancy import storage

        if pk is None:
            return Response(feedback.for_platform())
        row = feedback.platform_get(pk)
        if row is None or row.screenshot is None:
            raise Http404
        return HttpResponse(storage.read(row.screenshot),
                            content_type=row.screenshot.content_type or "image/png")

    def patch(self, request, pk=None):
        from apps.platform import feedback
        from apps.platform.models import Feedback

        row = feedback.platform_get(pk) if pk else None
        status = request.data.get("status")
        if row is None:
            return Response({"detail": "No such feedback."}, status=404)
        if status not in Feedback.Status.values:
            return Response({"detail": "New, seen or closed."}, status=400)
        Feedback.all_objects.filter(pk=row.pk).update(status=status)
        return Response({"id": str(row.pk), "status": status})
