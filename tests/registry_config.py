"""Registration of every tenant-scoped model (assumption B3).

Adding a model without adding it here fails `test_registry_completeness`.
That is the point: this file cannot be forgotten, because omitting it is red.
"""

from __future__ import annotations

from apps.accounts.models import MagicLinkToken
from apps.crm.models import (
    EmailAttachment, UnmatchedInbound, Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactServiceCategory, ContactType, ContactTypeLink, EmailMessage,
    ContactPipelinePosition, DevSendAllowlistEntry, EmailTemplate, EmailTemplateUse, EmailThread,
    Campaign, CampaignAttachment, CampaignRecipient, EmailSuppression, Enrollment, MailPreference,
    DuplicateDismissal,
    GmailConnection,
    ImportBatch, Pipeline,
    ImportMappingProfile, ImportRow, OutboxAttachment, OutboxMessage,
    FollowUp, FollowUpRun, FollowUpRunStep, FollowUpStep, PipelineNotice, PipelineStage, Referral, ServiceCategory, StageAutomation, StageChange,
    StageRuleFiring, Task,
)
from apps.notes.models import Note, NoteFolder, NotePinUnlock
from apps.platform.models import AgreementAcceptance, Feedback
from apps.work.models import (
    ClientTeam, ClientTeamMember,
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
    NmiEvent,
    AutopayConsent, ClientPaymentMethod, PaymentAccount, PaymentAttempt, PracticeInvoice,
    PracticeInvoiceLine, PracticeSubscription, PracticeSubscriptionAddon,
)
from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceCategoryChange, FinanceCleared, FinanceEntry,
    FinanceGuide, FinanceImportBatch, FinanceImportProfile, FinanceImportRow,
    FinanceMonthClose, FinanceReconciliation, FinanceRule, FinanceSettings,
)
from apps.scorecard.models import (
    BonusComponent, BonusPerson, BonusPlan, BonusReopen, BonusResult, Kpi, KpiMonthTarget, KpiPerson, KpiReading, KpiFeed, KpiReadingChange, KpiReminder, KpiTrackFeed, Scorecard, TrackConnection,
    HubSpotConnection, KpiHubSpotFeed, KpiAppFeed,
    ScorecardPage,
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
# Read through the campaign's own routes (the campaign's `attachments`), never by id.
register(CampaignAttachment, factories.CampaignAttachmentFactory, api_exposed=False)
register(Referral, factories.ReferralFactory, endpoints=("/api/referrals/",))
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
register(EmailTemplate, factories.EmailTemplateFactory, endpoints=("/api/email-templates/",))
register(EmailTemplateUse, factories.EmailTemplateUseFactory)
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
register(NoteFolder, factories.NoteFolderFactory, endpoints=("/api/note-folders/",))
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
# P7 phase 1: no route reads or writes a team yet. tests/test_client_teams.py
# holds that a team is never reachable from another company or practice.
register(ClientTeam, factories.ClientTeamFactory, api_exposed=False)
register(ClientTeamMember, factories.ClientTeamMemberFactory, api_exposed=False)
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
# --- P4 part 1: the practice's NMI account. Its one route is the practice's
# own (/api/payment-account/), never by id.
register(PaymentAccount, factories.PaymentAccountFactory, api_exposed=False)
# P4 part 2: read only through the portal's invoice routes, never by id.
register(PaymentAttempt, factories.PaymentAttemptFactory, api_exposed=False)
# P4 part 4: the company's own, through /api/portal-autopay/ (no ids).
register(ClientPaymentMethod, factories.ClientPaymentMethodFactory, api_exposed=False)
register(AutopayConsent, factories.AutopayConsentFactory, api_exposed=False)
# P4 part 5: the practice's own subscription, through /api/subscription/ (the
# practice owner's; no ids but its invoices' PDFs).
register(PracticeSubscription, factories.PracticeSubscriptionFactory, api_exposed=False)
register(PracticeSubscriptionAddon, factories.PracticeSubscriptionAddonFactory,
         api_exposed=False)
register(PracticeInvoice, factories.PracticeInvoiceFactory, api_exposed=False)
register(PracticeInvoiceLine, factories.PracticeInvoiceLineFactory, api_exposed=False)

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
# P6 M1, second stop. A reconciliation is read on the grid and by id; what it
# cleared, a month's closes and a person's "walk me through it" only through it.
register(FinanceReconciliation, factories.FinanceReconciliationFactory,
         endpoints=("/api/finance-reconcile/",))
register(FinanceCleared, factories.FinanceClearedFactory, api_exposed=False)
register(FinanceMonthClose, factories.FinanceMonthCloseFactory, api_exposed=False)
register(FinanceGuide, factories.FinanceGuideFactory, api_exposed=False)

# The notes of a call, attached to its session: read through the session, by
# the practice owner and an associate on their own prospect, and nobody else.
register(StrategyCallNotes, factories.StrategyCallNotesFactory, api_exposed=False)

# A person's own choice about the dashboard's Getting started card: read and
# written only as oneself, through the one route.
from apps.tenancy.models import GettingStartedDismissal  # noqa: E402

register(GettingStartedDismissal, factories.GettingStartedDismissalFactory,
         api_exposed=False)

# The year's miles and square feet for the CPA's worksheet: the one settings
# route, by year, never by id.
from apps.finance.models import FinanceYearFacts  # noqa: E402

register(FinanceYearFacts, factories.FinanceYearFactsFactory, api_exposed=False)

# P6 M2: the cash forecast's one stored thing, the floor. Read and set
# through the forecast's own route, never by id.
from apps.finance.models import FinanceForecastSettings  # noqa: E402

register(FinanceForecastSettings, factories.FinanceForecastSettingsFactory,
         api_exposed=False)

# P6 M2, stop 2: what the owner has said about the forecast, and the monthly
# snapshot. All read and written through the forecast's own routes.
from apps.finance.models import (  # noqa: E402
    FinanceForecastAdjustment, FinanceForecastPlanned, FinanceForecastSnapshot,
)

register(FinanceForecastPlanned, factories.FinanceForecastPlannedFactory,
         endpoints=("/api/finance-forecast/",))
register(FinanceForecastAdjustment, factories.FinanceForecastAdjustmentFactory,
         endpoints=("/api/finance-forecast/",))
register(FinanceForecastSnapshot, factories.FinanceForecastSnapshotFactory,
         api_exposed=False)

# --- M5 part 1: the KPI scorecard. Read only through /api/scorecard/, which
# asks `apps.scorecard.access` (tests/test_scorecard.py). ---
register(Scorecard, factories.ScorecardFactory, api_exposed=False)
register(ScorecardPage, factories.ScorecardPageFactory, api_exposed=False)
register(Kpi, factories.KpiFactory, api_exposed=False)
register(KpiMonthTarget, factories.KpiMonthTargetFactory, api_exposed=False)
register(KpiPerson, factories.KpiPersonFactory, api_exposed=False)
register(KpiReading, factories.KpiReadingFactory, api_exposed=False)
register(KpiReadingChange, factories.KpiReadingChangeFactory, api_exposed=False)
register(KpiReminder, factories.KpiReminderFactory, api_exposed=False)
# M5 part 3: a KPI's sheet feed. Read only through /api/scorecard/feeds/,
# which finds the KPI through `access.company_for` (tests/test_scorecard_feeds.py).
register(KpiFeed, factories.KpiFeedFactory, api_exposed=False)
# M5 part 2: bonus plans. Read only through /api/scorecard/bonus/, which asks
# `apps.scorecard.bonus.BonusReader` (tests/test_scorecard_bonus.py).
register(BonusPlan, factories.BonusPlanFactory, api_exposed=False)
register(BonusComponent, factories.BonusComponentFactory, api_exposed=False)
register(BonusPerson, factories.BonusPersonFactory, api_exposed=False)
register(BonusResult, factories.BonusResultFactory, api_exposed=False)
register(BonusReopen, factories.BonusReopenFactory, api_exposed=False)

# Stage rules, part 2: an idle rule's once-per-stay record, never served; and
# the notices, served by /api/pipeline-notices/ to their recipient only
# (tests/test_stage_rules_part2.py).
register(StageRuleFiring, factories.StageRuleFiringFactory, api_exposed=False)
register(PipelineNotice, factories.PipelineNoticeFactory, api_exposed=False)

# Pipeline part 3: a stage's follow-up and each contact's run through it,
# served by /api/pipeline-stages/<id>/follow-up/ and the contact's own page
# (tests/test_follow_ups.py).
register(FollowUp, factories.FollowUpFactory, api_exposed=False)
register(FollowUpStep, factories.FollowUpStepFactory, api_exposed=False)
register(FollowUpRun, factories.FollowUpRunFactory, api_exposed=False)
register(FollowUpRunStep, factories.FollowUpRunStepFactory, api_exposed=False)
# P4 §4: what the NMI read-back found, the practice owner's alone
# (/api/nmi-events/, tests/test_nmi_read_back.py).
register(NmiEvent, factories.NmiEventFactory, api_exposed=False)

# M5 part 4: a company's Track connection and a KPI's Track measure, served by
# /api/scorecard/track/ through `access.company_for` (tests/test_scorecard_track.py).
register(TrackConnection, factories.TrackConnectionFactory, api_exposed=False)
register(KpiTrackFeed, factories.KpiTrackFeedFactory, api_exposed=False)

# M5, "My practice": a KPI of the practice's own scorecard read "From this
# app", served by /api/scorecard/app-feed/ (tests/test_scorecard_practice.py).
register(KpiAppFeed, factories.KpiAppFeedFactory, api_exposed=False)

# M5 part 5: a company's HubSpot connection and a KPI's HubSpot measure, served
# by /api/scorecard/hubspot/ through `access.company_for`
# (tests/test_scorecard_hubspot.py).
register(HubSpotConnection, factories.HubSpotConnectionFactory, api_exposed=False)
register(KpiHubSpotFeed, factories.KpiHubSpotFeedFactory, api_exposed=False)

# The Notices list and browser notifications (2026-10-26): each person's own,
# served by /api/notify/ for the person signed in (tests/test_notify.py).
from apps.notify.models import Notice, PushPreference, PushSubscription  # noqa: E402

register(Notice, factories.NoticeFactory, api_exposed=False)
register(PushSubscription, factories.PushSubscriptionFactory, api_exposed=False)
register(PushPreference, factories.PushPreferenceFactory, api_exposed=False)
