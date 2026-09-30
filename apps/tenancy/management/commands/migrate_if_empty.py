"""The web service's first step on Railway (Phase 7, 2026-09-29).

- **An empty database** (no migration recorded at all): build the schema.
  Creating tables in a database that holds nothing is purely additive; there
  is nothing to back up and nothing to lose. This is how a new environment's
  first deploy comes up without anyone opening a shell into a container that
  cannot start.
- **Any other database**: never migrate. Exit non-zero if a migration is
  unapplied, so the deploy refuses to start and the migration waits for the
  owner's rule (SQL shown, additive, suite green, a backup today).
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def recorded_migrations(tables) -> int:
    if "django_migrations" not in tables:
        return 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_migrations")
        return cursor.fetchone()[0]


class Command(BaseCommand):
    help = "Build the schema on an empty database; otherwise refuse unapplied migrations."

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
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan)
            raise CommandError(f"Unapplied migrations: {names}. A deploy never applies "
                               "them; apply them by hand after the day's backup.")
        self.stdout.write("Migrations are current.")
