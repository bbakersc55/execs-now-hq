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


class CompanyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Company

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Company {n}")


class ClientCompanyFactory(CompanyFactory):
    is_client_company = True
    seat_count = 3


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    role = Role.FF


class ClientAssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClientAssignment

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    company = factory.SubFactory(ClientCompanyFactory)


class TenantSecretFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TenantSecret

    tenant = factory.SubFactory(TenantFactory)
    kind = "anthropic_api_key"
    ciphertext = b"encrypted"
    last4 = "abcd"


class AuditEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditEvent

    tenant = factory.SubFactory(TenantFactory)
    verb = "test.event"


class StoredFileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoredFile

    tenant = factory.SubFactory(TenantFactory)
    bucket = "execs-now-hq-media"
    object_key = factory.Sequence(lambda n: f"object-{n}")
    purpose = "recording_audio"


class AiCallFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AiCall

    tenant = factory.SubFactory(TenantFactory)
    purpose = "digest_prose"
    model = "claude-opus-5"


class MagicLinkTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MagicLinkToken

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    token_hash = factory.Sequence(lambda n: f"{n:064d}")
    expires_at = factory.LazyFunction(
        lambda: timezone.now() + timezone.timedelta(minutes=20)
    )
