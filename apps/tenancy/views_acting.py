"""Acting as another user — FR-3.42, matrix 9.6–9.10.

POST /api/act-as/            start, as the REAL person (never while acting)
POST /api/act-as/stop/       the explicit end
GET  /api/act-as/candidates/ who the real person may act as

Entering and leaving are audited. While acting, `request.membership` is the
acted-as user's; `request.real_membership` is always the person at the keyboard.
"""

from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import acting
from .models import CLIENT_ROLES, AuditEvent, ClientAssignment, Membership, Role


class ActAsViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request):
        real = getattr(request, "real_membership", None)
        if getattr(request, "acting_as", None) is not None:
            return Response({"detail": "Stop acting as "
                             f"{request.acting_as.user.full_name or request.acting_as.user.email}"
                             " first."}, status=409)
        if real is None or real.role not in (Role.FF, Role.CF, Role.FCC):
            return Response({"detail": "Acting as someone else is not available to you."},
                            status=403)
        target = acting.load_target(real.tenant_id, request.data.get("membership"))
        refused = acting.refusal(real, target)
        if refused is not None:
            return Response({"detail": refused[1]}, status=refused[0])
        request.session[acting.SESSION_KEY] = str(target.pk)
        AuditEvent.all_objects.create(
            tenant_id=real.tenant_id, actor=request.real_user, verb="act_as.started",
            target_type="membership", target_id=target.pk,
            payload={"acting_role": real.role, "acted_as": target.user.email,
                     "acted_as_role": target.role, "company": str(target.client_company_id)},
        )
        return Response(acting.describe(request.real_user, real.role, target), status=201)

    @action(detail=False, methods=["post"])
    def stop(self, request):
        target = getattr(request, "acting_as", None)
        if target is None:
            return Response({"detail": "You are not acting as anyone."}, status=409)
        real = request.real_membership
        request.session.pop(acting.SESSION_KEY, None)
        AuditEvent.all_objects.create(
            tenant_id=real.tenant_id, actor=request.real_user, verb="act_as.stopped",
            target_type="membership", target_id=target.pk,
            payload={"acting_role": real.role, "acted_as": target.user.email,
                     "acted_as_role": target.role, "company": str(target.client_company_id)},
        )
        return_to = (f"/companies/{target.client_company_id}"
                     if real.role in (Role.FF, Role.CF) else "/work")
        return Response({"stopped": True, "return_to": return_to})

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        real = getattr(request, "real_membership", None)
        if getattr(request, "acting_as", None) is not None:
            return Response({"detail": "Stop acting as someone first."}, status=409)
        if real is None or real.role not in (Role.FF, Role.CF, Role.FCC):
            return Response({"detail": "Acting as someone else is not available to you."},
                            status=403)
        rows = (Membership.all_objects.filter(
                    tenant_id=real.tenant_id, role__in=CLIENT_ROLES, revoked_at__isnull=True)
                .exclude(pk=real.pk).select_related("user", "client_company"))
        if real.role == Role.FCC:
            rows = rows.filter(client_company_id=real.client_company_id)
        else:
            rows = rows.filter(client_company__is_client_company=True,
                               client_company__deleted_at__isnull=True)
            if real.role == Role.CF:
                rows = rows.filter(client_company_id__in=ClientAssignment.all_objects.filter(
                    tenant_id=real.tenant_id, user_id=real.user_id, removed_at__isnull=True,
                ).values("company_id"))
        company = request.query_params.get("company")
        if company:
            rows = rows.filter(client_company_id=company) if _uuid(company) else rows.none()
        return Response([
            {"membership": str(m.pk), "name": m.user.full_name or m.user.email,
             "email": m.user.email, "role": m.role,
             "company": str(m.client_company_id), "company_name": m.client_company.name}
            for m in rows.order_by("client_company__name", "user__email")
        ])


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False
