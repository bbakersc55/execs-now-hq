"""Who reaches whose People data, at what level (2026-11-17).

A **scope** is one client company, or the practice's own people (`None`).
For a person and a scope, `access_for` gives one of:

- `director`: everything the app holds (the practice owner everywhere; a
  client owner for their own company; an HR Director grant);
- `generalist`: everyone, with the sensitive fields masked (a grant);
- `directory`: the directory fields of everyone (the client's senior
  leadership, with no HR permission);
- `reports`: their own record and their direct reports' directory fields (a
  manager, with no HR permission);
- `self`: their own record (an employee);
- `None`: nothing, and the answer is 404, never 403.

Nothing here reads the People Command Center's switch but `people_on`: with
it off, nobody reaches anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.tenancy.models import CLIENT_ROLES, Role

DIRECTOR, GENERALIST, DIRECTORY, REPORTS, SELF = (
    "director", "generalist", "directory", "reports", "self")
HR_LEVELS = (DIRECTOR, GENERALIST)
LABELS = {DIRECTOR: "HR Director", GENERALIST: "HR Generalist",
          DIRECTORY: "Senior leadership (directory)", REPORTS: "Manager (direct reports)",
          SELF: "Your own record"}
PRACTICE = "practice"


@dataclass
class Access:
    level: str
    #: For `reports` and `self`: the record ids they reach, and which of them
    #: they see in full (their own).
    reach: set = field(default_factory=set)
    own: set = field(default_factory=set)
    #: Can manage HR permissions here, and read the access log.
    manages: bool = False

    @property
    def hr(self) -> bool:
        return self.level in HR_LEVELS


def people_on(tenant_id) -> bool:
    from apps.centers import services as centers

    return bool(tenant_id) and centers.has(tenant_id, "people")


def scope_key(company) -> str:
    return PRACTICE if company is None else str(company.pk)


def _grant_level(user_id, tenant_id, company) -> str | None:
    from django.db.models import Q

    from apps.people.models import HRGrant, Level

    scope = Q(all_companies=True)
    scope |= (Q(client_company__isnull=True, all_companies=False) if company is None
              else Q(client_company_id=company.pk))
    levels = set(HRGrant.all_objects.filter(tenant_id=tenant_id, user_id=user_id,
                                            revoked_at__isnull=True)
                 .filter(scope).values_list("level", flat=True))
    if Level.DIRECTOR in levels:
        return DIRECTOR
    if Level.GENERALIST in levels:
        return GENERALIST
    return None


def _senior(membership) -> bool:
    """The client's senior leadership: leads every team, or leads one."""
    from apps.work.permissions import ClientScope

    scope = ClientScope(membership)
    return bool(scope.leads_all or scope.led_team_ids())


def access_for(membership, company) -> Access | None:
    """This member's access to one scope (a client company, or None for the
    practice's own people). None: they reach nothing there."""
    from apps.people.models import PersonRecord

    if membership is None or not people_on(membership.tenant_id):
        return None
    tenant_id = membership.tenant_id
    if company is not None and company.tenant_id != tenant_id:
        return None
    client_side = membership.role in CLIENT_ROLES
    if client_side and (company is None or company.pk != membership.client_company_id):
        return None
    if company is not None and not company.is_client_company:
        return None
    if membership.role == Role.FF:
        return Access(DIRECTOR, manages=True)
    if membership.role == Role.FCC:
        return Access(DIRECTOR, manages=True)
    granted = _grant_level(membership.user_id, tenant_id, company)
    if granted:
        return Access(granted)
    if client_side and _senior(membership):
        return Access(DIRECTORY)
    own = set(PersonRecord.all_objects.filter(
        tenant_id=tenant_id, client_company=company, user_id=membership.user_id)
        .values_list("pk", flat=True))
    if not own:
        return None
    reports = set(PersonRecord.all_objects.filter(tenant_id=tenant_id, client_company=company,
                                                  manager_id__in=own)
                  .values_list("pk", flat=True))
    if reports:
        return Access(REPORTS, reach=own | reports, own=own)
    return Access(SELF, reach=own, own=own)


def scopes_for(membership) -> list:
    """The scopes this member can open: (company or None, Access)."""
    from apps.crm.models import Company

    if membership is None or not people_on(membership.tenant_id):
        return []
    if membership.role in CLIENT_ROLES:
        candidates = list(Company.all_objects.filter(pk=membership.client_company_id))
    else:
        candidates = [None] + list(Company.all_objects.filter(
            tenant_id=membership.tenant_id, is_client_company=True, deleted_at__isnull=True)
            .order_by("name"))
    out = []
    for company in candidates:
        found = access_for(membership, company)
        if found is not None:
            out.append((company, found))
    return out


def holds_hr_permission(user) -> bool:
    """An HR permission in any practice that has People on: its owner, a
    client owner, or a grant. They must use two-factor sign-in."""
    from apps.people.models import HRGrant
    from apps.tenancy.models import Membership

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    tenants = set(Membership.all_objects.filter(
        user=user, revoked_at__isnull=True, role__in=(Role.FF, Role.FCC))
        .values_list("tenant_id", flat=True))
    tenants |= set(HRGrant.all_objects.filter(user=user, revoked_at__isnull=True)
                   .values_list("tenant_id", flat=True))
    return any(people_on(t) for t in tenants)


# ---------------------------------------------------------------- showing

MASK = "•••••"


def mask(value):
    if value in (None, "", []):
        return value
    if isinstance(value, list):
        return f"{len(value)} document{'' if len(value) == 1 else 's'}"
    return MASK


def sees_in_full(access: Access, record) -> bool:
    return access.level == DIRECTOR or record.pk in access.own


def visible(access: Access, records):
    """The records this access reaches."""
    if access.level in (DIRECTOR, GENERALIST, DIRECTORY):
        return records
    return records.filter(pk__in=access.reach)


# ------------------------------------------------- People's rows in other tables
# 2026-11-17, the records: what People puts in the app's shared tables (a
# checklist's tasks in Work, an offer letter in e-signature, the contact an
# offer is sent to) is People's. **Never to an AI app** (`request.ai_app`, set
# by every AI app's request), never in search, and to people only as below.

def _ai(request) -> bool:
    return bool(getattr(request, "ai_app", False))


def _hr_scopes(membership, levels=HR_LEVELS):
    """(everything, company ids, the practice's own) where this member holds
    one of `levels`: by being the practice owner or a client owner, or by a
    grant. Only while People is on."""
    from apps.people.models import HRGrant

    if membership is None or not people_on(membership.tenant_id):
        return False, set(), False
    if membership.role == Role.FF:
        return True, set(), True
    if membership.role == Role.FCC:
        return False, {membership.client_company_id}, False
    grants = HRGrant.all_objects.filter(tenant_id=membership.tenant_id,
                                        user_id=membership.user_id, revoked_at__isnull=True,
                                        level__in=levels)
    if membership.role in CLIENT_ROLES:
        grants = grants.filter(client_company_id=membership.client_company_id)
    everything = grants.filter(all_companies=True).exists()
    ids = set(grants.filter(client_company__isnull=False).values_list("client_company_id",
                                                                      flat=True))
    practice = grants.filter(client_company__isnull=True, all_companies=False).exists()
    return everything, ids, practice


def tasks_for(request, queryset):
    """A checklist's tasks in Work: to the practice owner, to whoever owns or
    is assigned one, and to HR permissions for that company. Never to an AI
    app."""
    from django.db.models import Q

    if _ai(request):
        return queryset.filter(people_item__isnull=True)
    membership = getattr(request, "membership", None)
    if membership is None:
        return queryset.filter(people_item__isnull=True)
    everything, ids, practice = _hr_scopes(membership)
    if everything:
        return queryset
    allowed = (Q(people_item__isnull=True) | Q(assignee_id=membership.user_id)
               | Q(owner_id=membership.user_id) | Q(client_company_id__in=ids))
    if practice:
        allowed |= Q(client_company__isnull=True)
    return queryset.filter(allowed)


def documents_for(request, rows):
    """People's documents for signature: to an HR Director of that company,
    and in the portal to their own signer. Never to an AI app."""
    from django.db.models import Exists, OuterRef, Q

    from apps.people.models import PersonDocument

    rows = rows.annotate(_peoples=Exists(PersonDocument.all_objects.filter(
        esign_document=OuterRef("pk"))))
    if _ai(request):
        return rows.filter(_peoples=False)
    membership = getattr(request, "membership", None)
    if membership is None:
        return rows.filter(_peoples=False)
    everything, ids, _practice = _hr_scopes(membership, levels=(DIRECTOR,))
    if everything:
        return rows
    allowed = Q(_peoples=False) | Q(company_id__in=ids)
    if membership.role in CLIENT_ROLES:
        # Their own: on their own record, or addressed to their own contact.
        rows = rows.annotate(_theirs=Exists(PersonDocument.all_objects.filter(
            esign_document=OuterRef("pk"), person__user_id=membership.user_id)))
        allowed |= Q(_theirs=True)
        if membership.contact_id:
            allowed |= Q(signer_id=membership.contact_id)
    return rows.filter(allowed)


def contacts_for(queryset):
    """A contact People made to send someone a document: never in Contacts,
    search or an AI app. It is reached through their record."""
    return queryset.exclude(people_made__isnull=False)


def messages_for(request, queryset):
    """The email that asks for a People document's signature, while it waits
    in the Sending queue: to an HR Director of that company only (an offer
    carries pay), and never to an AI app."""
    from django.db.models import Exists, OuterRef, Q

    from apps.people.models import PersonDocument

    def peoples(**more):
        return Exists(PersonDocument.all_objects.filter(esign_document_id=OuterRef("source_id"),
                                                        **more))

    membership = getattr(request, "membership", None)
    if _ai(request) or membership is None:
        return queryset.exclude(Q(source_type="document"), peoples())
    everything, ids, _practice = _hr_scopes(membership, levels=(DIRECTOR,))
    if everything:
        return queryset
    hidden = Exists(PersonDocument.all_objects.filter(
        esign_document_id=OuterRef("source_id")).exclude(person__client_company_id__in=ids))
    return queryset.exclude(Q(source_type="document"), hidden)
