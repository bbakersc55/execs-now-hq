"""Fill the demo database with the fictional practice, or reset it
(owner, 2026-09-29). apps/tenancy/demo/ holds what goes in.

    python manage.py seed_demo --database <name> --ff-email you@getexecutivesnow.com

**Every run starts by emptying Summit's own practice** — that is what makes it
a reset — and nothing else: demo visitors' copies (2026-10-17), with their
sign-ins, data and end dates, are left as they are. `--whole-database` empties
every table instead, as the command always did before; it is for the laptop
only and is refused anywhere that is not a localhost build. Either way it
refuses before touching anything unless:

1. `APP_ENVIRONMENT` is `demo`;
2. the database is not `execsnowhq_dev` (the laptop's production database
   until cutover, its fallback after), whatever else is true;
3. the operator types the database's name (`--database`), matching the one
   configured.

Summit's own people go with it, but never the platform owner's sign-in, which
the new Summit takes over.

`--ff-email` is the Google account that signs in to the demo as its practice
owner. Inside the demo that person is shown as John Carter (`--ff-name`): the
demo has its own database, so the name there is the demo's alone.

The demo's own send-only Gmail connection, if it has one, is carried across
the reset, so re-seeding does not mean connecting Gmail again. So is the demo
practice's own Anthropic key, if it has one, for the same practice owner. The
files the old demo stored are taken out of its bucket.
"""

from __future__ import annotations

import json
import time

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
                            help="The Google account that signs in as the practice owner.")
        parser.add_argument("--ff-name", default="",
                            help="How that person is shown in the demo. John Carter "
                                 "unless given.")
        parser.add_argument("--whole-database", action="store_true",
                            help="Laptop only: empty every table, visitors' copies "
                                 "included, rather than Summit alone.")
        parser.add_argument("--oauth-client", default="internal",
                            choices=("internal", "external"),
                            help="Which Google OAuth client the demo practice signs in "
                                 "and connects Gmail with.")

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

        whole = options["whole_database"]
        if whole and not settings.IS_LOCAL:
            raise CommandError("--whole-database empties every visitor's copy too. It is for "
                               "the laptop only. Refusing.")

        from apps.tenancy import demo
        from apps.tenancy.demo import visitors

        began = time.monotonic()
        with transaction.atomic():
            kept = demo.kept_mail_connection()
            ai_key = demo.kept_ai_key()
            if whole:
                old_files = [(f.bucket, f.object_key) for f in demo.stored_objects()]
                emptied = f"Emptied {demo.reset_database()} tables in {name}"
            else:
                old_files = demo.reset_summit()
                emptied = f"Emptied {demo.PRACTICE} in {name}"
            made = demo.build(ff_email=options["ff_email"], ff_name=options["ff_name"],
                              oauth_client=options["oauth_client"], mail_connection=kept,
                              ai_key=ai_key)
        # Only once the new demo is committed: a failed seed rolls back to the
        # old one, which still needs its files.
        removed = visitors.remove_files(old_files)
        self.stdout.write(f"{emptied}, removed {removed} of {len(old_files)} old files, then "
                          f"seeded {made['tenant'].name} in {time.monotonic() - began:.0f}s:")
        self.stdout.write(json.dumps(made["counts"], indent=2, default=str))
        self.stdout.write(f"Sign in as {options['ff_email']} with Google.")
