"""Factories for the two mandatory test families."""

from __future__ import annotations

import factory
from django.utils import timezone

from apps.accounts.models import MagicLinkToken, User
from apps.crm.models import Company
from apps.tenancy.models import (
    AiCall, AuditEvent, ClientAssignment, Membership, Role, StoredFile,
    Tenant, TenantSecret,
)


class TenantScopedFactory(factory.django.DjangoModelFactory):
    """Base for tenant-scoped factories.

    `objects` is fail-closed (assumption B1), so it raises during factory
    creation — correctly: a factory building rows in two tenants at once has no
    single tenant to bind. Test setup is one of the legitimate uses of the
    explicit `all_objects` escape hatch, so factories use it deliberately.

    Note what this does NOT do: the tests themselves still query through
    `objects`, so the scoping under test is never bypassed.
    """

    class Meta:
        abstract = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return model_class.all_objects.create(*args, **kwargs)


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Practice {n}")
    slug = factory.Sequence(lambda n: f"practice-{n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.invalid")
    full_name = factory.Sequence(lambda n: f"User {n}")


class CompanyFactory(TenantScopedFactory):
    class Meta:
        model = Company

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Company {n}")


class ClientCompanyFactory(CompanyFactory):
    is_client_company = True
    seat_count = 3


class MembershipFactory(TenantScopedFactory):
    class Meta:
        model = Membership

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    role = Role.FF


class ClientAssignmentFactory(TenantScopedFactory):
    class Meta:
        model = ClientAssignment

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    company = factory.SubFactory(ClientCompanyFactory)


class TenantSecretFactory(TenantScopedFactory):
    class Meta:
        model = TenantSecret

    tenant = factory.SubFactory(TenantFactory)
    kind = "anthropic_api_key"
    ciphertext = b"encrypted"
    last4 = "abcd"


class AuditEventFactory(TenantScopedFactory):
    class Meta:
        model = AuditEvent

    tenant = factory.SubFactory(TenantFactory)
    verb = "test.event"


class StoredFileFactory(TenantScopedFactory):
    class Meta:
        model = StoredFile

    tenant = factory.SubFactory(TenantFactory)
    bucket = "execs-now-hq-media"
    object_key = factory.Sequence(lambda n: f"object-{n}")
    purpose = "recording_audio"


class AiCallFactory(TenantScopedFactory):
    class Meta:
        model = AiCall

    tenant = factory.SubFactory(TenantFactory)
    purpose = "digest_prose"
    model = "claude-opus-5"


class MagicLinkTokenFactory(TenantScopedFactory):
    class Meta:
        model = MagicLinkToken

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    token_hash = factory.Sequence(lambda n: f"{n:064d}")
    expires_at = factory.LazyFunction(
        lambda: timezone.now() + timezone.timedelta(minutes=20)
    )
