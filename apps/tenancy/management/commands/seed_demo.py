"""Fill the demo database with the fictional practice, or reset it
(owner, 2026-09-29). apps/tenancy/demo.py holds what goes in.

    python manage.py seed_demo --database <name> --ff-email you@getexecutivesnow.com

**Every run starts by emptying the whole database** — that is what makes it a
reset. So it refuses before touching anything unless:

1. `APP_ENVIRONMENT` is `demo`;
2. the database is not `execsnowhq_dev` (the laptop's production database
   until cutover, its fallback after), whatever else is true;
3. the operator types the database's name (`--database`), matching the one
   configured.

`--ff-email` is the Google account that signs in to the demo as its founder.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

PROTECTED_DATABASES = {"execsnowhq_dev"}


class Command(BaseCommand):
    help = "Demo only: empty this database and fill it with the fictional demo practice."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True,
                            help="The configured database's name, typed as a confirmation.")
        parser.add_argument("--ff-email", required=True,
                            help="The Google account that signs in as the demo's founder.")
        parser.add_argument("--ff-name", default="Demo Founder")

    def handle(self, *args, **options):
        name = settings.DATABASES["default"].get("NAME") or ""
        if settings.APP_ENVIRONMENT != "demo":
            raise CommandError(f"APP_ENVIRONMENT is {settings.APP_ENVIRONMENT!r}, not "
                               "'demo'. This command empties the database. Refusing.")
        if name in PROTECTED_DATABASES:
            raise CommandError(f"{name!r} is the laptop's production database. Refusing.")
        if options["database"] != name:
            raise CommandError(f"You typed {options['database']!r}, but the configured "
                               f"database is {name!r}. Refusing.")

        from apps.tenancy import demo

        with transaction.atomic():
            emptied = demo.reset_database()
            made = demo.build(ff_email=options["ff_email"], ff_name=options["ff_name"])
        self.stdout.write(f"Emptied {emptied} tables in {name}, then seeded "
                          f"{made['tenant'].name}:")
        for key in ("clients", "prospects", "digests", "strategy_sessions",
                    "meeting_proposals"):
            self.stdout.write(f"  {key.replace('_', ' '):<20} {made[key]}")
        self.stdout.write(f"Sign in as {options['ff_email']} with Google.")
