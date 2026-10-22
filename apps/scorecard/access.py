"""Who sees and enters what on a scorecard (spec, "Who sees what"). Written
once, here, and asked by every route: a page or a KPI a person may not see is
absent from what the API sends, and a route that names it answers 404.

Audiences reuse the company's Teams card (P7), read on every request, so a
change of level or team shows at once and nothing is copied.

| Audience | Who sees the KPI |
|---|---|
| Everyone at the company | Every portal user of the company, Viewers included |
| Senior leadership and up | Senior leadership and the client owner |
| A team | Anyone on that team, plus senior leadership and the client owner |
| Each person sees their own | Each tracked person; their manager; senior leadership and the owner |

A page has an audience and a KPI narrows it, never widens it. Senior
leadership is the level on any team, or senior leadership of every team.

**Per-person rows** never reach a colleague (the leak rule): a member is sent
their own row and nothing else, in the trend, the total and the entry form
alike; a manager is sent the rows of the people on the teams they manage;
senior leadership, the client owner and the practice all of them. A total is
worked out only from the rows the reader is sent, and not at all for someone
who is sent only their own.

**The leaderboard switch is the practice's consent to share** (Bryan, after
part 1): with it on, everyone in the KPI's audience, members included, is
sent every row, ranked with names and values. It shares what is shown and
nothing more: who may enter a row, and a reading's history, stay as above.

**A computed KPI** is shown only to someone who sees both the KPIs it is
worked out from, so it can never reveal one of them; nobody enters it.

**Entering readings** (decision 4): the practice owner and associates always
may; the client owner and senior leadership may enter any reading; anyone
else where they are the KPI's reading owner, an assistant included. On a
per-person KPI a tracked person may also enter their own row. A Viewer never
enters anything. The reading owner enters the rows they cover: the client
owner, senior leadership and the practice everyone's, a manager their team's,
a member their own.

**Practice users** see every KPI of the companies they reach (an associate:
the companies assigned to them). Only the practice owner and associates set
a scorecard up; an assistant sees it and enters what they own.
"""

from __future__ import annotations

from django.http import Http404

from apps.crm import permissions as crm_perms
from apps.tenancy.models import CLIENT_ROLES, Role


def _live_kpis(page):
    from .models import Kpi

    return Kpi.all_objects.filter(page=page, archived_at__isnull=True)


def _tracked(kpi) -> set:
    from .models import KpiPerson

    return set(KpiPerson.all_objects.filter(kpi=kpi).values_list("membership_id", flat=True))


class Reader:
    """One person's place on one company's scorecard, read once a request."""

    def __init__(self, request, company):
        from apps.work.permissions import client_scope
        from apps.work.teams import Level

        self.request = request
        self.company = company
        self.membership = request.membership
        self.role = self.membership.role
        self.user_id = self.membership.user_id
        self.is_client = self.role in CLIENT_ROLES
        self.scope = client_scope(request) if self.is_client else None
        if self.scope is not None:
            self.levels = dict(self.scope.levels)
            self.sees_all = self.scope.is_owner or self.scope.leads_all \
                or Level.LEADER in self.levels.values()
            self.only_looks = not self.scope.acts
            self.managed_teams = {team for team, level in self.levels.items()
                                  if level == Level.MANAGER}
        else:
            self.levels = {}
            self.sees_all = True
            self.only_looks = False
            self.managed_teams = set()
        self._managed_people = None

    # --- who they are ---------------------------------------------------------

    @property
    def is_practice(self) -> bool:
        return not self.is_client

    @property
    def sets_up(self) -> bool:
        """Defines KPIs, pages and audiences: the practice owner and associates
        (decided after the mock-up: only the practice, to start)."""
        return self.role in (Role.FF, Role.CF)

    @property
    def enters_any(self) -> bool:
        """May enter any reading: the practice owner and associates, the
        client owner and senior leadership."""
        if self.is_practice:
            return self.sets_up
        return self.sees_all and not self.only_looks

    # --- what they see ----------------------------------------------------------

    def _audience_allows(self, audience, team, *, per_person=False):
        if self.sees_all:
            return True
        if audience in ("everyone", "page"):
            return True
        if audience == "leadership":
            return False
        if audience == "team":
            # An archived team reads as senior leadership and up.
            return team is not None and team.archived_at is None and team.pk in self.levels
        if audience == "each_person":
            return per_person
        return False

    def sees_page(self, page, kpis=None) -> bool:
        """A page is listed when its audience allows the reader and, for
        anyone short of senior leadership, it holds a KPI they see."""
        if not self._audience_allows(page.audience, page.team, per_person=True):
            return False
        if self.sees_all:
            return True
        kpis = _live_kpis(page) if kpis is None else kpis
        return any(self.sees_kpi(kpi) for kpi in kpis)

    def sees_kpi(self, kpi) -> bool:
        page = kpi.page
        if page.archived_at is not None and not self.is_practice:
            return False
        if not self._audience_allows(page.audience, page.team, per_person=kpi.per_person):
            return False
        if not self._audience_allows(kpi.audience, kpi.audience_team,
                                     per_person=kpi.per_person):
            return False
        if kpi.is_computed and not all(
                source is not None and source.archived_at is None and self.sees_kpi(source)
                for source in (kpi.source_a, kpi.source_b)):
            return False
        if self.sees_all:
            return True
        if kpi.per_person:
            # Someone who would be sent no row at all is not shown the KPI.
            return bool(self.rows_of(kpi))
        if "each_person" in (page.audience, kpi.audience):
            return False
        return True

    def managed_people(self) -> set:
        """The memberships on the teams this person manages."""
        if self._managed_people is None:
            from apps.work.models import ClientTeamMember

            self._managed_people = set(ClientTeamMember.all_objects.filter(
                tenant_id=self.company.tenant_id, team_id__in=self.managed_teams,
                team__archived_at__isnull=True,
                team__client_company_id=self.company.pk,
            ).values_list("membership_id", flat=True)) if self.managed_teams else set()
        return self._managed_people

    def covered_rows(self, kpi, tracked=None):
        """The rows that are this person's own business: their own, and their
        team's if they manage it; every row for senior leadership and up."""
        tracked = set(_tracked(kpi)) \
            if tracked is None else set(tracked)
        if self.sees_all:
            return tracked
        mine = {self.membership.pk} | self.managed_people()
        return tracked & mine

    def rows_of(self, kpi, tracked=None):
        """The memberships whose rows this person is sent on a per-person KPI,
        asked once the KPI's audience has let them in. With the leaderboard on,
        every row; under "each person sees their own" the audience is the
        tracked people and their managers, so only they get the board."""
        tracked = set(_tracked(kpi)) \
            if tracked is None else set(tracked)
        covered = self.covered_rows(kpi, tracked)
        if self.sees_all or not kpi.leaderboard:
            return covered
        if "each_person" in (kpi.page.audience, kpi.audience) and not covered:
            return set()
        return tracked

    def sees_only_own_row(self, kpi, tracked=None) -> bool:
        return not self.sees_all and self.rows_of(kpi, tracked) <= {self.membership.pk}

    # --- what they enter --------------------------------------------------------

    def may_enter(self, kpi) -> bool:
        if kpi.is_computed or not self.sees_kpi(kpi) or self.only_looks:
            return False
        if self.enters_any or kpi.reading_owner_id == self.user_id:
            return True
        if kpi.per_person and self.is_client:
            return self.membership.pk in _tracked(kpi)
        return False

    def enters_rows_of(self, kpi, tracked=None) -> set:
        """On a per-person KPI, the rows this person may enter."""
        tracked = set(_tracked(kpi)) \
            if tracked is None else set(tracked)
        if not self.may_enter(kpi):
            return set()
        if self.enters_any:
            return tracked
        if kpi.reading_owner_id == self.user_id:
            if self.is_practice:
                return tracked
            return self.covered_rows(kpi, tracked)
        return tracked & {self.membership.pk}

    def sees_history_of(self, kpi) -> bool:
        """A reading's history is one click away for anyone who can enter it."""
        return self.may_enter(kpi)


def company_for(request, company_id):
    """The company the scorecard is asked for, or 404. A client user's own
    company and only theirs, whatever is asked; an associate the companies
    assigned to them."""
    from apps.crm.models import Company
    from apps.work.views import _is_uuid

    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    if membership.role in CLIENT_ROLES:
        if company_id and str(company_id) != str(membership.client_company_id):
            raise Http404
        company = Company.objects.filter(pk=membership.client_company_id,
                                         deleted_at__isnull=True).first()
    elif membership.role in crm_perms.TENANT_ROLES:
        if not _is_uuid(str(company_id or "")):
            raise Http404
        company = crm_perms.company_queryset_for(
            request, Company.objects.filter(pk=company_id, deleted_at__isnull=True)).first()
    else:
        company = None
    if company is None:
        raise Http404
    return company
