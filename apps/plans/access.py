"""Who sees and edits a plan (P11, "Who sees and edits").

- **The plan exists only while the practice has a Command Center on.** With
  none, every route is 404 and nothing is listed.
- **The practice:** the practice owner, and an associate for a company they
  are assigned to, edit everything, the practice's own plan included. An
  assistant reads it.
- **The client portal**, for the client's own company only:
  - the client owner and senior leadership (a Senior leadership level on any
    team, or "leads all teams") see every horizon;
  - everyone else sees this month and this week, a month's or week's item
    only when it is the whole company's or one of their teams'.
  - Adding and editing at the month and week follows Work: a person who may
    create tasks there may add and edit here. At the year and quarter, the
    client owner and senior leadership propose; the practice approves.
  - The tray of Claude's and AI apps' proposals is the practice's.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import Http404

from apps.tenancy.models import CLIENT_ROLES, Role

from .models import Horizon

ALL = (Horizon.PICTURE, Horizon.YEAR, Horizon.QUARTER, Horizon.MONTH, Horizon.WEEK)
TEAM_HORIZONS = (Horizon.MONTH, Horizon.WEEK)
PROPOSED_FROM_CLIENT = (Horizon.YEAR, Horizon.QUARTER)
PRACTICE_KEY = "practice"


def available(tenant_id) -> bool:
    from apps.centers import services as centers

    return bool(centers.enabled(tenant_id))


class PlanAccess:
    """One person's place on one company's plan."""

    def __init__(self, request, company):
        from apps.work.permissions import client_scope
        from apps.work.teams import Level

        self.request = request
        self.company = company
        self.membership = request.membership
        self.role = self.membership.role
        self.is_client = self.role in CLIENT_ROLES
        self.scope = client_scope(request) if self.is_client else None
        if self.scope is not None:
            levels = dict(self.scope.levels)
            self.team_ids = set(levels)
            self.sees_all = self.scope.is_owner or self.scope.leads_all \
                or Level.LEADER in levels.values()
        else:
            self.team_ids = set()
            self.sees_all = True

    # --- what they see ------------------------------------------------------

    @property
    def horizons(self) -> tuple:
        return ALL if self.sees_all else TEAM_HORIZONS

    def sees_item(self, item) -> bool:
        if item.horizon not in self.horizons:
            return False
        if not self.is_client:
            return True
        if item.state != item.State.ACCEPTED:
            # A client sees only the proposals they made themselves.
            return item.state == item.State.PROPOSED and item.proposed_by_id == self.request.user.pk
        if self.sees_all:
            return True
        return item.client_team_id is None or item.client_team_id in self.team_ids

    @property
    def sees_tray(self) -> bool:
        return not self.is_client

    # --- what they do -------------------------------------------------------

    @property
    def edits(self) -> bool:
        """The practice owner, and an associate who reaches the company."""
        return self.role in (Role.FF, Role.CF)

    def _client_adds(self) -> bool:
        return self.scope is not None and self.scope.may_make("task")

    def may_add(self, horizon) -> bool:
        """Straight onto the plan."""
        if self.edits:
            return True
        return horizon in TEAM_HORIZONS and self._client_adds()

    def may_propose(self, horizon) -> bool:
        """Into the practice's tray: the client owner and senior leadership,
        at the year and the quarter."""
        return (self.is_client and horizon in PROPOSED_FROM_CLIENT and self.sees_all
                and self.scope is not None and self.scope.acts)

    def may_edit(self, item) -> bool:
        if self.edits:
            return True
        if not self.is_client or item.state != item.State.ACCEPTED:
            return False
        if item.horizon not in TEAM_HORIZONS or not self._client_adds():
            return False
        return self.sees_all or item.client_team_id is None or item.client_team_id in self.team_ids

    @property
    def may_close(self) -> bool:
        return self.edits

    @property
    def may_draft(self) -> bool:
        return self.edits

    def describe(self) -> dict:
        return {"horizons": list(self.horizons), "edits": self.edits,
                "may_close": self.may_close, "may_draft": self.may_draft,
                "sees_tray": self.sees_tray,
                "may_add": [h for h in ALL if self.may_add(h)],
                "may_propose": [h for h in ALL if self.may_propose(h)]}


def company_for(request, company_id):
    """The company the plan is of, once the person is known to reach it;
    404 otherwise (another company, another practice, or no Command Center)."""
    from apps.crm import permissions as crm_perms
    from apps.crm.models import Company
    from apps.scorecard.practice import practice_company

    membership = getattr(request, "membership", None)
    if membership is None or not available(membership.tenant_id):
        raise Http404
    role = membership.role
    if str(company_id) == PRACTICE_KEY:
        if role not in (Role.FF, Role.CF, Role.VA):
            raise Http404
        return practice_company(membership.tenant)
    if role in CLIENT_ROLES:
        if str(company_id) == "mine" or str(company_id) == str(membership.client_company_id):
            company = Company.objects.filter(pk=membership.client_company_id).first()
            if company is None:
                raise Http404
            return company
        raise Http404
    try:
        found = crm_perms.company_queryset_for(request, Company.objects.filter(
            pk=company_id, deleted_at__isnull=True)).first()
    except (ValueError, TypeError, ValidationError):
        found = None
    if found is None:
        # The practice's own row, asked for by its id.
        practice = practice_company(membership.tenant)
        if str(practice.pk) == str(company_id) and role in (Role.FF, Role.CF, Role.VA):
            return practice
        raise Http404
    return found


def access_for(request, company_id) -> PlanAccess:
    return PlanAccess(request, company_for(request, company_id))
