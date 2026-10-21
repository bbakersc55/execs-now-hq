"""The web service's first step on Railway (Phase 7, 2026-09-29).

- **An empty database** (no migration recorded at all): build the schema.
  Creating tables in a database that holds nothing is purely additive; there
  is nothing to back up and nothing to lose. This is how a new environment's
  first deploy comes up without anyone opening a shell into a container that
  cannot start.
- **The demo** (`APP_ENVIRONMENT=demo`, owner 2026-10-02): apply what is
  unapplied. It deploys from `dev` with no worker, so there is no new-code
  container to migrate from by hand, and it holds only seeded, fictional data.
  Refused if the host is production's, whatever the environment says.
- **Any other database**: never migrate. Exit non-zero if a migration is
  unapplied, so the deploy refuses to start. Production's migrations go only
  through the runbook's "Releasing a migration"; the worker waits for it.

`--wait` (owner, 2026-10-20, after Release 20): before refusing, wait up to
that many seconds for someone else to apply them, checking every `--every`
seconds and saying what it is waiting on. `start_web.sh` waits six minutes,
so a normal release (worker WAITING, migrated by hand within a few minutes)
keeps the push's own web build alive instead of failing it. It still never
migrates.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PRODUCTION_HOST = "app.getexecutivesnow.com"


def recorded_migrations(tables) -> int:
    if "django_migrations" not in tables:
        return 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_migrations")
        return cursor.fetchone()[0]


def pending_plan():
    executor = MigrationExecutor(connection)
    return executor.migration_plan(executor.loader.graph.leaf_nodes())


def names(plan) -> str:
    return ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan)


class Command(BaseCommand):
    help = "Build the schema on an empty database; otherwise refuse unapplied migrations."

    def add_arguments(self, parser):
        parser.add_argument("--wait", type=int, default=0,
                            help="Seconds to wait for the migrations to be applied by hand "
                                 "before refusing (default: refuse at once).")
        parser.add_argument("--every", type=int, default=10,
                            help="Seconds between checks while waiting.")

    def handle(self, *args, **options):
        tables = connection.introspection.table_names()
        if recorded_migrations(tables) == 0:
            app_tables = [t for t in tables if t != "django_migrations"]
            if app_tables:
                raise CommandError(
                    f"No migrations are recorded, but {len(app_tables)} tables exist. "
                    "That is not an empty database. Refusing to touch it.")
            self.stdout.write("Empty database: building the schema.")
            call_command("migrate", interactive=False, verbosity=1)
            return
        plan = pending_plan()
        if plan and settings.IS_DEMO:
            if PRODUCTION_HOST in settings.PUBLIC_BASE_URL:
                raise CommandError(f"APP_ENVIRONMENT is demo but PUBLIC_BASE_URL is "
                                   f"{settings.PUBLIC_BASE_URL}. Refusing to migrate.")
            self.stdout.write(f"Demo: applying {len(plan)} migration(s).")
            call_command("migrate", interactive=False, verbosity=1)
            return
        if plan:
            plan = self.wait_for(plan, options["wait"], options["every"])
        if plan:
            raise CommandError(f"Unapplied migrations: {names(plan)}. A deploy never applies "
                               "them: runbook, \"Releasing a migration\".")
        self.stdout.write("Migrations are current.")

    def wait_for(self, plan, wait, every):
        """Re-check until nothing is pending or `wait` seconds have passed;
        returns what is still pending."""
        started = time.monotonic()
        while plan and (waited := time.monotonic() - started) < wait:
            self.stdout.write(
                f"==> {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} WAITING "
                f"({int(waited)}s of {wait}s) for: {names(plan)}. Apply them in the "
                "waiting worker: railway ssh --service qcluster -- python manage.py migrate")
            self.stdout.flush()
            time.sleep(every)
            plan = pending_plan()
        return plan
