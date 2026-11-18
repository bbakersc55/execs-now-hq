"""The People security walk's setup, on a seeded demo copy (2026-11-17).

    DATABASE_URL=postgres:///execsnowhq_walk .venv/bin/python manage.py people_walk_setup

**Not product code, and laptop only**: it refuses unless APP_ENVIRONMENT is
local and the database's name ends in `_walk`, so it can never touch
`execsnowhq_local`, the demo or production. `scripts/people_security_walk.py`
seeds the demo into that database, runs this, and walks the pages.

On the demo's Summit practice it turns People on, puts placeholder people at
Acme Fasteners (Wiley the owner; Marvin, a manager; Elmer, who reports to
Marvin; two more), and prints, as JSON, a signed-in session for the practice
owner, an associate (who is given HR Generalist in the walk), Marvin, Elmer
and an assistant with no permission; and two more of the assistant's, one
eleven hours fifty-five minutes old and one past twelve hours. `--session
EMAIL` prints a fresh one; `--age-code SESSION` makes a session's last code
five hours old.
"""

from __future__ import annotations

import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _session(user, *, signed_in_ago=0, coded_ago=None):
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    from apps.accounts.middleware import SIGNED_IN_KEY
    from apps.accounts.two_factor import SESSION_VERIFIED

    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session[SIGNED_IN_KEY] = time.time() - signed_in_ago
    if coded_ago is not None:
        session[SESSION_VERIFIED] = time.time() - coded_ago
    session.create()
    return session.session_key


class Command(BaseCommand):
    help = "Set up the People security walk on a seeded demo copy (laptop, *_walk only)."

    def add_arguments(self, parser):
        parser.add_argument("--session", metavar="EMAIL")
        parser.add_argument("--age-code", metavar="SESSION")

    def handle(self, *args, **options):
        database = connection.settings_dict["NAME"] or ""
        if settings.APP_ENVIRONMENT != "local" or not database.endswith("_walk"):
            raise CommandError("Only on the laptop, in a database whose name ends in _walk.")
        from apps.accounts.models import User

        if options["session"]:
            user = User.objects.get(email=options["session"])
            self.stdout.write(json.dumps({"session": _session(user)}))
            return
        if options["age_code"]:
            from django.contrib.sessions.backends.db import SessionStore

            from apps.accounts.two_factor import SESSION_VERIFIED

            session = SessionStore(session_key=options["age_code"])
            session[SESSION_VERIFIED] = time.time() - 5 * 60 * 60
            session.save()
            self.stdout.write(json.dumps({"aged": True}))
            return
        self._setup()

    def _setup(self):
        from apps.centers import services as centers
        from apps.crm.models import Company
        from apps.crm.services.secrets import encrypt
        from apps.people.models import PersonRecord
        from apps.platform import agreement
        from apps.platform.models import AgreementAcceptance
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Membership, Role
        from apps.work.models import ClientTeamMember

        owner = Membership.all_objects.filter(role=Role.FF).select_related("user", "tenant") \
            .order_by("created_at").first()
        tenant = owner.tenant
        terms = agreement.current()
        AgreementAcceptance.all_objects.get_or_create(
            user=owner.user, version=terms["version"],
            defaults={"tenant": tenant, "text_sha256": terms["sha256"]})
        associate = Membership.all_objects.filter(tenant=tenant, role=Role.CF).select_related(
            "user").order_by("created_at").first()
        assistant = Membership.all_objects.filter(tenant=tenant, role=Role.VA).select_related(
            "user").order_by("created_at").first()
        acme = Company.all_objects.get(tenant=tenant, name="Acme Fasteners")
        members = {m.user.full_name: m for m in Membership.all_objects.filter(
            tenant=tenant, client_company=acme, revoked_at__isnull=True).select_related("user")}

        def member(first):
            return next(m for name, m in members.items() if name.startswith(first))

        wiley, marvin, elmer = member("Wiley"), member("Marvin"), member("Elmer")
        # Neither is senior leadership here: a manager and a member.
        for m, level in ((marvin, "manager"), (elmer, "member")):
            Membership.all_objects.filter(pk=m.pk).update(leads_all_teams=False)
            ClientTeamMember.all_objects.filter(membership=m).update(level=level)
        with tenant_context(tenant.pk):
            if not centers.has(tenant.pk, "people"):
                centers.switch(tenant, "people", True, actor=owner.user)

        def person(first, last, title, user=None, boss=None, pay="$28.00 an hour"):
            # Since the demo seeds Acme's records (2026-11-17), theirs are used.
            seeded = PersonRecord.all_objects.filter(tenant=tenant, client_company=acme,
                                                     first_name=first, last_name=last).first()
            if seeded is not None:
                return seeded
            return PersonRecord.all_objects.create(
                tenant=tenant, client_company=acme, first_name=first, last_name=last,
                title=title, team="Plant", user=user, manager=boss,
                work_email=f"{first.lower()}@acme-fasteners.example",
                sensitive_ciphertext=encrypt(json.dumps({
                    "pay_rate": pay, "home_address": f"{first}'s home, Tucson, AZ",
                    "date_of_birth": "1988-06-14", "personal_phone": "520-555-0142",
                    "personal_email": f"{first.lower()}@home.example",
                    "emergency_contact": "A sister, 520-555-0199",
                    "documents": ["Offer letter (placeholder)"]})),
                created_by=owner.user)

        wiley_p = person("Wiley", "Coyote", "Owner", wiley.user, pay="$140,000 a year")
        marvin_p = person("Marvin", "Martian", "Plant manager", marvin.user, wiley_p,
                          pay="$41.25 an hour")
        person("Elmer", "Fudd", "Header line lead", elmer.user, marvin_p, pay="$32.50 an hour")
        person("Yosemite", "Sam", "Machinist", None, marvin_p)
        person("Foghorn", "Leghorn", "Machinist", None, wiley_p)
        hours = 60 * 60
        self.stdout.write(json.dumps({
            "cookie": settings.SESSION_COOKIE_NAME, "acme": str(acme.pk),
            "people": {
                "owner": {"email": owner.user.email, "session": _session(owner.user)},
                "generalist": {"email": associate.user.email,
                               "name": associate.user.full_name,
                               "member": str(associate.pk),
                               "session": _session(associate.user)},
                "manager": {"email": marvin.user.email, "session": _session(marvin.user)},
                "employee": {"email": elmer.user.email, "session": _session(elmer.user)},
                "assistant": {"email": assistant.user.email,
                              "session": _session(assistant.user)},
            },
            "assistant_nearly_12h": _session(assistant.user, signed_in_ago=11 * hours + 55 * 60),
            "assistant_past_12h": _session(assistant.user, signed_in_ago=12 * hours + 60),
        }))
