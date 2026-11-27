"""The card pages' script controls (docs/p16_card_page_scripts.md).

    manage.py card_pages status                 # mode, approval, last check, violations
    manage.py card_pages mode report-only       # the quick switch, if a payer is blocked
    manage.py card_pages mode enforce           # and back
    manage.py card_pages check                  # look now; alerts as the daily job does
    manage.py card_pages approve --note "Release 51"   # after a release: what is live, approved

`--base URL` reads another server than PUBLIC_BASE_URL (the laptop's proof).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "The card pages' script controls: status, mode, check, approve."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "mode", "check", "approve", "state"])
        parser.add_argument("value", nargs="?", default="")
        parser.add_argument("--note", default="")
        parser.add_argument("--by", default="", help="Who approves or switches (a name).")
        parser.add_argument("--base", default="", help="Another server's address.")
        parser.add_argument("--no-alert", action="store_true")

    def handle(self, *args, **o):
        getattr(self, f"do_{o['action']}")(o)

    def say(self, text=""):
        self.stdout.write(text)

    def do_mode(self, o):
        from apps.cardpages.models import Mode, Setting

        wanted = o["value"]
        if wanted not in Mode.values:
            raise CommandError("Say which: card_pages mode enforce, or card_pages mode "
                               "report-only.")
        row, _ = Setting.objects.get_or_create(pk=1)
        before = row.mode
        row.mode, row.changed_at = wanted, timezone.now()
        row.changed_by, row.note = (o["by"] or "manage.py")[:120], o["note"][:300]
        row.save()
        self.say(f"Card page policy: {Mode(wanted).label.lower()} (was "
                 f"{Mode(before).label.lower()}), from the next page load. The daily check "
                 "will report the header's change until it is approved.")

    def do_status(self, o):
        from apps.cardpages import check, policy
        from apps.cardpages.models import Check, Setting, Violation

        row = Setting.objects.filter(pk=1).first()
        self.say(f"Mode: {policy.mode()}"
                 + (f" (since {row.changed_at:%Y-%m-%d %H:%M} UTC, by {row.changed_by}"
                    f"{': ' + row.note if row.note else ''})" if row and row.changed_at else ""))
        self.say(f"Card policy: {policy.value(policy.CARD, policy.public_report_url())}")
        self.say(f"Bank pages ({', '.join(policy.BANK_PATHS)}): Plaid's script added.")
        base = check.current_baseline()
        self.say("Approved: " + (f"{base.approved_at:%Y-%m-%d %H:%M} UTC by {base.approved_by}"
                                 f" ({base.note}), {len(base.state['scripts'])} scripts"
                                 if base else "nothing yet"))
        last = Check.objects.order_by("-ran_at").first()
        if last:
            self.say(f"Last check: {last.ran_at:%Y-%m-%d %H:%M} UTC, {last.get_outcome_display()}"
                     + (f": {last.error}" if last.error else ""))
            for line in last.differences:
                self.say(f"  - {line}")
        else:
            self.say("Last check: none yet")
        rows = list(Violation.objects.order_by("-last_seen")[:15])
        self.say(f"Violations reported: {Violation.objects.count()} kinds"
                 + (", the latest:" if rows else ""))
        for v in rows:
            self.say(f"  {v.last_seen:%Y-%m-%d %H:%M} ×{v.count} {v.disposition or '?'} "
                     f"{v.directive} {v.blocked or '(inline)'} on {v.document}"
                     + (" [browser extension]" if v.noise else ""))

    def do_check(self, o):
        from apps.cardpages import check

        row = check.run(base_url=o["base"] or None, alert=not o["no_alert"])
        self.say(f"{row.get_outcome_display()} ({row.base_url})")
        for line in row.differences or ([row.error] if row.error else []):
            self.say(f"  - {line}")

    def do_state(self, o):
        from apps.cardpages import check

        self.say(json.dumps(check.observe(o["base"] or settings.PUBLIC_BASE_URL), indent=1))

    def do_approve(self, o):
        from apps.cardpages import check

        if not o["note"].strip():
            raise CommandError('Say why, e.g. --note "Release 51".')
        row, lines = check.approve(note=o["note"], by=o["by"] or "manage.py",
                                   base_url=o["base"] or None)
        self.say(f"Approved what {row.base_url} serves now: {len(row.state['scripts'])} "
                 f"scripts on {len(row.state['pages'])} pages.")
        self.say("Changed since the approval before:" if lines else "Nothing had changed.")
        for line in lines:
            self.say(f"  - {line}")
