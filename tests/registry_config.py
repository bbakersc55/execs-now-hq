"""Registration of every tenant-scoped model (assumption B3).

Adding a model without adding it here fails `test_registry_completeness`.
That is the point: this file cannot be forgotten, because omitting it is red.
"""

from __future__ import annotations

from apps.accounts.models import MagicLinkToken
from apps.crm.models import (
    EmailAttachment, UnmatchedInbound, Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactServiceCategory, ContactType, ContactTypeLink, EmailMessage,
    ContactPipelinePosition, DevSendAllowlistEntry, EmailTemplate, EmailThread,
    Campaign, CampaignRecipient, EmailSuppression, Enrollment, MailPreference,
    DuplicateDismissal,
    GmailConnection,
    ImportBatch, Pipeline,
    ImportMappingProfile, ImportRow, OutboxAttachment, OutboxMessage,
    PipelineStage, ServiceCategory, StageAutomation, StageChange, Task,
)
from apps.notes.models import Note, NotePinUnlock
from apps.platform.models import AgreementAcceptance, Feedback
from apps.work.models import (
    Comment, CompanyGoalOrder, Digest, DigestItem, Goal, GoalMeasurement, GoalMilestone,
    GoalOrderProposal, GoalProposal,
    GoalNarrative, GoalNarrativeVersion, GoalReportExport, GoalResolution,
    Project, Stakeholder, StakeholderToken, TaskChecklistItem, TaskUpdate,
)
from apps.meetings.models import (
    Commitment, DriveBackfill, DriveExclusion, DriveWatch, DriveWatchFolder, Meeting,
    MeetingParticipant, MeetingProposal, MeetingSourceFile, ProposalItem,
)
from apps.strategy.models import (
    StrategyCallNotes, StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
    StrategyPrepQuestion, StrategyQuestion, StrategySection, StrategySession,
    StrategySessionPrep, StrategyStyleExample, StrategyTemplate,
)
from apps.tenancy.models import (
    AiCall, AuditEvent, ClientAssignment, Membership, StoredFile, TenantSecret,
)
from apps.billing.models import (
    ClientInvoice, ClientInvoiceLine, ClientInvoiceSchedule, ClientPayment, InvoiceSettings,
)
from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceCategoryChange, FinanceEntry, FinanceImportBatch,
    FinanceImportProfile, FinanceImportRow, FinanceRule, FinanceSettings,
)
from apps.tenancy.registry import register

from . import factories

register(Membership, factories.MembershipFactory)
register(ClientAssignment, factories.ClientAssignmentFactory)
register(Company, factories.CompanyFactory)
register(TenantSecret, factories.TenantSecretFactory, api_exposed=False)
register(AuditEvent, factories.AuditEventFactory)
register(StoredFile, factories.StoredFileFactory, api_exposed=False)
register(AiCall, factories.AiCallFactory, api_exposed=False)
register(MagicLinkToken, factories.MagicLinkTokenFactory, api_exposed=False)

# --- Module 1 ---
register(Contact, factories.ContactFactory)
# Read through the contact's own routes (`/enrollments/`), never by id.
register(Enrollment, factories.EnrollmentFactory, api_exposed=False)
# Read through the contact's own routes (`/suppressions/`), never by id.
register(EmailSuppression, factories.EmailSuppressionFactory, api_exposed=False)
register(Campaign, factories.CampaignFactory, endpoints=("/api/campaigns/",))
# Read through the campaign's own routes (`/recipients/`), never by id.
register(CampaignRecipient, factories.CampaignRecipientFactory, api_exposed=False)
register(ContactEmail, factories.ContactEmailFactory)
register(ContactPhone, factories.ContactPhoneFactory)
register(ContactType, factories.ContactTypeFactory)
register(ContactTypeLink, factories.ContactTypeLinkFactory)
register(ContactServiceCategory, factories.ContactServiceCategoryFactory)
register(ServiceCategory, factories.ServiceCategoryFactory)
register(PipelineStage, factories.PipelineStageFactory)
register(StageChange, factories.StageChangeFactory)
register(CompanyDomain, factories.CompanyDomainFactory)
register(CompanyLocation, factories.CompanyLocationFactory)
register(StageAutomation, factories.StageAutomationFactory)
register(EmailTemplate, factories.EmailTemplateFactory)
register(EmailThread, factories.EmailThreadFactory)
register(EmailMessage, factories.EmailMessageFactory)
# --- Module 6 — inbound.
register(UnmatchedInbound, factories.UnmatchedInboundFactory,
         endpoints=("/api/unmatched-inbound/",))
register(EmailAttachment, factories.EmailAttachmentFactory, api_exposed=False)
register(GmailConnection, factories.GmailConnectionFactory)
register(DevSendAllowlistEntry, factories.DevSendAllowlistEntryFactory)
register(MailPreference, factories.MailPreferenceFactory)
register(Pipeline, factories.PipelineFactory)
register(ContactPipelinePosition, factories.ContactPipelinePositionFactory)
register(OutboxMessage, factories.OutboxMessageFactory)
register(OutboxAttachment, factories.OutboxAttachmentFactory)
register(ImportBatch, factories.ImportBatchFactory)
register(ImportRow, factories.ImportRowFactory)
register(ImportMappingProfile, factories.ImportMappingProfileFactory)
register(Task, factories.TaskFactory)
register(Note, factories.NoteFactory)
register(NotePinUnlock, factories.NotePinUnlockFactory, api_exposed=False)

# --- Module 3 ---
register(Goal, factories.GoalFactory)
register(Project, factories.ProjectFactory)
register(TaskChecklistItem, factories.TaskChecklistItemFactory)
register(Comment, factories.CommentFactory)
register(TaskUpdate, factories.TaskUpdateFactory)
register(Stakeholder, factories.StakeholderFactory)
register(StakeholderToken, factories.StakeholderTokenFactory, api_exposed=False)
register(Digest, factories.DigestFactory)
register(DigestItem, factories.DigestItemFactory)

# --- Module 4B — the client value report.
register(GoalMeasurement, factories.GoalMeasurementFactory,
         endpoints=("/api/goal-measurements/",))
register(GoalMilestone, factories.GoalMilestoneFactory,
         endpoints=("/api/goal-milestones/",))
register(GoalResolution, factories.GoalResolutionFactory,
         endpoints=("/api/goal-resolutions/",))
# Read through its company (`/api/goal-order/?client_company=`), and decided
# by id: `/api/goal-order/<id>/accept/`. tests/test_goal_order.py covers both.
register(GoalOrderProposal, factories.GoalOrderProposalFactory, api_exposed=False)
# Read through its company (`/api/goal-proposals/?client_company=`), and
# decided by id; tests/test_goal_proposals.py covers both.
register(GoalProposal, factories.GoalProposalFactory, api_exposed=False)
# Never addressed by id at all: read and written through `/api/goal-order/`.
register(CompanyGoalOrder, factories.CompanyGoalOrderFactory, api_exposed=False)
register(GoalReportExport, factories.GoalReportExportFactory,
         endpoints=("/api/value-report-exports/",))
# Reached only through their goal — there is no endpoint that takes one by id.
register(GoalNarrative, factories.GoalNarrativeFactory, api_exposed=False)
register(GoalNarrativeVersion, factories.GoalNarrativeVersionFactory,
         api_exposed=False)

# --- Module 5 — meeting ingestion.
register(DriveWatch, factories.DriveWatchFactory, endpoints=("/api/drive-watch/",))
# Read through the folder's own routes, never by id.
register(DriveBackfill, factories.DriveBackfillFactory, api_exposed=False)
# Both read through the folder card (`/api/drive-watch/`), never by id alone.
register(DriveWatchFolder, factories.DriveWatchFolderFactory, api_exposed=False)
register(Commitment, factories.CommitmentFactory, endpoints=("/api/commitments/",))
register(DriveExclusion, factories.DriveExclusionFactory, api_exposed=False)
register(MeetingSourceFile, factories.MeetingSourceFileFactory, api_exposed=False)
register(MeetingProposal, factories.MeetingProposalFactory,
         endpoints=("/api/meeting-proposals/",))
register(ProposalItem, factories.ProposalItemFactory,
         endpoints=("/api/proposal-items/",))
register(Meeting, factories.MeetingFactory, api_exposed=False)
register(MeetingParticipant, factories.MeetingParticipantFactory, api_exposed=False)

# --- Module 4 — the strategy session.
register(StrategyTemplate, factories.StrategyTemplateFactory,
         endpoints=("/api/strategy-templates/",))
register(StrategySession, factories.StrategySessionFactory,
         endpoints=("/api/strategy-sessions/",))
register(StrategyMapRow, factories.StrategyMapRowFactory,
         endpoints=("/api/strategy-map-rows/",))
register(StrategyPathNote, factories.StrategyPathNoteFactory,
         endpoints=("/api/strategy-path-notes/",))
register(StrategyDiagnosticProposal, factories.StrategyDiagnosticProposalFactory,
         endpoints=("/api/strategy-diagnostic-proposals/",))
# Read only into the drafting prompts; no endpoint.
register(StrategyStyleExample, factories.StrategyStyleExampleFactory, api_exposed=False)
register(StrategyPrepQuestion, factories.StrategyPrepQuestionFactory,
         endpoints=("/api/strategy-prep-questions/",))
# Reached only through its session — there is no endpoint that takes one by id.
register(StrategySessionPrep, factories.StrategySessionPrepFactory, api_exposed=False)
# Reached only through their template or their session, never by id of their
# own — there is no endpoint that takes one.
register(StrategySection, factories.StrategySectionFactory, api_exposed=False)
register(StrategyQuestion, factories.StrategyQuestionFactory, api_exposed=False)
register(StrategyAnswer, factories.StrategyAnswerFactory, api_exposed=False)

# --- P2: the platform layer ---
# Accepted once, on the agreement screen; never read back by id.
register(AgreementAcceptance, factories.AgreementAcceptanceFactory, api_exposed=False)
# Staff send it and list their own (/api/feedback/); the platform owner reads
# it through apps/platform/feedback.py, the one crossing.
register(Feedback, factories.FeedbackFactory, endpoints=("/api/feedback/",))

# Backlog 2026-10-03: written and undone through /api/contacts/not-duplicates/;
# never read by id.
register(DuplicateDismissal, factories.DuplicateDismissalFactory, api_exposed=False)

# --- P4A: client invoicing ---
register(ClientInvoice, factories.ClientInvoiceFactory, endpoints=("/api/invoices/",))
register(ClientInvoiceSchedule, factories.ClientInvoiceScheduleFactory,
         endpoints=("/api/invoice-schedules/",))
# Read through their invoice, or the one settings route; never by id.
register(ClientInvoiceLine, factories.ClientInvoiceLineFactory, api_exposed=False)
register(ClientPayment, factories.ClientPaymentFactory, api_exposed=False)
register(InvoiceSettings, factories.InvoiceSettingsFactory, api_exposed=False)

# --- P5: the books (the practice owner's only) ---
register(FinanceEntry, factories.FinanceEntryFactory, endpoints=("/api/finance-entries/",))
register(FinanceAccount, factories.FinanceAccountFactory,
         endpoints=("/api/finance-accounts/",))
register(FinanceCategory, factories.FinanceCategoryFactory,
         endpoints=("/api/finance-categories/",))
register(FinanceSettings, factories.FinanceSettingsFactory, api_exposed=False)
register(FinanceImportBatch, factories.FinanceImportBatchFactory,
         endpoints=("/api/finance-imports/",))
register(FinanceRule, factories.FinanceRuleFactory, endpoints=("/api/finance-rules/",))
register(FinanceImportRow, factories.FinanceImportRowFactory, api_exposed=False)
register(FinanceImportProfile, factories.FinanceImportProfileFactory, api_exposed=False)
register(FinanceCategoryChange, factories.FinanceCategoryChangeFactory,
         endpoints=("/api/finance-categories/changes/",))

# The notes of a call, attached to its session: read through the session, by
# the practice owner and an associate on their own prospect, and nobody else.
register(StrategyCallNotes, factories.StrategyCallNotesFactory, api_exposed=False)
