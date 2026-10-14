"""Who sees and changes what in the task engine. Source: `03_access_matrix.md` §7.

Scopes, per the matrix:

- **FF, VA** — everything in the tenant.
- **CF** — `assigned` client companies, **plus `own-work`**: anything they own
  or are assigned, whatever company it sits on, the practice's internal work
  included. A task reaches them by a fourth path as well — the contact it hangs
  off, if that contact is in their FR-1.9c universe. (Matrix 7.1 said
  `assigned` alone until 2026-09-17; the owner ruled the code right and the row
  wrong. A CF's own work is theirs: work assigned to someone who cannot see it
  is a bug, not a scope.)
- **FCC, ECC** — their own company only, and for tasks only client-visible
  ones (FR-3.13). Out of scope is 404, never 403.

FR-3.9a is one rule, written once, in `client_may_edit`.

**P7, client teams** (`docs/p7_client_teams_permissions.md` §2, §3) divides
the client's side of the work among the client's people, and is written once
too, in `ClientScope`. It narrows inside the limits above and never widens
past them (P7-4): FR-3.13 and FR-3.9a are asked first, and a level is asked
only after they have said yes.

| | Goals | Work in their team | Work in other teams |
|---|---|---|---|
| Viewer | see | see all | see all |
| Member | see | see and edit theirs | theirs only |
| Manager | see | see and edit all | see all |
| Senior leadership | see, edit | see and edit all, in the teams they lead | see all |
| Client owner | see, edit | see and edit all | (every team is theirs) |

"Theirs" is assigned to them, created by them, or in a project that is
theirs; a project is theirs when they created it or are its client-side
owner (P7-3). The practice's roles are not touched by any of it.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from apps.crm import permissions as crm_perms
from apps.tenancy.models import CLIENT_ROLES, MayCreate, Membership, Role


def _membership(request):
    return getattr(request, "membership", None)


def is_client(request) -> bool:
    membership = _membership(request)
    return membership is not None and membership.role in CLIENT_ROLES


# ---------------------------------------------------------- P7, client teams

#: What each may-create setting allows, least first.
_MAY_CREATE = {MayCreate.NOTHING: 0, MayCreate.TASKS: 1, MayCreate.PROJECTS: 2,
               MayCreate.GOALS: 3}
_NEEDS = {"task": 1, "project": 2, "goal": 3}


class ClientScope:
    """One client user's place in their company: the teams they are on and at
    what level, and what they may create. Read once a request.

    A level is held on a team. The client owner's is not held at all: they
    have everything, in every team. `leads_all_teams` is senior leadership of
    every team; senior leadership of selected teams is the level on each.
    """

    def __init__(self, membership):
        from apps.work.models import ClientTeamMember

        self.membership = membership
        self.tenant_id = membership.tenant_id
        self.user_id = membership.user_id
        self.company_id = membership.client_company_id
        self.contact_id = membership.contact_id
        self.is_owner = membership.role == Role.FCC
        self.leads_all = bool(membership.leads_all_teams)
        self.may_create = membership.may_create
        # Only teams of their own company, and only live ones: a row left
        # from another company or an archived team gives nothing.
        self.levels = dict(ClientTeamMember.all_objects.filter(
            tenant_id=self.tenant_id, membership=membership,
            team__client_company_id=self.company_id, team__archived_at__isnull=True,
        ).values_list("team_id", "level"))
        self._default_team_id = False

    # --- what the levels add up to ------------------------------------------

    @property
    def acts(self) -> bool:
        """Does anything at all: not someone who only looks. A viewer, and a
        person on no team, changes and creates nothing."""
        from apps.work.teams import Level

        return self.is_owner or self.leads_all or any(
            level != Level.VIEWER for level in self.levels.values())

    @property
    def sees_all(self) -> bool:
        """Sees every project and client-visible task of the company: all but
        a member, who sees their own."""
        from apps.work.teams import Level

        return self.is_owner or self.leads_all or any(
            level != Level.MEMBER for level in self.levels.values())

    @property
    def edits_goals(self) -> bool:
        """A goal is the company's, not a team's (P7-2): any senior leader
        and the client owner."""
        from apps.work.teams import Level

        return self.is_owner or self.leads_all or Level.LEADER in self.levels.values()

    def runs(self, team_id) -> bool:
        """Sees and edits everything in this team: its manager or senior
        leader, or the client owner."""
        from apps.work.teams import Level

        return self.is_owner or self.leads_all or self.levels.get(team_id) in (
            Level.MANAGER, Level.LEADER)

    def works_in(self, team_id) -> bool:
        """On this team to do work, at any level but viewer."""
        from apps.work.teams import Level

        return self.runs(team_id) or self.levels.get(team_id) == Level.MEMBER

    def led_team_ids(self) -> set:
        from apps.work.teams import Level

        return {team for team, level in self.levels.items() if level == Level.LEADER}

    # --- which team a thing belongs to --------------------------------------

    @property
    def default_team_id(self):
        if self._default_team_id is False:
            from apps.work import teams

            self._default_team_id = teams.default_team_id(self.tenant_id, self.company_id)
        return self._default_team_id

    def team_of(self, entity):
        """A project's team is its own. A task's is its project's, or its own
        when it is in none (§1.2). One that was never given a team is the
        default team's."""
        from apps.crm.models import Task

        if isinstance(entity, Task) and entity.project_id:
            entity = entity.project
        return entity.client_team_id or self.default_team_id

    # --- "theirs" ------------------------------------------------------------

    def project_is_theirs(self, project) -> bool:
        if project.created_by_client and project.owner_id == self.user_id:
            return True
        return self.contact_id is not None \
            and project.client_owner_contact_id == self.contact_id

    def task_is_theirs(self, task) -> bool:
        from apps.work.services import creator_of

        if task.assignee_id == self.user_id:
            return True
        if task.project_id and self.project_is_theirs(task.project):
            return True
        creator = creator_of(task)
        return creator is not None and creator.pk == self.user_id

    def _their_projects(self) -> Q:
        theirs = Q(created_by_client=True, owner_id=self.user_id)
        if self.contact_id is not None:
            theirs |= Q(client_owner_contact_id=self.contact_id)
        return theirs

    def _their_tasks(self) -> Q:
        """Assigned to them or created by them. The creator is the actor of
        the task's CREATED update: a task has no column for it."""
        from apps.work.models import TaskUpdate

        created = TaskUpdate.all_objects.filter(
            task_id=OuterRef("pk"), kind=TaskUpdate.Kind.CREATED, actor_id=self.user_id)
        return Q(assignee_id=self.user_id) | Exists(created)

    def projects(self, queryset):
        """The company's projects this person sees. A member also sees the
        project one of their tasks sits in, by name, with only their own
        tasks under it (P7-5): `tasks` is what keeps the rest out."""
        from apps.crm.models import Task

        queryset = queryset.filter(client_company_id=self.company_id)
        if self.sees_all:
            return queryset
        holding = Task.all_objects.filter(
            self._their_tasks(), tenant_id=self.tenant_id,
            client_company_id=self.company_id, is_client_visible=True,
            deleted_at__isnull=True, project_id__isnull=False).values("project_id")
        return queryset.filter(self._their_projects() | Q(pk__in=holding))

    def tasks(self, queryset):
        from apps.work.models import Project

        # FR-3.13 — own company, client-visible only. No level reaches past it.
        queryset = queryset.filter(client_company_id=self.company_id,
                                   is_client_visible=True)
        if self.sees_all:
            return queryset
        theirs = Project.all_objects.filter(
            self._their_projects(), tenant_id=self.tenant_id,
            client_company_id=self.company_id).values("pk")
        return queryset.filter(self._their_tasks() | Q(project_id__in=theirs))

    # --- what they may do -----------------------------------------------------

    def may_change_task(self, task) -> bool:
        """Asked after FR-3.9a has said yes."""
        if not self.acts:
            return False
        return self.runs(self.team_of(task)) or self.task_is_theirs(task)

    def may_change_project(self, project) -> bool:
        if not self.acts:
            return False
        return self.runs(self.team_of(project)) or self.project_is_theirs(project)

    def may_make(self, kind: str) -> bool:
        """`kind` is task, project or goal (§3). Someone who only looks makes
        nothing, whatever their setting says."""
        return self.acts and _MAY_CREATE.get(self.may_create, 0) >= _NEEDS[kind]

    def takes_work_in(self, team_id) -> bool:
        """Can be handed a task of this team."""
        return self.is_owner or self.leads_all or self.works_in(team_id)


def client_scope(request) -> ClientScope | None:
    """The requester's `ClientScope`, or None for anyone at the practice.
    While someone is acting as a colleague, it is the colleague's."""
    membership = _membership(request)
    if membership is None or membership.role not in CLIENT_ROLES:
        return None
    held = getattr(request, "_client_scope", None)
    if held is None or held.membership.pk != membership.pk:
        held = ClientScope(membership)
        try:
            request._client_scope = held
        except AttributeError:       # a stand-in request that takes no attributes
            pass
    return held


def _company_scope(request, queryset, company_field="client_company_id"):
    role = crm_perms.role_of(request)
    membership = _membership(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        return queryset.filter(
            Q(**{f"{company_field}__in": crm_perms.assigned_company_ids(request)})
            | Q(owner_id=membership.user_id)
        )
    if role in CLIENT_ROLES:
        return queryset.filter(**{company_field: membership.client_company_id})
    return queryset.none()


def goal_queryset_for(request, queryset):
    return _company_scope(request, queryset)


def project_queryset_for(request, queryset):
    scope = client_scope(request)
    if scope is not None:
        return scope.projects(queryset)
    return _company_scope(request, queryset)


def task_queryset_for(request, queryset):
    """A task reaches a CF by four paths, not one: the company is assigned, the
    contact it hangs off is theirs (Phase 1 stage-rule tasks), they own it, or
    it is assigned to them. The last two hold regardless of company — matrix
    7.1's `own-work`."""
    role = crm_perms.role_of(request)
    membership = _membership(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        from apps.crm.models import Contact

        visible_contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.all()
        ).values("pk")
        return queryset.filter(
            Q(client_company_id__in=crm_perms.assigned_company_ids(request))
            | Q(contact_id__in=visible_contacts)
            | Q(owner_id=membership.user_id)
            | Q(assignee_id=membership.user_id)
        )
    if role in CLIENT_ROLES:
        return client_scope(request).tasks(queryset)
    return queryset.none()


def report_task_queryset_for(request, queryset):
    """The tasks a goal's progress is worked out from. For a client user that
    is every client-visible task of their company, whatever their level: the
    value report keeps its audience (decided 2026-10-12), and a goal's
    progress is the same number for everyone who sees the goal."""
    membership = _membership(request)
    if membership is not None and membership.role in CLIENT_ROLES:
        return queryset.filter(client_company_id=membership.client_company_id,
                               is_client_visible=True)
    return task_queryset_for(request, queryset)


def comment_queryset_for(request, queryset):
    """AC-3.4 — an internal comment must be ABSENT from a client's response,
    not merely hidden in the UI."""
    from apps.work.models import Comment

    if is_client(request):
        return queryset.filter(visibility=Comment.Visibility.SHARED)
    return queryset


def is_client_side_user(tenant_id, user_id, company_id) -> bool:
    if user_id is None:
        return False
    return Membership.all_objects.filter(
        tenant_id=tenant_id, user_id=user_id, role__in=CLIENT_ROLES,
        client_company_id=company_id, revoked_at__isnull=True,
    ).exists()


def client_may_edit(request, task) -> bool:
    """FR-3.9a, the whole rule:

    > A client user may edit, change the status of, and reassign any task that
    > is client-visible, in their own company, and either assigned to a
    > client-side user or created by a client user.

    So a task assigned to a fractional is read-only to the client apart from
    shared comments: if the fractional owns the work, the client asks.
    """
    membership = _membership(request)
    if membership is None or membership.role not in CLIENT_ROLES:
        return False
    if not task.is_client_visible or task.client_company_id != membership.client_company_id:
        return False
    if not task.created_by_client and not is_client_side_user(
            task.tenant_id, task.assignee_id, membership.client_company_id):
        return False
    # P7: inside that, by level. A manager of the task's team, or its own.
    return client_scope(request).may_change_task(task)


def client_may_delete(request, task) -> bool:
    """FR-3.9a.3 — narrower than editing: a task a client made, deleted by
    whoever made it. Deleting work the practice made or assigned is not a
    client's call, at any level.

    P7-13, as Bryan ruled on 2026-10-13 and 10-14: the client owner may
    delete a colleague's task as well, as they may a colleague's project. A
    manager or a senior leader cancels it."""
    from apps.work.services import creator_of

    membership = _membership(request)
    if not client_may_edit(request, task) or not task.created_by_client:
        return False
    if membership.role == Role.FCC:
        return True
    creator = creator_of(task)
    return creator is not None and creator.pk == membership.user_id


def client_may_assign_to(request, user_id, team_id=None) -> bool:
    """FR-3.9a.2 — a client hands work to a colleague, never to a fractional
    and never outside the company.

    P7, when the task's team is given: to someone on that team (§2.2, §2.3).
    A senior leader may also hand it to someone on any team they lead, and
    the client owner to anyone who takes work at all. Never to someone who
    only looks."""
    membership = _membership(request)
    if user_id is None:
        return True
    colleague = Membership.all_objects.filter(
        tenant_id=membership.tenant_id, user_id=user_id, role__in=CLIENT_ROLES,
        client_company_id=membership.client_company_id, revoked_at__isnull=True,
    ).first()
    if colleague is None:
        return False
    theirs, mine = ClientScope(colleague), client_scope(request)
    if not theirs.acts:
        return False
    if team_id is None or theirs.takes_work_in(team_id) or mine.is_owner or mine.leads_all:
        return True
    return any(theirs.takes_work_in(team) for team in mine.led_team_ids())


def client_may_edit_project(request, project) -> bool:
    """A client user edits a project their company's people made, and never
    one the practice made: that was the whole rule before P7 and is still the
    outer limit. Inside it, by level: a manager of its team, or their own."""
    scope = client_scope(request)
    if scope is None or project.client_company_id != scope.company_id \
            or not project.created_by_client:
        return False
    return scope.may_change_project(project)


def client_may_delete_project(request, project) -> bool:
    """P7-13, which Bryan ruled on 2026-10-13 covers projects as it does
    tasks: a client's project is deleted by whoever made it, or by the client
    owner. A manager or a senior leader cancels it. Before P7 any client user
    of the company could delete a colleague's project: this is the one thing
    phase 1 takes away on the day it is released."""
    scope = client_scope(request)
    if scope is None or project.client_company_id != scope.company_id \
            or not project.created_by_client:
        return False
    return scope.is_owner or (scope.acts and project.owner_id == scope.user_id)


def client_may_edit_goal(request, goal) -> bool:
    """P7 §2.1 — a senior leader and the client owner edit any goal of their
    company. **Not asked by any route yet:** goals stay the practice's to
    change until phase 4 opens it, with the say on which fields."""
    scope = client_scope(request)
    return scope is not None and goal.client_company_id == scope.company_id \
        and scope.edits_goals


def client_may_create(request, kind: str) -> bool:
    """P7 §3 — `kind` is task, project or goal."""
    scope = client_scope(request)
    return scope is not None and scope.may_make(kind)


def client_may_comment(request) -> bool:
    """Whoever sees a thing may add a shared comment on it (§2.6), except
    someone who only looks: a comment is something made."""
    scope = client_scope(request)
    return scope is not None and scope.acts


class NotTheirTeam(Exception):
    """The place a client user asked to put new work is not one of theirs."""


def client_team_for_new(request, *, project=None, wanted=None):
    """The team a client user's new project or task belongs to (§1.2).

    In a project: the project's, and only where they work in that team or the
    project is theirs. Otherwise the team they named, if they work in it;
    their own, if they are on one; and with several and none named, the
    default team if they are on it, else the first by name."""
    from apps.work.models import ClientTeam

    scope = client_scope(request)
    if project is not None:
        team_id = scope.team_of(project)
        if not (scope.works_in(team_id) or scope.project_is_theirs(project)):
            raise NotTheirTeam("That project is another team's. You can add work on "
                               "your own team.")
        return team_id
    live = ClientTeam.all_objects.filter(
        tenant_id=scope.tenant_id, client_company_id=scope.company_id,
        archived_at__isnull=True)
    if not (scope.is_owner or scope.leads_all):
        live = live.filter(pk__in=[team for team in scope.levels
                                   if scope.works_in(team)])
    if wanted is not None:
        if not live.filter(pk=wanted).exists():
            raise NotTheirTeam("That team is not one you can add work to.")
        return wanted
    found = live.order_by("-is_default", "name").values_list("pk", flat=True).first()
    return found or scope.default_team_id


def may_write(request, task) -> bool:
    """Tenant staff by role scope; client users by FR-3.9a."""
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.CF, Role.VA):
        return True
    return client_may_edit(request, task)


# ------------------------------------------------ Module 4B — the value report
#
# Matrix §10A draws one line: **judging the client relationship is
# FF-and-assigned-CF; administering it is a VA's too.** Recording a reading and
# exporting a PDF are administration. Resolving a goal, accepting a narrative
# and writing the outcome statement are judgements — a VA who could do them
# could publish a verdict on the engagement that the fractional never reached.

def may_judge(request, company_id) -> bool:
    """Matrix 10A.6, 10A.10, 10A.13 — FF, or a CF assigned to that company."""
    role = crm_perms.role_of(request)
    if role == Role.FF:
        return True
    if role == Role.CF:
        return company_id is not None and company_id in set(
            crm_perms.assigned_company_ids(request))
    return False


def may_administer(request) -> bool:
    """Matrix 10A.4, 10A.7, 10A.15 — any tenant role, never a client. Scope is
    the queryset's job; this is only about the verb."""
    return crm_perms.role_of(request) in (Role.FF, Role.CF, Role.VA)
