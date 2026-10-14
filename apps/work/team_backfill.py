"""P7 phase 1's data step: every client company's default team, with its
people and its work on it (`docs/p7_client_teams_permissions.md` §6, §7).

Read by three callers, so that what is shown and what is done cannot differ:
the migrations (`work` 0010, `crm` 0036), the dry run
(`manage.py client_teams_dry_run`), and the test that a portal user reaches
exactly what they reached before.

It takes an app registry, the migration's historical one or the live one,
and uses nothing of a model but its columns. **Do not change what it does
after `work` 0010 has been released**; a later change is a new migration.
"""

from __future__ import annotations

DEFAULT_NAME = "Everyone"
#: What every client user could see and do before P7 (P7-1).
LEVEL = "manager"
CLIENT_ROLES = ("FCC", "ECC")


def _rows(apps, app, name):
    return apps.get_model(app, name)._base_manager


def plan(apps) -> list[dict]:
    """A row for every company that gets a default team: one with a live
    portal user, a project, or a task. Reads only columns that were there
    before P7, so it can be run before the migration and after."""
    companies: dict = {}

    def of(tenant_id, company_id) -> dict:
        return companies.setdefault((tenant_id, company_id), {
            "tenant_id": tenant_id, "company_id": company_id, "people": [],
            "projects": 0, "tasks_alone": 0, "tasks_in_projects": 0})

    for row in (_rows(apps, "tenancy", "Membership")
                .filter(role__in=CLIENT_ROLES, revoked_at__isnull=True,
                        client_company_id__isnull=False)
                .order_by("role", "user__email")
                .values("pk", "tenant_id", "client_company_id", "role", "user__email")):
        of(row["tenant_id"], row["client_company_id"])["people"].append(
            {"membership_id": row["pk"], "role": row["role"], "email": row["user__email"]})
    for row in (_rows(apps, "work", "Project").filter(client_company_id__isnull=False)
                .values("tenant_id", "client_company_id")):
        of(row["tenant_id"], row["client_company_id"])["projects"] += 1
    for row in (_rows(apps, "crm", "Task").filter(client_company_id__isnull=False)
                .values("tenant_id", "client_company_id", "project_id")):
        key = "tasks_in_projects" if row["project_id"] else "tasks_alone"
        of(row["tenant_id"], row["client_company_id"])[key] += 1

    names = dict(_rows(apps, "crm", "Company").filter(
        pk__in=[company_id for _tenant, company_id in companies])
        .values_list("pk", "name"))
    practices = dict(_rows(apps, "tenancy", "Tenant").values_list("pk", "name"))
    out = []
    for (tenant_id, company_id), row in companies.items():
        out.append({**row, "company": names.get(company_id, ""),
                    "practice": practices.get(tenant_id, "")})
    return sorted(out, key=lambda row: (row["practice"], row["company"],
                                        str(row["company_id"])))


def _default_team(apps, tenant_id, company_id):
    teams = _rows(apps, "work", "ClientTeam")
    found = teams.filter(tenant_id=tenant_id, client_company_id=company_id,
                         is_default=True, archived_at__isnull=True).first()
    if found is None:
        found = teams.create(tenant_id=tenant_id, client_company_id=company_id,
                             name=DEFAULT_NAME, is_default=True)
    return found


def teams_people_and_projects(apps) -> dict:
    """`work` 0010. A person already on a team of their company, and a
    project that already has a team, are left as they are, so running it
    twice changes nothing."""
    members = _rows(apps, "work", "ClientTeamMember")
    done = {"teams": 0, "people": 0, "projects": 0}
    for row in plan(apps):
        team = _default_team(apps, row["tenant_id"], row["company_id"])
        done["teams"] += 1
        for person in row["people"]:
            placed = members.filter(membership_id=person["membership_id"],
                                    team__client_company_id=row["company_id"],
                                    team__archived_at__isnull=True).exists()
            if not placed:
                members.create(tenant_id=row["tenant_id"], team=team,
                               membership_id=person["membership_id"], level=LEVEL)
                done["people"] += 1
        done["projects"] += _rows(apps, "work", "Project").filter(
            tenant_id=row["tenant_id"], client_company_id=row["company_id"],
            client_team__isnull=True).update(client_team=team)
    return done


def tasks(apps) -> dict:
    """`crm` 0036. A task in no project gets its company's default team. A
    task in a project reads its project's, and is left without one."""
    done = {"tasks": 0}
    for row in plan(apps):
        if not row["tasks_alone"]:
            continue
        team = _default_team(apps, row["tenant_id"], row["company_id"])
        done["tasks"] += _rows(apps, "crm", "Task").filter(
            tenant_id=row["tenant_id"], client_company_id=row["company_id"],
            project__isnull=True, client_team__isnull=True).update(client_team=team)
    return done


def undo_tasks(apps) -> None:
    _rows(apps, "crm", "Task").filter(client_team__isnull=False).update(client_team=None)


def undo_teams(apps) -> None:
    """The reverse of `work` 0010's step: the rows it made. The tables go
    with the migration itself."""
    _rows(apps, "work", "Project").filter(client_team__isnull=False).update(
        client_team=None)
    _rows(apps, "work", "ClientTeamMember").all().delete()
    _rows(apps, "work", "ClientTeam").all().delete()


def say(rows: list[dict]) -> str:
    """The plan in words, a company at a time: before, and after."""
    out = []
    for row in rows:
        people = ", ".join(f"{p['email']} ({'client owner' if p['role'] == 'FCC' else 'client team member'})"
                           for p in row["people"]) or "nobody"
        out += [
            f"{row['practice']} / {row['company']}",
            f"  before: {len(row['people'])} portal user(s): {people}",
            f"          {row['projects']} project(s), {row['tasks_alone']} task(s) in no "
            f"project, {row['tasks_in_projects']} task(s) in projects; no teams",
            f"  after:  one team, \"{DEFAULT_NAME}\" (the default); "
            f"{len(row['people'])} on it as Manager; {row['projects']} project(s) and "
            f"{row['tasks_alone']} task(s) on it; the {row['tasks_in_projects']} task(s) in "
            "projects follow their project",
        ]
    totals = {key: sum(row[key] for row in rows)
              for key in ("projects", "tasks_alone", "tasks_in_projects")}
    out.append(f"TOTAL: {len(rows)} default team(s); "
               f"{sum(len(row['people']) for row in rows)} portal user(s) placed as Manager; "
               f"{totals['projects']} project(s) and {totals['tasks_alone']} task(s) given a "
               f"team; {totals['tasks_in_projects']} task(s) left to follow their project. "
               "Nobody's may-create or senior leadership is changed.")
    return "\n".join(out)
