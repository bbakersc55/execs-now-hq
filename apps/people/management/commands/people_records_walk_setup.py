"""The employee records walk's setup, on a seeded demo copy (2026-11-17).

    DATABASE_URL=postgres:///execsnowhq_walk .venv/bin/python manage.py people_records_walk_setup

**Not product code, and laptop only**: it refuses unless APP_ENVIRONMENT is
local and the database's name ends in `_walk`, so it can never touch
`execsnowhq_local`, the demo or production. `scripts/people_records_walk.py`
seeds the demo into that database (whose People seed makes Acme's records),
runs this, and walks the pages.

It changes only what a level needs: Porky leads every team (senior
leadership), Elmer is nobody's leader (a manager of his reports), and
Yosemite gets the handbook acknowledgment to sign. It prints, as JSON, a
signed-in session for each level, the records the walk opens, and Lola's
signing link.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.people.management.commands.people_walk_setup import _session


class Command(BaseCommand):
    help = "Set up the employee records walk on a seeded demo copy (laptop, *_walk only)."

    def handle(self, *args, **options):
        database = connection.settings_dict["NAME"] or ""
        if settings.APP_ENVIRONMENT != "local" or not database.endswith("_walk"):
            raise CommandError("Only on the laptop, in a database whose name ends in _walk.")
        from apps.crm.models import Company
        from apps.crm.services import outbox
        from apps.esign import links
        from apps.people import hiring
        from apps.people.models import PersonDocument, PersonRecord
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
        acme = Company.all_objects.get(tenant=tenant, name="Acme Fasteners")
        staff = {m.user.full_name: m for m in Membership.all_objects.filter(
            tenant=tenant, role__in=(Role.CF, Role.VA), revoked_at__isnull=True)
            .select_related("user")}
        clients = {m.user.full_name: m for m in Membership.all_objects.filter(
            tenant=tenant, client_company=acme, revoked_at__isnull=True).select_related("user")}

        def client(first):
            return next(m for name, m in clients.items() if name.startswith(first))

        wiley, porky, elmer, yosemite = (client("Wiley"), client("Porky"), client("Elmer"),
                                         client("Yosemite"))
        Membership.all_objects.filter(pk=porky.pk).update(leads_all_teams=True)
        for m in (elmer, yosemite):
            Membership.all_objects.filter(pk=m.pk).update(leads_all_teams=False)
            ClientTeamMember.all_objects.filter(membership=m).update(level="member")
        records = {r.first_name: r for r in PersonRecord.all_objects.filter(
            tenant=tenant, client_company=acme)}
        with tenant_context(tenant.pk):
            yosemite_record = records["Yosemite"]
            if not PersonDocument.objects.filter(person=yosemite_record, kind="handbook").exists():
                document = hiring._send(yosemite_record, actor=owner.user, kind="handbook",
                                        template=hiring._template(tenant,
                                                                  hiring.HANDBOOK_TEMPLATE),
                                        email=yosemite_record.work_email, fields={}, role="FF")
                outbox.approve(document.request_message, actor=owner.user, role="FF")
            offer = PersonDocument.objects.get(person=records["Lola"], kind="offer_letter")
            link = links.ensure(offer.esign_document)
        lasso = staff["Ted Lasso"]
        pam = staff["Pam Beesly"]
        self.stdout.write(json.dumps({
            "cookie": settings.SESSION_COOKIE_NAME, "acme": str(acme.pk),
            "records": {k: str(v.pk) for k, v in records.items()},
            "lola_link": "/sign/" + link.rsplit("/sign/", 1)[1],
            "offer_document": str(offer.esign_document_id),
            "people": {
                "owner": {"email": owner.user.email, "session": _session(owner.user)},
                "client owner": {"email": wiley.user.email, "session": _session(wiley.user)},
                "generalist": {"email": lasso.user.email, "session": _session(lasso.user)},
                "senior leadership": {"email": porky.user.email,
                                      "session": _session(porky.user)},
                "manager": {"email": elmer.user.email, "session": _session(elmer.user)},
                "employee": {"email": yosemite.user.email, "session": _session(yosemite.user)},
                "assistant": {"email": pam.user.email, "session": _session(pam.user)},
            },
        }))
