"""Make a user the platform owner, or stop them being one (P2, D8).

    manage.py set_platform_owner bryan.baker@getexecutivesnow.com
    manage.py set_platform_owner someone@example.com --remove

The only way the flag is set: no screen or API writes it. The platform owner
may open the Practices area, which shows numbers about practices and the
feedback their staff send, and nothing inside any practice.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set or remove the platform owner flag on a user."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--remove", action="store_true")

    def handle(self, *args, **options):
        from apps.accounts.models import User

        user = User.objects.filter(email__iexact=options["email"]).first()
        if user is None:
            raise CommandError(f"No user with the address {options['email']}.")
        user.is_platform_owner = not options["remove"]
        user.save(update_fields=["is_platform_owner", "updated_at"])
        others = User.objects.filter(is_platform_owner=True).exclude(pk=user.pk)
        state = "is now" if user.is_platform_owner else "is no longer"
        self.stdout.write(f"{user.email} {state} the platform owner.")
        if others.exists():
            self.stdout.write(f"  Also platform owner: {', '.join(others.values_list('email', flat=True))}")
