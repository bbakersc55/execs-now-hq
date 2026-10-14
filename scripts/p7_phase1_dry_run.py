"""P7 phase 1's data step, as a dry run for a database that does not have P7 yet.

`manage.py client_teams_dry_run` arrives with the release, and the dry run is
wanted before it. This reads the same thing from code that has never heard of
a team: it uses only columns that exist before `work` 0010, and writes
nothing. Piped into a shell, as the demo's pre-check is:

    railway ssh --service execs-now-hq -- "echo $(base64 -w0 scripts/p7_phase1_dry_run.py) | base64 -d | python manage.py shell"

`tests/test_client_teams.py` holds its output to `team_backfill.say(plan)`,
word for word, so what is read here is what the migration will do.
"""

from django.apps import apps

CLIENT_ROLES = ("FCC", "ECC")
NAME = "Everyone"


def _rows(app, name):
    return apps.get_model(app, name)._base_manager


def plan():
    companies = {}

    def of(tenant_id, company_id):
        return companies.setdefault((tenant_id, company_id), {
            "people": [], "projects": 0, "tasks_alone": 0, "tasks_in_projects": 0})

    for row in (_rows("tenancy", "Membership")
                .filter(role__in=CLIENT_ROLES, revoked_at__isnull=True,
                        client_company_id__isnull=False)
                .order_by("role", "user__email")
                .values("tenant_id", "client_company_id", "role", "user__email")):
        of(row["tenant_id"], row["client_company_id"])["people"].append(
            (row["user__email"], row["role"]))
    for row in (_rows("work", "Project").filter(client_company_id__isnull=False)
                .values("tenant_id", "client_company_id")):
        of(row["tenant_id"], row["client_company_id"])["projects"] += 1
    for row in (_rows("crm", "Task").filter(client_company_id__isnull=False)
                .values("tenant_id", "client_company_id", "project_id")):
        key = "tasks_in_projects" if row["project_id"] else "tasks_alone"
        of(row["tenant_id"], row["client_company_id"])[key] += 1

    names = dict(_rows("crm", "Company").filter(
        pk__in=[company for _tenant, company in companies]).values_list("pk", "name"))
    practices = dict(_rows("tenancy", "Tenant").values_list("pk", "name"))
    out = [{**row, "company": names.get(company, ""), "practice": practices.get(tenant, ""),
            "company_id": company}
           for (tenant, company), row in companies.items()]
    return sorted(out, key=lambda row: (row["practice"], row["company"],
                                        str(row["company_id"])))


def say(rows):
    out = []
    for row in rows:
        people = ", ".join(
            f"{email} ({'client owner' if role == 'FCC' else 'client team member'})"
            for email, role in row["people"]) or "nobody"
        out += [
            f"{row['practice']} / {row['company']}",
            f"  before: {len(row['people'])} portal user(s): {people}",
            f"          {row['projects']} project(s), {row['tasks_alone']} task(s) in no "
            f"project, {row['tasks_in_projects']} task(s) in projects; no teams",
            f"  after:  one team, \"{NAME}\" (the default); "
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


print("DRY RUN. Nothing is written.")
print(say(plan()))
