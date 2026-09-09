"""Tenant binding for the current unit of work.

Assumption B1. A *contextvar*, not a thread-local: a contextvar survives async
and cannot leak across a reused worker thread, which a thread-local can.

Nothing in the application reads this directly. `TenantManager` reads it, and
raises when it is unset — see managers.py for why that is the whole point.
"""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar

_current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_tenant_id", default=None
)
_current_client_company_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_client_company_id", default=None
)


class TenantContextMissing(RuntimeError):
    """Raised when a tenant-scoped query runs with no tenant bound.

    This is the fail-closed guarantee in assumption B1. A forgotten scope is a
    loud error in a test, never a silent cross-tenant read in production.
    """


def get_current_tenant_id() -> uuid.UUID | None:
    return _current_tenant_id.get()


def get_current_client_company_id() -> uuid.UUID | None:
    return _current_client_company_id.get()


def require_current_tenant_id() -> uuid.UUID:
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise TenantContextMissing(
            "No tenant is bound to this context. Web requests bind one in "
            "TenantMiddleware; background jobs and management commands must "
            "use `with tenant_context(tenant_id):`. To query across tenants "
            "deliberately, use `Model.all_objects`."
        )
    return tenant_id


@contextlib.contextmanager
def tenant_context(tenant_id, client_company_id=None):
    """Bind a tenant (and optionally a client company) for a block of work.

    Background jobs have no request, so every task takes a tenant_id and opens
    one of these — same manager, same guarantees (assumption B1).
    """
    if hasattr(tenant_id, "pk"):
        tenant_id = tenant_id.pk
    if hasattr(client_company_id, "pk"):
        client_company_id = client_company_id.pk

    tenant_token = _current_tenant_id.set(tenant_id)
    company_token = _current_client_company_id.set(client_company_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(tenant_token)
        _current_client_company_id.reset(company_token)


@contextlib.contextmanager
def no_tenant_context():
    """Explicitly unbind. Used by tests asserting the fail-closed behaviour."""
    tenant_token = _current_tenant_id.set(None)
    company_token = _current_client_company_id.set(None)
    try:
        yield
    finally:
        _current_tenant_id.reset(tenant_token)
        _current_client_company_id.reset(company_token)
