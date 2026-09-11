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


# ------------------------------------------------------------ Module 2 fakes

class FakeSpeech:
    """Google Speech-to-Text, faked at the client boundary.

    Operations are REAL `google.longrunning` protobufs carrying a real packed
    `LongRunningRecognizeResponse`, so the parsing code under test is the code
    that runs against Google.
    """

    def __init__(self):
        from types import SimpleNamespace

        self.started = []
        self.ops = {}
        self.fail_start = None
        self.transport = SimpleNamespace(
            operations_client=SimpleNamespace(get_operation=self._get)
        )

    def long_running_recognize(self, *, config, audio):
        from types import SimpleNamespace

        from google.longrunning import operations_pb2

        if self.fail_start is not None:
            raise self.fail_start
        name = f"operations/{len(self.started) + 1}"
        self.started.append({"config": config, "audio": audio, "name": name})
        self.ops[name] = operations_pb2.Operation(name=name, done=False)
        return SimpleNamespace(operation=SimpleNamespace(name=name))

    def _get(self, name):
        return self.ops[name]

    def finish(self, name, *paragraphs):
        from google.cloud import speech_v1
        from google.longrunning import operations_pb2

        response = speech_v1.LongRunningRecognizeResponse(results=[
            speech_v1.SpeechRecognitionResult(
                alternatives=[speech_v1.SpeechRecognitionAlternative(transcript=p)]
            ) for p in paragraphs
        ])
        op = operations_pb2.Operation(name=name, done=True)
        op.response.Pack(speech_v1.LongRunningRecognizeResponse.pb(response))
        self.ops[name] = op

    def fail(self, name, message):
        from google.longrunning import operations_pb2

        op = operations_pb2.Operation(name=name, done=True)
        op.error.code = 3
        op.error.message = message
        self.ops[name] = op


@pytest.fixture
def fake_stt(monkeypatch):
    from apps.notes import recording

    fake = FakeSpeech()
    monkeypatch.setattr(recording, "_speech_client", lambda: fake)
    return fake


class FakeClaude:
    """The Anthropic client at its boundary: records each request, returns the
    SDK's response shape."""

    def __init__(self):
        from types import SimpleNamespace

        self.requests = []
        self.reply = "**Summary** — A call about the warehouse move."
        self.stop_reason = "end_turn"
        self.model = "claude-opus-5"
        self.raise_exc = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        from types import SimpleNamespace

        self.requests.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return SimpleNamespace(
            model=self.model, stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=12000, output_tokens=800),
            content=[SimpleNamespace(type="text", text=self.reply)],
        )


@pytest.fixture
def fake_claude(monkeypatch, settings):
    from apps.tenancy import claude

    fake = FakeClaude()
    settings.ANTHROPIC_API_KEY = "sk-ant-test-fallback"
    monkeypatch.setattr(claude, "_client", lambda key: fake)
    return fake
