"""The "Set up KPIs from a sheet" walk's setup, on a seeded demo copy
(2026-11-17).

    DATABASE_URL=postgres:///execsnowhq_walk .venv/bin/python manage.py scorecard_sheet_walk_setup

**Not product code, and laptop only**: it refuses unless APP_ENVIRONMENT is
local and the database's name ends in `_walk`. The laptop has no Google
connection (its database is a scrubbed copy), so it gives the demo's practice
owner a Google connection row with the Sheets scope and no tokens; the server
is then started with `SCORECARD_RECORDED_SHEETS`, so every read is of the
recorded sheet and none reaches Google. Prints, as JSON, a signed-in session
for the practice owner and the company the walk sets up.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _session(user):
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.create()
    return session.session_key


class Command(BaseCommand):
    help = "Set up the sheet walk on a seeded demo copy (laptop, *_walk only)."

    def add_arguments(self, parser):
        parser.add_argument("--company", default="Globex Logistics")

    def handle(self, *args, **options):
        database = connection.settings_dict["NAME"] or ""
        if settings.APP_ENVIRONMENT != "local" or not database.endswith("_walk"):
            raise CommandError("Only on the laptop, in a database whose name ends in _walk.")
        from apps.crm.models import Company, GmailConnection
        from apps.crm.services.gmail_oauth import SHEETS_SCOPES, TIER1_SCOPES
        from apps.platform import agreement
        from apps.platform.models import AgreementAcceptance
        from apps.tenancy.models import Membership, Role

        owner = Membership.all_objects.filter(role=Role.FF).select_related("user", "tenant") \
            .order_by("created_at").first()
        tenant = owner.tenant
        terms = agreement.current()
        AgreementAcceptance.all_objects.get_or_create(
            user=owner.user, version=terms["version"],
            defaults={"tenant": tenant, "text_sha256": terms["sha256"]})
        GmailConnection.all_objects.filter(tenant=tenant).delete()
        GmailConnection.all_objects.create(tenant=tenant, user=owner.user,
                                           email_address=owner.user.email,
                                           scopes=TIER1_SCOPES + SHEETS_SCOPES)
        company = Company.all_objects.get(tenant=tenant, name=options["company"])
        self.stdout.write(json.dumps({
            "cookie": settings.SESSION_COOKIE_NAME, "session": _session(owner.user),
            "company": str(company.pk), "company_name": company.name,
            "account": owner.user.email}))
