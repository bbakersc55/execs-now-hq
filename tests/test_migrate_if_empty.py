"""migrate_if_empty (Phase 7, 2026-09-29): a new environment's first deploy
builds its schema; a database with anything in it is never migrated by a
deploy."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.management import CommandError, call_command


@pytest.mark.django_db
def test_a_current_database_is_left_alone():
    with mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        call_command("migrate_if_empty")
    run.assert_not_called()


@pytest.mark.django_db
def test_an_unapplied_migration_refuses_the_start_and_is_not_applied():
    from django.db.migrations.executor import MigrationExecutor

    pending = mock.Mock(app_label="crm")
    pending.name = "0099_x"
    with mock.patch.object(MigrationExecutor, "migration_plan",
                           return_value=[(pending, False)]), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        with pytest.raises(CommandError, match="Unapplied migrations: crm.0099_x"):
            call_command("migrate_if_empty")
    run.assert_not_called()


@pytest.mark.django_db
def test_tables_without_migration_records_are_not_an_empty_database():
    from django.db import connection

    with mock.patch.object(connection.introspection, "table_names",
                           return_value=["django_migrations", "contact"]), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.recorded_migrations",
                    return_value=0), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        with pytest.raises(CommandError, match="not an empty database"):
            call_command("migrate_if_empty")
    run.assert_not_called()


@pytest.mark.django_db
def test_an_empty_database_gets_its_schema():
    from django.db import connection

    with mock.patch.object(connection.introspection, "table_names", return_value=[]), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        call_command("migrate_if_empty")
    run.assert_called_once_with("migrate", interactive=False, verbosity=1)


def _pending():
    from django.db.migrations.executor import MigrationExecutor

    pending = mock.Mock(app_label="crm")
    pending.name = "0099_x"
    return mock.patch.object(MigrationExecutor, "migration_plan",
                             return_value=[(pending, False)])


@pytest.mark.django_db
def test_the_demo_applies_its_migrations_at_start(settings):
    settings.IS_DEMO = True
    settings.PUBLIC_BASE_URL = "https://demo.getexecutivesnow.com"
    with _pending(), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        call_command("migrate_if_empty")
    run.assert_called_once_with("migrate", interactive=False, verbosity=1)


@pytest.mark.django_db
def test_a_demo_setting_on_the_production_host_is_refused(settings):
    settings.IS_DEMO = True
    settings.PUBLIC_BASE_URL = "https://app.getexecutivesnow.com"
    with _pending(), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        with pytest.raises(CommandError, match="Refusing to migrate"):
            call_command("migrate_if_empty")
    run.assert_not_called()


@pytest.mark.django_db
def test_production_still_refuses(settings):
    settings.IS_DEMO = False
    settings.PUBLIC_BASE_URL = "https://app.getexecutivesnow.com"
    with _pending(), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        with pytest.raises(CommandError, match="Unapplied migrations"):
            call_command("migrate_if_empty")
    run.assert_not_called()


# ------------------------------------------------- web waits (owner, 2026-10-20)

class _Clock:
    """Stands in for `time` in the command: sleeping moves the clock on."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def strftime(self, fmt, _t):
        return "2026-10-21T00:34:00Z"

    def gmtime(self):
        return None


def _plans(*plans):
    """migration_plan answering each check in turn: pending, then as given."""
    from django.db.migrations.executor import MigrationExecutor

    pending = mock.Mock(app_label="crm")
    pending.name = "0099_x"
    answers = [[(pending, False)] if p else [] for p in plans]
    return mock.patch.object(MigrationExecutor, "migration_plan", side_effect=answers)


@pytest.mark.django_db
def test_web_waits_for_the_migration_and_starts_once_it_is_applied(settings):
    from io import StringIO

    settings.IS_DEMO = False
    clock, out = _Clock(), StringIO()
    with _plans(True, True, True, False), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.time", clock), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        call_command("migrate_if_empty", wait=360, every=10, stdout=out)
    run.assert_not_called()
    assert clock.sleeps == [10, 10, 10]
    lines = out.getvalue().splitlines()
    assert lines[0] == ("==> 2026-10-21T00:34:00Z WAITING (0s of 360s) for: crm.0099_x. "
                        "Apply them in the waiting worker: railway ssh --service qcluster "
                        "-- python manage.py migrate")
    assert "(20s of 360s)" in lines[2]
    assert lines[-1] == "Migrations are current."


@pytest.mark.django_db
def test_web_gives_up_after_the_wait_and_never_migrates(settings):
    settings.IS_DEMO = False
    clock = _Clock()
    with _plans(*[True] * 40), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.time", clock), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.call_command") as run:
        with pytest.raises(CommandError, match="Unapplied migrations: crm.0099_x"):
            call_command("migrate_if_empty", wait=360, every=10)
    run.assert_not_called()
    assert clock.sleeps == [10] * 36


@pytest.mark.django_db
def test_without_a_wait_it_refuses_at_once(settings):
    settings.IS_DEMO = False
    clock = _Clock()
    with _plans(True), \
         mock.patch("apps.tenancy.management.commands.migrate_if_empty.time", clock):
        with pytest.raises(CommandError, match="Unapplied migrations"):
            call_command("migrate_if_empty")
    assert clock.sleeps == []


def test_web_start_waits_six_minutes_inside_its_health_check():
    """The start script's wait, and Railway's health check on web outlasting it:
    a check that gives up first fails the deploy all the same."""
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    start = (root / "scripts/start_web.sh").read_text()
    wait = int(re.search(r"migrate_if_empty --wait (\d+) --every 10\b", start).group(1))
    assert wait == 360
    health = json.loads((root / "railway/web.json").read_text())["deploy"]["healthcheckTimeout"]
    assert health > wait + 60
    worker = (root / "scripts/start_qcluster.sh").read_text()
    assert "migrate_if_empty" not in worker and "sleep 30" in worker
