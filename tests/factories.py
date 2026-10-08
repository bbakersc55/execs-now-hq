"""Factories for the two mandatory test families."""

from __future__ import annotations

import decimal

import factory
from django.utils import timezone

from apps.accounts.models import MagicLinkToken, User
from apps.crm.models import (
    EmailAttachment, UnmatchedInbound, Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactPipelinePosition, ContactType, ContactTypeLink, ContactServiceCategory,
    Campaign, CampaignRecipient, DevSendAllowlistEntry, EmailSuppression, Enrollment,
    MailPreference, DuplicateDismissal,
    EmailMessage, EmailTemplate, EmailThread, GmailConnection, ImportBatch,
    ImportMappingProfile, ImportRow, OutboxAttachment, OutboxMessage, Pipeline,
    PipelineStage, ServiceCategory, StageAutomation, StageChange, Task,
)
from apps.meetings.models import (
    Commitment, DriveBackfill, DriveExclusion, DriveWatch, DriveWatchFolder, Meeting,
    MeetingParticipant, MeetingProposal, MeetingSourceFile, ProposalItem,
)
from apps.notes.models import Note, NotePinUnlock
from apps.platform.models import AgreementAcceptance, Feedback
from apps.work.models import (
    Comment, CompanyGoalOrder, Digest, DigestItem, Goal, GoalMeasurement, GoalMilestone,
    GoalOrderProposal, GoalProposal,
    GoalNarrative, GoalNarrativeVersion, GoalReportExport, GoalResolution,
    Project, Stakeholder, StakeholderToken, TaskChecklistItem, TaskUpdate,
)
from apps.strategy.models import (
    StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
    StrategyPrepQuestion, StrategyQuestion, StrategySection, StrategySession,
    StrategySessionPrep, StrategyStyleExample, StrategyTemplate,
)
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
    """Writes real bytes, like the real upload path does.

    A factory that produced metadata with no content behind it would reproduce
    the exact bug this class of test exists to catch, and every attachment test
    would pass against an empty file.
    """

    class Meta:
        model = StoredFile

    tenant = factory.SubFactory(TenantFactory)
    bucket = "execs-now-hq-media"
    object_key = factory.Sequence(lambda n: f"object-{n}")
    purpose = "recording_audio"
    content_type = "application/pdf"

    @factory.post_generation
    def content(obj, create, extracted, **kwargs):
        if not create:
            return
        from apps.tenancy import storage

        body = extracted if extracted is not None else b"%PDF-1.4 test content"
        obj.byte_size = storage.write_content(obj, body)
        obj.save(update_fields=["byte_size", "updated_at"])


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

class PipelineFactory(TenantScopedFactory):
    class Meta:
        model = Pipeline

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Pipeline {n}")
    kind = "custom"


class PipelineStageFactory(TenantScopedFactory):
    class Meta:
        model = PipelineStage

    tenant = factory.SubFactory(TenantFactory)
    pipeline = factory.SubFactory(PipelineFactory)
    code = factory.Sequence(lambda n: f"stage{n}")
    label = factory.Sequence(lambda n: f"Stage {n}")
    semantic = "none"


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


class CampaignFactory(TenantScopedFactory):
    class Meta:
        model = Campaign

    tenant = factory.SubFactory(TenantFactory)
    name = "Autumn note"
    subject = "Hello {FirstName}"
    body_html = "<p>Hi {FirstName}, a note from {FractionalName} at {Company}.</p>"


class CampaignRecipientFactory(TenantScopedFactory):
    class Meta:
        model = CampaignRecipient

    tenant = factory.SubFactory(TenantFactory)
    campaign = factory.SubFactory(CampaignFactory, tenant=factory.SelfAttribute("..tenant"))
    contact = factory.SubFactory("tests.factories.ContactFactory",
                                 tenant=factory.SelfAttribute("..tenant"))


class EmailSuppressionFactory(TenantScopedFactory):
    class Meta:
        model = EmailSuppression

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory("tests.factories.ContactFactory",
                                 tenant=factory.SelfAttribute("..tenant"))
    category = "marketing"


class EnrollmentFactory(TenantScopedFactory):
    class Meta:
        model = Enrollment

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory("tests.factories.ContactFactory",
                                 tenant=factory.SelfAttribute("..tenant"))
    program = "referral_touches"


class ContactFactory(TenantScopedFactory):
    class Meta:
        model = Contact

    tenant = factory.SubFactory(TenantFactory)
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")


class ContactPipelinePositionFactory(TenantScopedFactory):
    class Meta:
        model = ContactPipelinePosition

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory)
    pipeline = factory.SubFactory(PipelineFactory)
    stage = factory.SubFactory(PipelineStageFactory)


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
    pipeline = factory.SubFactory(PipelineFactory)
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
    pipeline = factory.SubFactory(PipelineFactory)
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


class MailPreferenceFactory(TenantScopedFactory):
    class Meta:
        model = MailPreference

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)


class DevSendAllowlistEntryFactory(TenantScopedFactory):
    class Meta:
        model = DevSendAllowlistEntry

    tenant = factory.SubFactory(TenantFactory)
    address = factory.Sequence(lambda n: f"allowed{n}@example.invalid")


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


class NotePinUnlockFactory(TenantScopedFactory):
    class Meta:
        model = NotePinUnlock

    tenant = factory.SubFactory(TenantFactory)
    note = factory.SubFactory(NoteFactory, tenant=factory.SelfAttribute("..tenant"))
    user = factory.SubFactory(UserFactory)
    session_key = factory.Sequence(lambda n: f"session{n:032d}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(minutes=30))


# --- Module 3 -----------------------------------------------------------------

class GoalFactory(TenantScopedFactory):
    class Meta:
        model = Goal

    tenant = factory.SubFactory(TenantFactory)
    title = factory.Sequence(lambda n: f"Goal {n}")


class ProjectFactory(TenantScopedFactory):
    class Meta:
        model = Project

    tenant = factory.SubFactory(TenantFactory)
    title = factory.Sequence(lambda n: f"Project {n}")


class TaskChecklistItemFactory(TenantScopedFactory):
    class Meta:
        model = TaskChecklistItem

    tenant = factory.SubFactory(TenantFactory)
    task = factory.SubFactory(TaskFactory, tenant=factory.SelfAttribute("..tenant"))
    text = factory.Sequence(lambda n: f"Step {n}")


class CommentFactory(TenantScopedFactory):
    class Meta:
        model = Comment

    tenant = factory.SubFactory(TenantFactory)
    task = factory.SubFactory(TaskFactory, tenant=factory.SelfAttribute("..tenant"))
    author = factory.SubFactory(UserFactory)
    body = "Internal by default."


class TaskUpdateFactory(TenantScopedFactory):
    class Meta:
        model = TaskUpdate

    tenant = factory.SubFactory(TenantFactory)
    task = factory.SubFactory(TaskFactory, tenant=factory.SelfAttribute("..tenant"))
    kind = TaskUpdate.Kind.STATUS_CHANGED
    from_value = "not_started"
    to_value = "in_progress"


class StakeholderFactory(TenantScopedFactory):
    class Meta:
        model = Stakeholder

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"))
    task = factory.SubFactory(TaskFactory, tenant=factory.SelfAttribute("..tenant"))


class StakeholderTokenFactory(TenantScopedFactory):
    class Meta:
        model = StakeholderToken

    tenant = factory.SubFactory(TenantFactory)
    stakeholder = factory.SubFactory(StakeholderFactory,
                                     tenant=factory.SelfAttribute("..tenant"))
    token_hash = factory.Sequence(lambda n: f"{n:064d}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=30))


class DigestFactory(TenantScopedFactory):
    class Meta:
        model = Digest

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"))
    cadence = "weekly"
    period_start = factory.LazyFunction(lambda: timezone.now() - timezone.timedelta(days=7))
    period_end = factory.LazyFunction(timezone.now)
    send_window_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=1))


class DigestItemFactory(TenantScopedFactory):
    class Meta:
        model = DigestItem

    tenant = factory.SubFactory(TenantFactory)
    digest = factory.SubFactory(DigestFactory, tenant=factory.SelfAttribute("..tenant"))
    task_update = factory.SubFactory(TaskUpdateFactory,
                                     tenant=factory.SelfAttribute("..tenant"))


# --- Module 4 -----------------------------------------------------------------

class StrategyTemplateFactory(TenantScopedFactory):
    class Meta:
        model = StrategyTemplate

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Operations {n}")
    discipline = "operations"


class StrategySectionFactory(TenantScopedFactory):
    class Meta:
        model = StrategySection

    tenant = factory.SubFactory(TenantFactory)
    template = factory.SubFactory(StrategyTemplateFactory,
                                  tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"s{n}")
    title = factory.Sequence(lambda n: f"Section {n}")
    position = factory.Sequence(lambda n: n)


class StrategyQuestionFactory(TenantScopedFactory):
    class Meta:
        model = StrategyQuestion

    tenant = factory.SubFactory(TenantFactory)
    section = factory.SubFactory(StrategySectionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    template = factory.SelfAttribute("section.template")
    key = factory.Sequence(lambda n: f"q{n}")
    prompt = factory.Sequence(lambda n: f"Question {n}?")


class StrategySessionFactory(TenantScopedFactory):
    class Meta:
        model = StrategySession

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"))
    template = factory.SubFactory(StrategyTemplateFactory,
                                  tenant=factory.SelfAttribute("..tenant"))


class StrategyAnswerFactory(TenantScopedFactory):
    class Meta:
        model = StrategyAnswer

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    question_key = factory.Sequence(lambda n: f"q{n}")
    value = factory.LazyFunction(lambda: {"text": "An answer."})


class StrategyMapRowFactory(TenantScopedFactory):
    class Meta:
        model = StrategyMapRow

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    bottleneck = factory.Sequence(lambda n: f"Bottleneck {n}")


# ---------------------------------------------- Module 4B — the value report

class GoalMeasurementFactory(TenantScopedFactory):
    class Meta:
        model = GoalMeasurement

    tenant = factory.SubFactory(TenantFactory)
    goal = factory.SubFactory(GoalFactory, tenant=factory.SelfAttribute("..tenant"))
    value = decimal.Decimal("7")
    measured_at = factory.LazyFunction(lambda: timezone.localdate())


class GoalMilestoneFactory(TenantScopedFactory):
    class Meta:
        model = GoalMilestone

    tenant = factory.SubFactory(TenantFactory)
    goal = factory.SubFactory(GoalFactory, tenant=factory.SelfAttribute("..tenant"))
    title = factory.Sequence(lambda n: f"Milestone {n}")


class GoalProposalFactory(TenantScopedFactory):
    class Meta:
        model = GoalProposal

    tenant = factory.SubFactory(TenantFactory)
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))
    title = factory.Sequence(lambda n: f"Proposed goal {n}")


class CompanyGoalOrderFactory(TenantScopedFactory):
    class Meta:
        model = CompanyGoalOrder

    tenant = factory.SubFactory(TenantFactory)
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))


class GoalOrderProposalFactory(TenantScopedFactory):
    class Meta:
        model = GoalOrderProposal

    tenant = factory.SubFactory(TenantFactory)
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))


class GoalResolutionFactory(TenantScopedFactory):
    class Meta:
        model = GoalResolution

    tenant = factory.SubFactory(TenantFactory)
    goal = factory.SubFactory(GoalFactory, tenant=factory.SelfAttribute("..tenant"))
    resolution = GoalResolution.Resolution.PAUSED
    # Never blank: the database itself refuses one (AC-4B.10).
    reason = "Paused while the client hires."


class GoalNarrativeFactory(TenantScopedFactory):
    class Meta:
        model = GoalNarrative

    tenant = factory.SubFactory(TenantFactory)
    goal = factory.SubFactory(GoalFactory, tenant=factory.SelfAttribute("..tenant"))
    proposed_body = "A draft nobody has accepted."


class GoalNarrativeVersionFactory(TenantScopedFactory):
    class Meta:
        model = GoalNarrativeVersion

    tenant = factory.SubFactory(TenantFactory)
    narrative = factory.SubFactory(GoalNarrativeFactory,
                                   tenant=factory.SelfAttribute("..tenant"))
    goal = factory.SelfAttribute("narrative.goal")
    body = "What the client was told."


class GoalReportExportFactory(TenantScopedFactory):
    class Meta:
        model = GoalReportExport

    tenant = factory.SubFactory(TenantFactory)
    goal = factory.SubFactory(GoalFactory, tenant=factory.SelfAttribute("..tenant"))
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))
    stored_file = factory.SubFactory(StoredFileFactory,
                                     tenant=factory.SelfAttribute("..tenant"),
                                     purpose="value_report_pdf",
                                     object_key=factory.Sequence(
                                         lambda n: f"value-report/{n}.pdf"))


class StrategyPathNoteFactory(TenantScopedFactory):
    class Meta:
        model = StrategyPathNote

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    path = StrategyPathNote.Path.A
    kind = StrategyPathNote.Kind.PRO
    text = factory.Sequence(lambda n: f"A pro {n}")


class StrategyDiagnosticProposalFactory(TenantScopedFactory):
    class Meta:
        model = StrategyDiagnosticProposal

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    rule = StrategyDiagnosticProposal.Rule.LOWEST_RATING
    prompt = factory.Sequence(lambda n: f"A diagnostic question {n}?")


class StrategyStyleExampleFactory(TenantScopedFactory):
    class Meta:
        model = StrategyStyleExample

    tenant = factory.SubFactory(TenantFactory)
    kind = StrategyStyleExample.Kind.MAP_HEADER
    proposed = "Claude's words"
    accepted = "The practice's words"
    source_type = "strategy_map_row"
    source_id = factory.LazyFunction(__import__("uuid").uuid4)


class StrategySessionPrepFactory(TenantScopedFactory):
    class Meta:
        model = StrategySessionPrep

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    summary = "Their site says they clean commercial kitchens."


class StrategyPrepQuestionFactory(TenantScopedFactory):
    class Meta:
        model = StrategyPrepQuestion

    tenant = factory.SubFactory(TenantFactory)
    prep = factory.SubFactory(StrategySessionPrepFactory,
                              tenant=factory.SelfAttribute("..tenant"))
    session = factory.SelfAttribute("prep.session")
    text = factory.Sequence(lambda n: f"A question {n}")


# ------------------------------------------------ Module 5 — meeting ingestion

class DriveWatchFactory(TenantScopedFactory):
    class Meta:
        model = DriveWatch

    tenant = factory.SubFactory(TenantFactory)
    folder_id = factory.Sequence(lambda n: f"folder-{n}")


class DriveBackfillFactory(TenantScopedFactory):
    class Meta:
        model = DriveBackfill

    tenant = factory.SubFactory(TenantFactory)
    watch = factory.SubFactory(DriveWatchFactory,
                               tenant=factory.SelfAttribute("..tenant"))
    scope = "all"


class DriveWatchFolderFactory(TenantScopedFactory):
    class Meta:
        model = DriveWatchFolder

    tenant = factory.SubFactory(TenantFactory)
    watch = factory.SubFactory(DriveWatchFactory,
                               tenant=factory.SelfAttribute("..tenant"))
    folder_id = factory.Sequence(lambda n: f"meet-folder-{n}")
    folder_name = "Google Meet"


class DriveExclusionFactory(TenantScopedFactory):
    class Meta:
        model = DriveExclusion

    tenant = factory.SubFactory(TenantFactory)
    watch = factory.SubFactory(DriveWatchFactory,
                               tenant=factory.SelfAttribute("..tenant"))
    pattern = "AoA"


class MeetingSourceFileFactory(TenantScopedFactory):
    class Meta:
        model = MeetingSourceFile

    tenant = factory.SubFactory(TenantFactory)
    drive_file_id = factory.Sequence(lambda n: f"file-{n}")
    drive_version = "1"
    name = factory.Sequence(lambda n: f"Meeting notes {n}")
    mime_type = "application/vnd.google-apps.document"
    drive_file_owner_email = "bryan@getexecutivesnow.test"
    text = "Dana said she would send the margin breakdown."


class MeetingProposalFactory(TenantScopedFactory):
    class Meta:
        model = MeetingProposal

    tenant = factory.SubFactory(TenantFactory)
    source_file = factory.SubFactory(MeetingSourceFileFactory,
                                     tenant=factory.SelfAttribute("..tenant"))
    title = factory.Sequence(lambda n: f"A meeting {n}")


class ProposalItemFactory(TenantScopedFactory):
    class Meta:
        model = ProposalItem

    tenant = factory.SubFactory(TenantFactory)
    proposal = factory.SubFactory(MeetingProposalFactory,
                                  tenant=factory.SelfAttribute("..tenant"))
    kind = ProposalItem.Kind.ACTION_ITEM
    source_excerpt = "Dana said she would send the margin breakdown."
    payload = factory.LazyFunction(lambda: {"text": "Send the margin breakdown"})


class CommitmentFactory(TenantScopedFactory):
    class Meta:
        model = Commitment

    tenant = factory.SubFactory(TenantFactory)
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"))
    owner_name = "Dana Reyes"
    owner_kind = "prospect"
    text = "Send the Q3 margin breakdown"
    outcome = "record_only"


class MeetingFactory(TenantScopedFactory):
    class Meta:
        model = Meeting

    tenant = factory.SubFactory(TenantFactory)
    title = factory.Sequence(lambda n: f"A meeting {n}")


class MeetingParticipantFactory(TenantScopedFactory):
    class Meta:
        model = MeetingParticipant

    tenant = factory.SubFactory(TenantFactory)
    meeting = factory.SubFactory(MeetingFactory, tenant=factory.SelfAttribute("..tenant"))
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"))


class UnmatchedInboundFactory(TenantScopedFactory):
    class Meta:
        model = UnmatchedInbound

    tenant = factory.SubFactory(TenantFactory)
    provider = "gmail"
    provider_message_id = factory.Sequence(lambda n: f"unmatched-{n}")
    from_address = factory.Sequence(lambda n: f"stranger{n}@elsewhere.invalid")
    subject = "Re: Your progress report"
    body_text = "Can you send me the detail?"
    body_stripped = "Can you send me the detail?"
    reason = "no thread, and no contact holds that address"


class EmailAttachmentFactory(TenantScopedFactory):
    class Meta:
        model = EmailAttachment

    tenant = factory.SubFactory(TenantFactory)
    message = factory.SubFactory(EmailMessageFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    stored_file = factory.SubFactory(StoredFileFactory,
                                     tenant=factory.SelfAttribute("..tenant"))
    filename = "q3-margin.csv"


# --- P2: the platform layer ---

class AgreementAcceptanceFactory(TenantScopedFactory):
    class Meta:
        model = AgreementAcceptance

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    version = "v1"
    text_sha256 = "0" * 64


class FeedbackFactory(TenantScopedFactory):
    class Meta:
        model = Feedback

    tenant = factory.SubFactory(TenantFactory)
    practice_name = factory.SelfAttribute("tenant.name")
    submitted_by = factory.SubFactory(UserFactory)
    role = "FF"
    doing = "Approving a digest"
    happened = "The button did nothing"
    expected = "The digest to be approved"
    page_url = "/digests"


class DuplicateDismissalFactory(TenantScopedFactory):
    """A pair said not to be duplicates, stored in id order."""

    class Meta:
        model = DuplicateDismissal

    class Params:
        pair = factory.LazyAttribute(lambda o: sorted(
            [ContactFactory(tenant=o.tenant), ContactFactory(tenant=o.tenant)],
            key=lambda c: str(c.pk)))

    tenant = factory.SubFactory(TenantFactory)
    contact_a = factory.LazyAttribute(lambda o: o.pair[0])
    contact_b = factory.LazyAttribute(lambda o: o.pair[1])


# --- P4A: client invoicing ---

class InvoiceSettingsFactory(TenantScopedFactory):
    class Meta:
        model = "billing.InvoiceSettings"

    tenant = factory.SubFactory(TenantFactory)
    pay_instructions = "Pay by bank transfer to the account on file."


class ClientInvoiceFactory(TenantScopedFactory):
    class Meta:
        model = "billing.ClientInvoice"

    tenant = factory.SubFactory(TenantFactory)
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"),
                                 company=factory.SelfAttribute("..client_company"))
    issue_date = factory.LazyFunction(lambda: __import__("datetime").date(2026, 10, 1))
    due_date = factory.LazyFunction(lambda: __import__("datetime").date(2026, 10, 16))


class ClientInvoiceLineFactory(TenantScopedFactory):
    class Meta:
        model = "billing.ClientInvoiceLine"

    tenant = factory.SubFactory(TenantFactory)
    invoice = factory.SubFactory(ClientInvoiceFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    description = "Monthly retainer"
    unit_price_cents = 500000
    amount_cents = 500000


class ClientInvoiceScheduleFactory(TenantScopedFactory):
    class Meta:
        model = "billing.ClientInvoiceSchedule"

    tenant = factory.SubFactory(TenantFactory)
    client_company = factory.SubFactory(ClientCompanyFactory,
                                        tenant=factory.SelfAttribute("..tenant"))
    contact = factory.SubFactory(ContactFactory, tenant=factory.SelfAttribute("..tenant"),
                                 company=factory.SelfAttribute("..client_company"))
    day_of_month = 1
    next_on = factory.LazyFunction(lambda: __import__("datetime").date(2026, 11, 1))


class ClientPaymentFactory(TenantScopedFactory):
    class Meta:
        model = "billing.ClientPayment"

    tenant = factory.SubFactory(TenantFactory)
    invoice = factory.SubFactory(ClientInvoiceFactory,
                                 tenant=factory.SelfAttribute("..tenant"),
                                 total_cents=500000)
    amount_cents = 100000
    paid_on = factory.LazyFunction(lambda: __import__("datetime").date(2026, 10, 5))


# --- P5: the books ---

class FinanceAccountFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceAccount"

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Checking {n}")
    opening_on = factory.LazyFunction(lambda: __import__("datetime").date(2026, 1, 1))


class FinanceCategoryFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceCategory"

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Category {n}")
    type = "expense"


class FinanceSettingsFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceSettings"

    tenant = factory.SubFactory(TenantFactory)


class FinanceEntryFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceEntry"

    tenant = factory.SubFactory(TenantFactory)
    kind = "expense"
    direction = "out"
    amount_cents = 12500
    on_date = factory.LazyFunction(lambda: __import__("datetime").date(2026, 10, 1))
    account = factory.SubFactory(FinanceAccountFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    category = factory.SubFactory(FinanceCategoryFactory,
                                  tenant=factory.SelfAttribute("..tenant"))
    description = "Software subscription"


# --- P5, second stop: the import and rules ---

class FinanceRuleFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceRule"

    tenant = factory.SubFactory(TenantFactory)
    contains = factory.Sequence(lambda n: f"VENDOR {n}")
    treat_as = "ignore"


class FinanceImportProfileFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceImportProfile"

    tenant = factory.SubFactory(TenantFactory)
    account = factory.SubFactory(FinanceAccountFactory,
                                 tenant=factory.SelfAttribute("..tenant"))


class FinanceImportBatchFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceImportBatch"

    tenant = factory.SubFactory(TenantFactory)
    account = factory.SubFactory(FinanceAccountFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    filename = "export.csv"


class FinanceImportRowFactory(TenantScopedFactory):
    class Meta:
        model = "finance.FinanceImportRow"

    tenant = factory.SubFactory(TenantFactory)
    batch = factory.SubFactory(FinanceImportBatchFactory,
                               tenant=factory.SelfAttribute("..tenant"))
    row_number = 2
    outcome = "new"


class StrategyCallNotesFactory(TenantScopedFactory):
    class Meta:
        model = "strategy.StrategyCallNotes"

    tenant = factory.SubFactory(TenantFactory)
    session = factory.SubFactory(StrategySessionFactory,
                                 tenant=factory.SelfAttribute("..tenant"))
    text = "Call notes."
    source = "pasted"
