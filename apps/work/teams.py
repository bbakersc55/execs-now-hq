"""Client teams (P7 §1): the default team, and who is on which.

Phase 1 holds only what the rule in `permissions.py` needs and what keeps
every portal user where they were: a company's default team, and a new
portal user's place on it. Making, renaming and archiving teams, and setting
a person's level, are phase 2.
"""

from __future__ import annotations

from apps.tenancy.models import CLIENT_ROLES
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
