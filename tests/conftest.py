import pytest

from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401  (registration side effect)
from .factories import TenantFactory


@pytest.fixture
def tenant_a(db):
    return TenantFactory(name="Tenant A", slug="tenant-a")


@pytest.fixture
def tenant_b(db):
    return TenantFactory(name="Tenant B", slug="tenant-b")


@pytest.fixture
def in_tenant_a(tenant_a):
    with tenant_context(tenant_a.pk):
        yield tenant_a
