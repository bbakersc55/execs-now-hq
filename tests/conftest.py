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


# ------------------------------------------------------------ Module 1 fixtures

@pytest.fixture
def seeded_tenant(tenant_a):
    """A tenant with the six pipeline stages and five contact types seeded."""
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_a)
    return tenant_a


@pytest.fixture
def stages(seeded_tenant):
    from apps.crm.models import PipelineStage

    return {
        s.code: s
        for s in PipelineStage.all_objects.filter(tenant=seeded_tenant)
    }


@pytest.fixture
def types(seeded_tenant):
    from apps.crm.models import ContactType

    return {
        t.code: t for t in ContactType.all_objects.filter(tenant=seeded_tenant)
    }


def _member(tenant, role, company=None):
    from .factories import MembershipFactory

    return MembershipFactory(tenant=tenant, role=role, client_company=company)


@pytest.fixture
def ff(seeded_tenant):
    return _member(seeded_tenant, "FF")


@pytest.fixture
def cf(seeded_tenant):
    return _member(seeded_tenant, "CF")


@pytest.fixture
def va(seeded_tenant):
    return _member(seeded_tenant, "VA")


@pytest.fixture
def fcc(seeded_tenant):
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant)
    return _member(seeded_tenant, "FCC", company=company)


@pytest.fixture
def api(client):
    """Returns a helper that logs in as a membership and issues API calls."""

    class Api:
        def as_(self, membership):
            client.force_login(membership.user)
            return client

    return Api()


@pytest.fixture
def dev_outbox(settings):
    """FR-0.7 — the local dev outbox. Every denied-send test asserts it is empty."""
    from django.core import mail

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    return mail.outbox
