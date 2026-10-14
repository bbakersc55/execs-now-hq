"""Client teams (P7 §1): the default team, and who is on which.

The first half is what the rule in `permissions.py` needs and what keeps
every portal user where they were: a company's default team, and a new
portal user's place on it (phase 1). The second half is setting teams up:
making, renaming and archiving them, a person's level on each, and their two
settings (phase 2).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.tenancy.models import CLIENT_ROLES, Role
from apps.work.models import ClientTeam, ClientTeamMember

Level = ClientTeamMember.Level

#: The level a portal user is given on the default team when nobody has
#: chosen one. Manager is what every client user could see and do before P7
#: (P7-1), so nobody's portal changes by being put there. The invitation form
#: of phase 2 asks for the team and the level, and starts at Member (P7-9).
UNCHOSEN_LEVEL = Level.MANAGER


def default_team(tenant_id, company_id) -> ClientTeam:
    """The company's default team, made if it has none."""
    found = ClientTeam.all_objects.filter(
        tenant_id=tenant_id, client_company_id=company_id, is_default=True,
        archived_at__isnull=True).first()
    if found is None:
        found = ClientTeam.all_objects.create(
            tenant_id=tenant_id, client_company_id=company_id,
            name=ClientTeam.DEFAULT_NAME, is_default=True)
    return found


def default_team_id(tenant_id, company_id):
    """As `default_team`, without making one: None when the company has none."""
    return ClientTeam.all_objects.filter(
        tenant_id=tenant_id, client_company_id=company_id, is_default=True,
        archived_at__isnull=True).values_list("pk", flat=True).first()


def is_placed(membership) -> bool:
    """On at least one live team of their own company."""
    return ClientTeamMember.all_objects.filter(
        membership=membership, team__client_company_id=membership.client_company_id,
        team__archived_at__isnull=True).exists()


def place(team, membership, level) -> ClientTeamMember:
    """Put a client user on a team at a level, or change their level on it.
    Only a client user of the team's own company can be on it."""
    if membership.role not in CLIENT_ROLES \
            or membership.client_company_id != team.client_company_id \
            or membership.tenant_id != team.tenant_id:
        raise ValueError("A team's people are client users of its own company.")
    if level not in Level.values:
        raise ValueError(f"Not a level: {level!r}.")
    row, _ = ClientTeamMember.all_objects.update_or_create(
        team=team, membership=membership,
        defaults={"tenant_id": team.tenant_id, "level": level})
    return row


def place_on_default(membership, level=UNCHOSEN_LEVEL) -> ClientTeamMember | None:
    """A portal user who is on no team of their company joins its default
    team. One who is on a team already is left exactly as they are."""
    if membership.role not in CLIENT_ROLES or membership.client_company_id is None \
            or membership.revoked_at is not None or is_placed(membership):
        return None
    return place(default_team(membership.tenant_id, membership.client_company_id),
                 membership, level)


# ------------------------------------------------- phase 2: setting teams up
#
# Who may: whoever manages that company's portal users (the practice owner,
# or an associate assigned to the company), and the client owner of their
# own company (phase 3, below). Every change is in the audit trail with who made it, as a portal
# role change is.

class TeamError(Exception):
    """Something asked of a team that cannot be done, said in words."""


def _audit(tenant_id, actor, verb, target_type, target_id, **payload):
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant_id=tenant_id, actor=actor, verb=verb,
                                  target_type=target_type, target_id=target_id,
                                  payload=payload)


def live_teams(company):
    return ClientTeam.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, archived_at__isnull=True)


def team_of_company(company, team_id) -> ClientTeam | None:
    """A live team of this company by id, or None: never another company's."""
    try:
        return live_teams(company).filter(pk=team_id).first()
    except (ValueError, TypeError, ValidationError):
        return None


def _clean_name(company, name, *, but=None) -> str:
    name = " ".join(str(name or "").split())[:80]
    if not name:
        raise TeamError("A team needs a name.")
    taken = live_teams(company).filter(name__iexact=name)
    if but is not None:
        taken = taken.exclude(pk=but.pk)
    if taken.exists():
        raise TeamError(f"{company.name} already has a team called {name}.")
    return name


@transaction.atomic
def create_team(company, name, *, actor) -> ClientTeam:
    default_team(company.tenant_id, company.pk)       # a company's first team is its default
    team = ClientTeam.all_objects.create(
        tenant_id=company.tenant_id, client_company=company,
        name=_clean_name(company, name), created_by=actor)
    _audit(company.tenant_id, actor, "client_team.created", "client_team", team.pk,
           company=str(company.pk), name=team.name)
    return team


@transaction.atomic
def rename_team(team, name, *, actor) -> ClientTeam:
    new = _clean_name(team.client_company, name, but=team)
    if new != team.name:
        old, team.name = team.name, new
        team.save(update_fields=["name", "updated_at"])
        _audit(team.tenant_id, actor, "client_team.renamed", "client_team", team.pk,
               **{"from": old, "to": new})
    return team


def _work_on(team):
    """The projects of a team and its tasks that are in no project. A thing
    with no team of its own is the default team's (`permissions.team_of`)."""
    from apps.crm.models import Task
    from apps.work.models import Project

    mine = Q(client_team=team)
    if team.is_default:
        mine |= Q(client_team__isnull=True)
    scope = dict(tenant_id=team.tenant_id, client_company_id=team.client_company_id,
                 deleted_at__isnull=True)
    return (Project.all_objects.filter(mine, **scope),
            Task.all_objects.filter(mine, project__isnull=True, **scope))


def counts(team) -> dict:
    """What a team holds, for its card: its projects, and its open tasks,
    those inside its projects included."""
    from apps.crm.models import Task

    projects, alone = _work_on(team)
    done = (Task.Status.DONE, Task.Status.CANCELLED)
    inside = Task.all_objects.filter(
        tenant_id=team.tenant_id, deleted_at__isnull=True, project__in=projects)
    return {"projects": projects.count(),
            "open_tasks": alone.exclude(status__in=done).count()
            + inside.exclude(status__in=done).count()}


def archive_preview(team) -> dict:
    """What archiving would move, said before it is confirmed (§1.1)."""
    if team.is_default:
        raise TeamError("The default team cannot be archived: it is where a company's "
                        "people and work are when they are on no other.")
    projects, alone = _work_on(team)
    only_here = [row for row in ClientTeamMember.all_objects.filter(team=team)
                 .select_related("membership")
                 if not ClientTeamMember.all_objects.filter(
                     membership=row.membership, team__archived_at__isnull=True,
                     team__client_company_id=team.client_company_id)
                 .exclude(team=team).exists()]
    return {"projects": projects.count(), "tasks": alone.count(),
            "people": ClientTeamMember.all_objects.filter(team=team).count(),
            "people_left_on_no_team": len(only_here),
            "moves_to": default_team(team.tenant_id, team.client_company_id).name,
            "_only_here": only_here}


@transaction.atomic
def archive_team(team, *, actor) -> dict:
    """Its work moves to the default team; its people keep their sign-in
    (P7-12). Someone who was on no other team joins the default team at the
    level they held here, so that nobody is left on no team by an archive."""
    preview = archive_preview(team)
    home = default_team(team.tenant_id, team.client_company_id)
    projects, alone = _work_on(team)
    moved = {"projects": projects.update(client_team=home),
             "tasks": alone.update(client_team=home)}
    for row in preview.pop("_only_here"):
        place(home, row.membership, row.level)
    team.archived_at = timezone.now()
    team.save(update_fields=["archived_at", "updated_at"])
    _audit(team.tenant_id, actor, "client_team.archived", "client_team", team.pk,
           name=team.name, moved_to=str(home.pk), **moved,
           people_moved=preview["people_left_on_no_team"])
    return {**moved, "people_moved": preview["people_left_on_no_team"],
            "moved_to": home.name}


@transaction.atomic
def set_level(team, membership, level, *, actor) -> None:
    """Put a person on a team at a level, change it, or (level None) take
    them off it. Taking someone off their last team is allowed and said: they
    then see only the work that is theirs."""
    before = ClientTeamMember.all_objects.filter(team=team, membership=membership).first()
    old = before.level if before else None
    if level in (None, ""):
        if before is None:
            return
        before.delete()
        _audit(team.tenant_id, actor, "client_team.person_removed", "membership",
               membership.pk, team=str(team.pk), team_name=team.name, level=old)
        return
    try:
        place(team, membership, level)
    except ValueError as exc:
        raise TeamError(str(exc)) from None
    if old != level:
        _audit(team.tenant_id, actor, "client_team.level_set", "membership", membership.pk,
               team=str(team.pk), team_name=team.name, **{"from": old, "to": level})


@transaction.atomic
def set_person(membership, *, actor, may_create=None, leads_all_teams=None) -> None:
    """What a client user may create, and whether they are senior leadership
    of every team. Each change is audited on its own."""
    from apps.tenancy.models import MayCreate

    if membership.role not in CLIENT_ROLES:
        raise TeamError("These are a client user's settings.")
    touched = []
    if may_create is not None and may_create != membership.may_create:
        if may_create not in MayCreate.values:
            raise TeamError("May create is nothing, tasks, projects or goals.")
        _audit(membership.tenant_id, actor, "portal.may_create_changed", "membership",
               membership.pk, **{"from": membership.may_create, "to": may_create})
        membership.may_create = may_create
        touched.append("may_create")
    if leads_all_teams is not None and leads_all_teams != membership.leads_all_teams:
        if not isinstance(leads_all_teams, bool):
            raise TeamError("Senior leadership of every team is yes or no.")
        _audit(membership.tenant_id, actor, "portal.leads_all_teams_changed", "membership",
               membership.pk, **{"from": membership.leads_all_teams, "to": leads_all_teams})
        membership.leads_all_teams = leads_all_teams
        touched.append("leads_all_teams")
    if touched:
        membership.save(update_fields=touched + ["updated_at"])


# ------------------------------------- phase 3: the client owner sets them up
#
# The same card and the same changes as the practice's (§4.2), for their own
# company only, with two limits. A client owner's own settings, and another
# client owner's, are the practice's to set. And a client owner gives nobody
# more to create than they may create themselves: without it, "Goals too"
# given to a colleague would be theirs through "Act as a colleague".

class TeamRefused(TeamError):
    """Not this person's to change: a 403, said in words."""


def practice_name(tenant) -> str:
    from apps.crm.services import email_layout

    brand = email_layout.branding(tenant)
    return brand.display_name or brand.practice_name or "the practice"


def check_client_owner(owner, person, *, may_create=None) -> None:
    """Raises TeamRefused for what a client owner may not change on `person`."""
    from apps.tenancy.models import MayCreate

    if person.role == Role.FCC:
        raise TeamRefused(f"A client owner's settings are set by {practice_name(owner.tenant)}.")
    order = list(MayCreate.values)
    if may_create in order and order.index(may_create) > order.index(owner.may_create):
        raise TeamRefused(
            "You can give someone at most what you may create yourself "
            f"({MayCreate(owner.may_create).label.lower()}). "
            f"{practice_name(owner.tenant)} can change that.")


def overview(company) -> dict:
    """The Teams card: each live team with its people and what it holds, and
    each portal user with their teams, their level on each and their two
    settings."""
    from apps.work import portal

    default_team(company.tenant_id, company.pk)
    teams_ = list(live_teams(company).order_by("-is_default", "name"))
    rows = list(ClientTeamMember.all_objects.filter(team__in=teams_)
                .values_list("team_id", "membership_id", "level"))
    people = list(portal.access_rows(company).order_by("role", "user__email"))
    names = {m.pk: m.user.full_name or m.user.email for m in people}
    return {
        "company": str(company.pk),
        "teams": [{
            "id": str(team.pk), "name": team.name, "is_default": team.is_default,
            **counts(team),
            "people": sorted(({"membership": str(member), "name": names[member],
                               "level": level}
                              for team_id, member, level in rows
                              if team_id == team.pk and member in names),
                             key=lambda row: row["name"].lower()),
        } for team in teams_],
        "people": [{
            "id": str(m.pk), "name": names[m.pk], "email": m.user.email, "role": m.role,
            "may_create": m.may_create, "leads_all_teams": m.leads_all_teams,
            "teams": [{"team": str(team_id), "level": level}
                      for team_id, member, level in rows if member == m.pk],
        } for m in people],
    }


def names_for(company) -> list[dict]:
    """The live teams of a company, for a picker."""
    default_team(company.tenant_id, company.pk)
    return [{"id": str(team.pk), "name": team.name, "is_default": team.is_default}
            for team in live_teams(company).order_by("-is_default", "name")]
