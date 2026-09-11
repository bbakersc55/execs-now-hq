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
def sales(seeded_tenant):
    """The seeded sales pipeline."""
    from apps.crm.services import pipeline

    return pipeline.sales_pipeline(seeded_tenant)


@pytest.fixture
def referrals(seeded_tenant):
    """The seeded referral pipeline."""
    from apps.crm.services import pipeline

    return pipeline.referral_pipeline(seeded_tenant)


def _stages_of(pipeline):
    """`pipeline.stages` goes through the fail-closed manager, which is right in
    a request and wrong in a fixture — test setup uses the explicit escape
    hatch, as the factories do."""
    from apps.crm.models import PipelineStage

    return {
        s.code: s
        for s in PipelineStage.all_objects.filter(pipeline=pipeline).order_by("position")
    }


@pytest.fixture
def stages(sales):
    """Sales-pipeline stages by code. Codes are unique PER PIPELINE now, so a
    bare `stages` dict has to name which pipeline it means."""
    return _stages_of(sales)


@pytest.fixture
def referral_stages(referrals):
    return _stages_of(referrals)


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
def api():
    """Logs in as a membership and returns a client.

    Each membership gets its OWN client, so sessions are independent. Sharing
    one client makes session-invalidation tests silently vacuous: logging in as
    a second user would replace the first user's session before the code under
    test ever ran.
    """
    from django.test import Client as DjangoClient

    class Api:
        def __init__(self):
            self._clients = {}

        def as_(self, membership):
            key = str(membership.pk)
            if key not in self._clients:
                self._clients[key] = DjangoClient()
                self._clients[key].force_login(membership.user)
            return self._clients[key]

    return Api()


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Every test writes blobs into its own directory.

    Without this, `stored_file` content would leak between tests and — worse —
    into the real media bucket, which is the default backend since Phase 2.
    The only tests that touch GCS are marked `gcs_live` and opt in explicitly.
    """
    settings.STORAGE_BACKEND = "local"
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return settings.MEDIA_ROOT


@pytest.fixture
def dev_outbox(settings):
    """FR-0.7 — the local dev outbox. Every denied-send test asserts it is empty."""
    from django.core import mail

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    return mail.outbox
