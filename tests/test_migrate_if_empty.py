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
