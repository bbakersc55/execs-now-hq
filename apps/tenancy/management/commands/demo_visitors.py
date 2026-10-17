"""Demo visitors' copies, in a process of their own (2026-10-17).
`apps/tenancy/demo/visitors.py` starts these from a web request; they can be
run by hand too.

    python manage.py demo_visitors setup <visitor id>   # set up or reset one copy
    python manage.py demo_visitors sweep                # delete copies past their read-only week
"""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Demo only: set up (or reset) a visitor's copy, or sweep away ended ones."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("setup", "sweep"))
        parser.add_argument("visitor", nargs="?", default=None)

    def handle(self, *args, **options):
        from apps.tenancy.demo import visitors
        from config import environment

        if not environment.is_demo():
            raise CommandError("Demo visitors live only on the demo. Refusing.")
        began = time.monotonic()
        if options["action"] == "setup":
            if not options["visitor"]:
                raise CommandError("Name the visitor's id.")
            visitors.run_setup(options["visitor"])
            self.stdout.write(f"demo visitors: set up {options['visitor']} in "
                              f"{time.monotonic() - began:.0f}s")
        else:
            self.stdout.write("demo visitors: sweep " + json.dumps(visitors.sweep()))
