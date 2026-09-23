"""Replay a captured Gmail thread payload against the ingester (FR-6.14).

**These fixtures are the module's regression suite** (FR-6.15). Everything that
decides anything about an inbound message is a pure function over a parsed
payload, so the only part needing a live mailbox is fetching the JSON — and
that part is the part least likely to be wrong.

    manage.py replay_inbound tests/fixtures/inbound/thread_id_match.json
    manage.py replay_inbound tests/fixtures/inbound/*.json --tenant executives-now
"""

from __future__ import annotations

import json
import pathlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.crm.services import inbound
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Replay captured Gmail thread payloads against the inbound ingester."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="Fixture JSON files.")
        parser.add_argument("--tenant", help="Tenant slug. Default: the only one.")
        parser.add_argument("--apply", action="store_true", help=(
            "Keep what the replay produces. Without it the whole run is rolled "
            "back, which is what you want against a database holding real mail."))

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get("tenant"):
            tenants = tenants.filter(slug=options["tenant"])
        if tenants.count() > 1:
            raise CommandError("Several tenants — name one with --tenant.")
        tenant = tenants.first()
        if tenant is None:
            raise CommandError("No such tenant.")

        # A replay writes rows. Against the development database — which holds
        # the practice's real contacts and real threads — that means seven
        # invented replies in the queue somebody has to clear. So the default
        # is a dry run, and keeping the result is the flag.
        with tenant_context(tenant.id), transaction.atomic():
            for path in options["paths"]:
                self.one(tenant, pathlib.Path(path))
            if not options["apply"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    "Dry run. Nothing kept. Re-run with --apply to keep it."))

    def one(self, tenant, path):
        if not path.exists():
            raise CommandError(f"{path} does not exist.")
        payload = json.loads(path.read_text())
        # A fixture is either a whole thread or a single message. Gmail really
        # returns both shapes, so both replay.
        if "messages" in payload:
            counts = inbound.ingest_thread(tenant, payload)
        else:
            counts = {inbound.ingest_message(tenant, payload)["outcome"]: 1}
        summary = ", ".join(f"{value} {key.replace('_', ' ')}"
                            for key, value in counts.items() if value)
        self.stdout.write(f"{path.name}: {summary or 'nothing'}")
