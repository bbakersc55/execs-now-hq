"""What P7 phase 1's data step will do, company by company, without doing it.

    python manage.py client_teams_dry_run

It reads only what was there before P7, so it runs before `work` 0010 is
applied (which is when it is wanted: production, before "release") and after.
It writes nothing.
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand

from apps.work import team_backfill


class Command(BaseCommand):
    help = "P7 phase 1: the default team each client company will get. Writes nothing."

    def handle(self, *args, **options):
        self.stdout.write("DRY RUN. Nothing is written.")
        self.stdout.write(team_backfill.say(team_backfill.plan(apps)))
