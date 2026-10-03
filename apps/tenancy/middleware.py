"""Binds the tenant (and client company) for the life of a request.

Assumption B1, layer 2. Cleared in a `finally` so nothing leaks into the next
request served by the same worker.
"""

from __future__ import annotations

from .context import _acting, _current_client_company_id, _current_tenant_id
from .models import Membership

AREA_PRACTICE = "practice"
AREA_PLATFORM = "platform"
#: The session key the area switch writes (apps/platform/views.py).
AREA_SESSION_KEY = "enhq_area"


def in_platform_area(request) -> bool:
    """The Practices area: only for a platform owner who switched to it. For
    anyone else the session key is ignored, so setting it grants nothing."""
    user = getattr(request, "user", None)
    return (user is not None and user.is_authenticated
            and getattr(user, "is_platform_owner", False)
            and request.session.get(AREA_SESSION_KEY) == AREA_PLATFORM)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_token = _current_tenant_id.set(None)
        company_token = _current_client_company_id.set(None)
        acting_token = _acting.set(None)
        try:
            membership = self._membership_for(request)
            # P2: the platform owner in the Practices area is bound to **no**
            # practice. Every practice-scoped query then fails closed, through
            # the same manager that keeps practices apart from each other.
            request.area = AREA_PRACTICE
            if in_platform_area(request):
                request.area = AREA_PLATFORM
                membership = None
            # FR-3.42 — acting as. The real person stays on the request; the
            # acted-as login becomes `request.user` and its membership the
            # scope, so every existing rule applies exactly as it would to that
            # user. Re-checked on every request: a revoked target or a lost
            # assignment ends it (audited) rather than lingering.
            request.real_user = getattr(request, "user", None)
            request.real_membership = membership
            request.acting_as = None
            if membership is not None:
                from .acting import resolve

                target = resolve(request, membership)
                if target is not None:
                    request.acting_as = target
                    request.user = target.user
                    membership = target
                    _acting.set((request.real_user.pk, target.user_id))
            request.membership = membership
            request.tenant = membership.tenant if membership else None
            if membership is not None:
                _current_tenant_id.set(membership.tenant_id)
                # FR-0.2: client users bind a second, independent scope layer.
                if membership.is_client_user:
                    _current_client_company_id.set(membership.client_company_id)
            return self.get_response(request)
        finally:
            _current_tenant_id.reset(tenant_token)
            _current_client_company_id.reset(company_token)
            _acting.reset(acting_token)

    def process_exception(self, request, exception):
        """A query with no practice bound failed closed (the manager raised).
        For a request that is a refusal, not a server error: the platform
        owner in the Practices area, or anyone else with no practice, asked
        for practice data and gets none."""
        from django.http import JsonResponse

        from .context import TenantContextMissing

        if isinstance(exception, TenantContextMissing):
            return JsonResponse({"detail": "There is no practice here to show."}, status=403)
        return None

    @staticmethod
    def _membership_for(request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return (
            Membership.all_objects.select_related("tenant")
            .filter(user=user, revoked_at__isnull=True)
            .first()
        )
