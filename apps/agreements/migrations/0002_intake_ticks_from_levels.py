"""Owner, 2026-11-23: intake's permission is a tick on one screen, no longer
the team-level rule. So nobody loses intake on the day it changes, everyone
the old rule let in gets the intake tick: for each company with intake forms
on, its Client owner, anyone with Senior leadership of all its teams, and
anyone at Manager or Senior leadership on one of its teams (active only).
Adds rows; changes and removes none. Reads and writes through each model's
base manager: a migration runs with no practice bound. Reversing it removes only the rows it
would have made, and only where nothing else is ticked on them."""

from django.db import migrations


def _old_rule(apps, company):
    Membership = apps.get_model("tenancy", "Membership")
    Member = apps.get_model("work", "ClientTeamMember")
    on_teams = set(Member._base_manager.filter(
        team__client_company_id=company.pk, team__archived_at__isnull=True,
        level__in=["manager", "leader"], membership__revoked_at__isnull=True)
        .values_list("membership_id", flat=True))
    out = []
    for m in Membership._base_manager.filter(tenant_id=company.tenant_id,
                                             client_company_id=company.pk,
                                             role__in=["FCC", "ECC"], revoked_at__isnull=True):
        if m.role == "FCC" or m.leads_all_teams or m.pk in on_teams:
            out.append(m)
    return out


def forwards(apps, schema_editor):
    Company = apps.get_model("crm", "Company")
    StaffAccess = apps.get_model("agreements", "StaffAccess")
    for company in Company._base_manager.filter(intake_forms_enabled=True,
                                                deleted_at__isnull=True):
        for m in _old_rule(apps, company):
            row, made = StaffAccess._base_manager.get_or_create(
                tenant_id=company.tenant_id, company_id=company.pk, user_id=m.user_id,
                defaults={"intake": True})
            if not made and not row.intake:
                row.intake = True
                row.save(update_fields=["intake"])


def backwards(apps, schema_editor):
    Company = apps.get_model("crm", "Company")
    StaffAccess = apps.get_model("agreements", "StaffAccess")
    for company in Company._base_manager.filter(intake_forms_enabled=True,
                                                deleted_at__isnull=True):
        users = [m.user_id for m in _old_rule(apps, company)]
        StaffAccess._base_manager.filter(company_id=company.pk, user_id__in=users, intake=True,
                                   agreements=False, signed_pdfs=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("agreements", "0001_initial"),
        ("crm", "0062_alter_outboxmessage_producer"),
        ("tenancy", "0025_sop_studio"),
        ("work", "0016_intake_task_source"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
