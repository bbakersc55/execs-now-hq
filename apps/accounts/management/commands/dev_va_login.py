"""Sign in as a test VA on this laptop — for the Phase 2 manual checks.

Staff sign in with Google, and Google only admits accounts in the owner's
Workspace. Checking what a VA sees should not cost a Workspace seat, so this
creates one test VA and prints a one-time sign-in link for it.

Refuses to run unless the app AND the database are local, checked before it
touches anything — the same two conditions as `scrub_dev_data`. The address
is at `.invalid`, a reserved TLD that cannot receive mail. Nothing here adds a
sign-in route: it issues an ordinary magic link (hashed, single-use, 20
minutes) through the landing page that already exists.

    .venv/bin/python manage.py dev_va_login            # create or reuse, print a link
    .venv/bin/python manage.py dev_va_login --remove   # revoke when finished
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TEST_VA_EMAIL = "va.localtest@example.invalid"
LOCAL_DB_HOSTS = {"", "localhost", "127.0.0.1"}


class Command(BaseCommand):
    help = "Local only: create a test VA and print a one-time sign-in link for it."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Revoke the test VA's membership and end its sessions.")

    def handle(self, *args, **options):
        host = settings.DATABASES["default"].get("HOST") or ""
        if not settings.IS_LOCAL:
            raise CommandError(f"PUBLIC_BASE_URL is {settings.PUBLIC_BASE_URL!r}, not localhost. Refusing.")
        if host not in LOCAL_DB_HOSTS:
            raise CommandError(f"The database host is {host!r}, not local. Refusing.")

        from apps.accounts.models import MagicLinkToken, User
        from apps.tenancy import services
        from apps.tenancy.models import Membership, Role, Tenant

        tenant = Tenant.objects.order_by("created_at").first()
        if tenant is None:
            raise CommandError("There is no tenant in this database.")

        if options["remove"]:
            membership = Membership.all_objects.filter(
                tenant=tenant, user__email=TEST_VA_EMAIL, revoked_at__isnull=True
            ).first()
            if membership is None:
                self.stdout.write("No active test VA. Nothing to do.")
                return
            services.remove_member(membership)
            self.stdout.write(self.style.SUCCESS(f"Revoked {TEST_VA_EMAIL} and ended its sessions."))
            return

        membership = Membership.all_objects.filter(tenant=tenant, user__email=TEST_VA_EMAIL).first()
        if membership is not None and membership.role != Role.VA:
            raise CommandError(f"{TEST_VA_EMAIL} exists with role {membership.role}; not changing it.")
        if membership is None or membership.revoked_at is not None:
            membership = services.invite_member(
                tenant=tenant, email=TEST_VA_EMAIL, role=Role.VA, full_name="Local test VA",
            )
        user = User.objects.get(pk=membership.user_id)

        _, raw = MagicLinkToken.issue(tenant=tenant, user=user, redirect_to=settings.APP_ROOT_URL)
        url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/auth/magic/{raw}"
        self.stdout.write(
            f"Test VA: {TEST_VA_EMAIL} (tenant {tenant.name})\n\n"
            f"Open this in a PRIVATE window (a normal window would replace your own sign-in):\n\n"
            f"    {url}\n\n"
            f"It works once and expires in 20 minutes; run this again for another.\n"
            f"When you are finished:  .venv/bin/python manage.py dev_va_login --remove"
        )
