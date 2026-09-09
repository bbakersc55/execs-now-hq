"""Registration of every tenant-scoped model (assumption B3).

Adding a model without adding it here fails `test_registry_completeness`.
That is the point: this file cannot be forgotten, because omitting it is red.
"""

from __future__ import annotations

from apps.accounts.models import MagicLinkToken
from apps.crm.models import (
    Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactServiceCategory, ContactType, ContactTypeLink, EmailMessage,
    EmailTemplate, EmailThread, GmailConnection, ImportBatch,
    ImportMappingProfile, ImportRow, OutboxAttachment, OutboxMessage,
    PipelineStage, ServiceCategory, StageAutomation, StageChange, Task,
)
from apps.notes.models import Note
from apps.tenancy.models import (
    AiCall, AuditEvent, ClientAssignment, Membership, StoredFile, TenantSecret,
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
register(GmailConnection, factories.GmailConnectionFactory)
register(OutboxMessage, factories.OutboxMessageFactory)
register(OutboxAttachment, factories.OutboxAttachmentFactory)
register(ImportBatch, factories.ImportBatchFactory)
register(ImportRow, factories.ImportRowFactory)
register(ImportMappingProfile, factories.ImportMappingProfileFactory)
register(Task, factories.TaskFactory)
register(Note, factories.NoteFactory)
