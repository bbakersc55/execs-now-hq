"""Binds the tenant (and client company) for the life of a request.

Assumption B1, layer 2. Cleared in a `finally` so nothing leaks into the next
request served by the same worker.
"""

from __future__ import annotations

from .context import _acting, _current_client_company_id, _current_tenant_id
from .models import Membership


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_token = _current_tenant_id.set(None)
        company_token = _current_client_company_id.set(None)
        acting_token = _acting.set(None)
        try:
            membership = self._membership_for(request)
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
