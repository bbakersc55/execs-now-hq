"""Who sees and does what with an SOP (P10, "Who").

- **The studio exists only while the practice has a Command Center on.** With
  none, every route is 404 and nothing is listed (the plans engine's rule).
- **The practice owner**, and **an associate** for a company assigned to them,
  create, edit, publish, archive and remind. **An assistant** reads every SOP
  and drafts and edits, but never publishes or archives.
- **The portal:** a published SOP, its latest version only, to each person in
  its audience; never a draft, never the working copy. The **client owner**
  opens every published SOP of their company and sees who has read it, but is
  asked to read only when the audience includes them. **Anyone else outside
  the audience can't fetch it at all**: 404, as if it weren't there.
"""

from __future__ import annotations

from django.http import Http404

from apps.tenancy.models import CLIENT_ROLES, Role


def available(tenant_id) -> bool:
    from apps.plans.access import available as plans_available

    return plans_available(tenant_id)


def company_for(request, company_id):
    """The plans engine's reach rule: 404 for anyone who doesn't reach the
    company, and with no Command Center on. "practice" is the practice's row."""
    from apps.plans.access import company_for as plan_company

    return plan_company(request, company_id)


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


class SopAccess:
    def __init__(self, request, company):
        self.request = request
        self.company = company
        self.membership = request.membership
        self.role = self.membership.role
        self.is_client = self.role in CLIENT_ROLES
        self.is_client_owner = self.role == Role.FCC and \
            str(self.membership.client_company_id) == str(company.pk)

    @property
    def drafts(self) -> bool:
        return self.role in (Role.FF, Role.CF, Role.VA)

    @property
    def publishes(self) -> bool:
        return self.role in (Role.FF, Role.CF)

    @property
    def sees_reads(self) -> bool:
        """"7 of 12 read", the names outstanding, and Remind."""
        return self.publishes or self.role == Role.VA or self.is_client_owner

    @property
    def reminds(self) -> bool:
        return self.publishes or self.is_client_owner

    def describe(self) -> dict:
        return {"drafts": self.drafts, "publishes": self.publishes,
                "sees_reads": self.sees_reads, "reminds": self.reminds,
                "is_client": self.is_client}


def access_for(request, company_id) -> SopAccess:
    return SopAccess(request, company_for(request, company_id))


# ------------------------------------------------------------------ the audience

def audience_memberships(sop) -> list:
    """The people asked to read it: live client memberships of the company."""
    from apps.tenancy.models import Membership
    from apps.work.models import ClientTeamMember

    from .models import Sop

    live = Membership.all_objects.filter(
        tenant_id=sop.tenant_id, client_company_id=sop.company_id, role__in=CLIENT_ROLES,
        revoked_at__isnull=True).select_related("user", "contact")
    if sop.audience == Sop.Audience.TEAMS:
        team_ids = list(sop.audience_teams.filter(team__archived_at__isnull=True)
                        .values_list("team_id", flat=True))
        ids = ClientTeamMember.all_objects.filter(team_id__in=team_ids) \
            .values_list("membership_id", flat=True)
        live = live.filter(pk__in=ids)
    elif sop.audience == Sop.Audience.PEOPLE:
        live = live.filter(pk__in=sop.audience_people.values_list("membership_id", flat=True))
    return sorted(live, key=lambda m: (m.user.full_name or m.user.email).lower())


def in_audience(sop, membership) -> bool:
    return any(m.pk == membership.pk for m in audience_memberships(sop))


def portal_reaches(sop, membership) -> bool:
    """A client user opens it: published, of their company, and they are in
    its audience or are the client owner."""
    from .models import Sop

    if sop.status != Sop.Status.PUBLISHED or sop.version < 1 \
            or str(sop.company_id) != str(membership.client_company_id):
        return False
    return membership.role == Role.FCC or in_audience(sop, membership)


def sop_for(request, pk):
    """(sop, access), or 404: another practice's, a company out of reach, a
    draft to a client, or a client outside the audience."""
    from .models import Sop

    membership = getattr(request, "membership", None)
    if membership is None or not available(membership.tenant_id) or not _is_uuid(pk):
        raise Http404
    sop = Sop.objects.filter(pk=pk).select_related("company").first()
    if sop is None:
        raise Http404
    if membership.role in CLIENT_ROLES:
        if not portal_reaches(sop, membership):
            raise Http404
        return sop, SopAccess(request, sop.company)
    # The company's own reach rule (an associate's assigned companies).
    company = company_for(request, "practice" if sop.company.is_practice else sop.company_id)
    return sop, SopAccess(request, company)
