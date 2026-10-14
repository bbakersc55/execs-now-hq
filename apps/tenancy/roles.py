"""What each role is called wherever a person reads it (P1, owner 2026-10-02).

The codes stay in code and data. These names are the only thing shown. The
frontend's twin is `frontend/src/lib/roles.ts`, and
`tests/test_vocabulary.py` keeps the two identical.
"""

from __future__ import annotations

ROLE_LABEL = {
    "FF": "Practice owner",
    "CF": "Associate",
    "VA": "Assistant",
    "FCC": "Client owner",
    "ECC": "Client team member",
}

#: Shown for a code this list does not know: never the code itself.
UNKNOWN_ROLE = "Team member"


def role_label(code: str | None) -> str:
    return ROLE_LABEL.get(code or "", UNKNOWN_ROLE)


# P7: a client user's level on a team, and what they may create. Shown in
# place of "Client team member" wherever a client user is listed (P7-10); the
# client owner stays "Client owner". The codes are the schema's.
LEVEL_LABEL = {
    "viewer": "Viewer",
    "member": "Member",
    "manager": "Manager",
    "leader": "Senior leadership",
}
#: Least first: the level shown for someone on several teams is the highest.
LEVEL_ORDER = ("viewer", "member", "manager", "leader")
ON_NO_TEAM = "On no team"

MAY_CREATE_LABEL = {
    "nothing": "Nothing",
    "tasks": "Tasks only",
    "projects": "Projects and tasks",
    "goals": "Goals too",
}


def level_label(role: str | None, levels=(), leads_all_teams: bool = False) -> str:
    """What a client user is called where they are listed: "Client owner", or
    the highest level they hold on any team."""
    if role == "FCC":
        return ROLE_LABEL["FCC"]
    if leads_all_teams:
        return LEVEL_LABEL["leader"]
    held = [level for level in LEVEL_ORDER if level in set(levels)]
    return LEVEL_LABEL[held[-1]] if held else ON_NO_TEAM
