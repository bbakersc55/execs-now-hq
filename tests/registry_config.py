"""Registration of every tenant-scoped model (assumption B3).

Adding a model without adding it here fails `test_registry_completeness`.
That is the point: this file cannot be forgotten, because omitting it is red.
"""

from __future__ import annotations

from apps.accounts.models import MagicLinkToken
from apps.crm.models import Company
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
