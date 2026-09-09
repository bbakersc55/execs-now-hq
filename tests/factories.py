"""Factories for the two mandatory test families."""

from __future__ import annotations

import factory
from django.utils import timezone

from apps.accounts.models import MagicLinkToken, User
from apps.crm.models import (
    Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactType, ContactTypeLink, ContactServiceCategory, EmailMessage,
    EmailTemplate, EmailThread, GmailConnection, ImportBatch, ImportMappingProfile,
    ImportRow, OutboxAttachment, OutboxMessage, PipelineStage, ServiceCategory,
    StageAutomation, StageChange, Task,
)
from apps.notes.models import Note
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


# --------------------------------------------------------------- Module 1

class PipelineStageFactory(TenantScopedFactory):
    class Meta:
        model = PipelineStage

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"stage{n}")
    label = factory.Sequence(lambda n: f"Stage {n}")


class ContactTypeFactory(TenantScopedFactory):
    class Meta:
        model = ContactType

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"type{n}")
    label = factory.Sequence(lambda n: f"Type {n}")


class ServiceCategoryFactory(TenantScopedFactory):
    class Meta:
        model = ServiceCategory

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Category {n}")


class ContactFactory(TenantScopedFactory):
    class Meta:
        model = Contact

    tenant = factory.SubFactory(TenantFactory)
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")


class ContactEmailFactory(TenantScopedFactory):
    class Meta:
        model = ContactEmail

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    address = factory.Sequence(lambda n: f"contact{n}@example.invalid")
    is_primary = True


class ContactPhoneFactory(TenantScopedFactory):
    class Meta:
        model = ContactPhone

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    number = "+15555550100"


class ContactTypeLinkFactory(TenantScopedFactory):
    class Meta:
        model = ContactTypeLink

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    contact_type = factory.SubFactory(ContactTypeFactory)


class ContactServiceCategoryFactory(TenantScopedFactory):
    class Meta:
        model = ContactServiceCategory

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    service_category = factory.SubFactory(ServiceCategoryFactory)


class CompanyDomainFactory(TenantScopedFactory):
    class Meta:
        model = CompanyDomain

    tenant = factory.SubFactory(TenantFactory)
    company = factory.SubFactory(CompanyFactory)
    domain = factory.Sequence(lambda n: f"example{n}.invalid")


class CompanyLocationFactory(TenantScopedFactory):
    class Meta:
        model = CompanyLocation

    tenant = factory.SubFactory(TenantFactory)
    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Location {n}")
    position = factory.Sequence(lambda n: n % 5)


class StageChangeFactory(TenantScopedFactory):
    class Meta:
        model = StageChange

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    to_stage = factory.SubFactory(PipelineStageFactory)


class EmailTemplateFactory(TenantScopedFactory):
    class Meta:
        model = EmailTemplate

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Template {n}")
    kind = "stage"
    subject = "Following up"
    body = "Body text"


class StageAutomationFactory(TenantScopedFactory):
    class Meta:
        model = StageAutomation

    tenant = factory.SubFactory(TenantFactory)
    to_stage = factory.SubFactory(PipelineStageFactory)
    action_type = "create_task"


class EmailThreadFactory(TenantScopedFactory):
    class Meta:
        model = EmailThread

    tenant = factory.SubFactory(TenantFactory)
    thread_token = factory.Sequence(lambda n: f"token{n:020d}")


class EmailMessageFactory(TenantScopedFactory):
    class Meta:
        model = EmailMessage

    tenant = factory.SubFactory(TenantFactory)
    thread = factory.SubFactory(EmailThreadFactory)
    direction = "outbound"
    provider = "postmark"
    from_address = "info@example.invalid"


class GmailConnectionFactory(TenantScopedFactory):
    class Meta:
        model = GmailConnection

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    email_address = factory.Sequence(lambda n: f"gmail{n}@example.invalid")
    scopes = ["gmail.send"]


class OutboxMessageFactory(TenantScopedFactory):
    class Meta:
        model = OutboxMessage

    tenant = factory.SubFactory(TenantFactory)
    state = "pending_approval"
    producer = "stage_rule"
    to_address = factory.Sequence(lambda n: f"to{n}@example.invalid")
    from_address = "info@example.invalid"
    subject = "Subject"


class OutboxAttachmentFactory(TenantScopedFactory):
    class Meta:
        model = OutboxAttachment

    tenant = factory.SubFactory(TenantFactory)
    outbox_message = factory.SubFactory(OutboxMessageFactory)
    stored_file = factory.SubFactory(StoredFileFactory)
    filename = "flyer.pdf"


class ImportMappingProfileFactory(TenantScopedFactory):
    class Meta:
        model = ImportMappingProfile

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Profile {n}")


class ImportBatchFactory(TenantScopedFactory):
    class Meta:
        model = ImportBatch

    tenant = factory.SubFactory(TenantFactory)
    filename = "contacts.csv"


class ImportRowFactory(TenantScopedFactory):
    class Meta:
        model = ImportRow

    tenant = factory.SubFactory(TenantFactory)
    import_batch = factory.SubFactory(ImportBatchFactory)
    row_number = factory.Sequence(lambda n: n + 2)
    outcome = "create"


class TaskFactory(TenantScopedFactory):
    class Meta:
        model = Task

    tenant = factory.SubFactory(TenantFactory)
    title = factory.Sequence(lambda n: f"Task {n}")


class NoteFactory(TenantScopedFactory):
    class Meta:
        model = Note

    tenant = factory.SubFactory(TenantFactory)
    body = "Note body"
