"""Make a local copy of production unable to reach anybody
(`05_dev_environment.md` §8, owner 2026-09-29).

`scripts/refresh_dev_from_prod.sh` restores production into a local database
and runs this straight after, so there is no moment at which real client
addresses sit in a usable database. It rewrites every address and phone number
to one that cannot receive anything, and removes every credential and token
that could send, sign in or spend.

**It refuses before touching a row unless all three hold:**

1. `PUBLIC_BASE_URL` is localhost;
2. the database host is local;
3. the database is **not** `execsnowhq_dev`. Until cutover that database *is*
   production, on this laptop, and passes both checks above. After cutover it
   is the two-week fallback. Either way it is never scrubbed.

And the operator types the database's name (`--database <name>`), so the
command cannot run against whatever `.env` happens to point at. No `--force`.

`.invalid` is a reserved TLD that cannot resolve, so the safety does not
depend on the app's own send guards being right.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

LOCAL_DB_HOSTS = {"", "localhost", "127.0.0.1"}

#: Never scrubbed, whatever else is true: the laptop's production database
#: today, and its fallback for two weeks after cutover.
PROTECTED_DATABASES = {"execsnowhq_dev"}

STAFF_ROLES = ("FF", "CF", "VA")


def invalid_address() -> str:
    return f"{uuid.uuid4()}@example.invalid"


class Command(BaseCommand):
    help = "Local only: rewrite every address and remove every credential in this database."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True,
                            help="The name of the database to scrub, typed out, as a "
                                 "confirmation. Must match the one configured.")
        parser.add_argument("--keep-staff", action="store_true",
                            help="Keep FF/CF/VA sign-in addresses, so the practice can "
                                 "still sign in locally with Google. Client addresses "
                                 "are rewritten regardless.")

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        name, host = db.get("NAME") or "", db.get("HOST") or ""
        if not settings.IS_LOCAL:
            raise CommandError(f"PUBLIC_BASE_URL is {settings.PUBLIC_BASE_URL!r}, "
                               "not localhost. Refusing.")
        if host not in LOCAL_DB_HOSTS:
            raise CommandError(f"The database host is {host!r}, not local. Refusing.")
        if name in PROTECTED_DATABASES:
            raise CommandError(
                f"{name!r} is the laptop's production database (its fallback after "
                "cutover). It is never scrubbed. Point DATABASE_URL at a separate "
                "local database.")
        if options["database"] != name:
            raise CommandError(f"You typed {options['database']!r}, but the configured "
                               f"database is {name!r}. Refusing.")

        self.stdout.write(f"Scrubbing {name} (host={host or 'socket'}, "
                          f"PUBLIC_BASE_URL={settings.PUBLIC_BASE_URL})")
        with transaction.atomic():
            for label, count, what in self._scrub(keep_staff=options["keep_staff"]):
                self.stdout.write(f"  {label:<34} {count:>7,} {what}")
        self.stdout.write("Done. No address in this database can receive mail.")

    def _scrub(self, *, keep_staff: bool):
        from django_q.models import OrmQ

        from apps.accounts.models import MagicLinkToken, User
        from apps.crm.models import (
            ContactEmail, ContactPhone, EmailMessage, EmailSuppression, GmailConnection,
            ImportRow, OutboxMessage, UnmatchedInbound,
        )
        from apps.meetings.models import ProposalItem
        from apps.strategy.models import StrategySession
        from apps.tenancy.models import Membership, Tenant, TenantSecret
        from apps.work.models import StakeholderToken

        rows = []

        def rewrite(model, field, label):
            n = 0
            for pk in model.all_objects.values_list("pk", flat=True):
                model.all_objects.filter(pk=pk).update(**{field: invalid_address()})
                n += 1
            rows.append((label, n, "rewritten -> <uuid>@example.invalid"))

        rewrite(ContactEmail, "address", "contact_email.address")

        users = User.objects.all()
        if keep_staff:
            staff = Membership.all_objects.filter(role__in=STAFF_ROLES).values("user_id")
            users = users.exclude(pk__in=staff)
        user_ids = list(users.values_list("pk", flat=True))
        for pk in user_ids:
            User.objects.filter(pk=pk).update(email=invalid_address())
        rows.append(("user.email", len(user_ids),
                     "rewritten -> <uuid>@example.invalid"
                     + (" (staff kept)" if keep_staff else "")))
        with connection.cursor() as cursor:
            # allauth keeps its own copy of the address, and Google's tokens.
            if user_ids:
                cursor.execute(
                    "UPDATE account_emailaddress SET email = u.email "
                    "FROM app_user u WHERE u.id = account_emailaddress.user_id "
                    "AND u.id = ANY(%s)", [user_ids])
            cursor.execute("DELETE FROM socialaccount_socialtoken")
            rows.append(("socialaccount_socialtoken", cursor.rowcount, "deleted"))

        n = 0
        for pk in ContactPhone.all_objects.values_list("pk", flat=True):
            ContactPhone.all_objects.filter(pk=pk).update(
                number=f"+1555{uuid.uuid4().int % 10**7:07d}")
            n += 1
        rows.append(("contact_phone.number", n, "rewritten -> +1555xxxxxxx"))

        rewrite(EmailSuppression, "address", "email_suppression.address")
        n = EmailMessage.all_objects.update(
            from_address="scrubbed@example.invalid",
            to_addresses=["scrubbed@example.invalid"], cc_addresses=[])
        rows.append(("email_message addresses", n, "rewritten"))
        n = UnmatchedInbound.all_objects.update(
            from_address="scrubbed@example.invalid",
            to_addresses=["scrubbed@example.invalid"])
        rows.append(("unmatched_inbound addresses", n, "rewritten"))
        n = ImportRow.all_objects.update(raw={})
        rows.append(("import_row.raw", n, "emptied (it held the CSV's addresses)"))

        # A proposal approved in development must not create a real address.
        n = 0
        for item in ProposalItem.all_objects.filter(kind=ProposalItem.Kind.PARTICIPANT):
            payload = dict(item.payload or {})
            if payload.get("parsed_email"):
                payload["parsed_email"] = invalid_address()
            candidate = dict(payload.get("new_contact_candidate") or {})
            if candidate.get("email"):
                candidate["email"] = payload.get("parsed_email") or invalid_address()
                payload["new_contact_candidate"] = candidate
            for row in payload.get("existing_candidates") or []:
                if row.get("email"):
                    row["email"] = "scrubbed@example.invalid"
            ProposalItem.all_objects.filter(pk=item.pk).update(payload=payload)
            n += 1
        rows.append(("proposal_item participant emails", n, "rewritten"))

        n = GmailConnection.all_objects.count()
        GmailConnection.all_objects.all().delete()
        secrets = TenantSecret.all_objects.count()
        TenantSecret.all_objects.all().delete()
        rows.append(("gmail_connection", n, f"deleted (and {secrets} tenant_secret rows, "
                                            "including the Anthropic key)"))
        n = OutboxMessage.all_objects.count()
        OutboxMessage.all_objects.all().delete()
        rows.append(("outbox_message", n, "deleted"))
        n = OrmQ.objects.count()
        OrmQ.objects.all().delete()
        rows.append(("django_q_ormq", n, "queued tasks flushed"))
        n = MagicLinkToken.all_objects.count()
        MagicLinkToken.all_objects.all().delete()
        rows.append(("magic_link_token", n, "deleted"))
        n = StakeholderToken.all_objects.count()
        StakeholderToken.all_objects.all().delete()
        rows.append(("stakeholder_token", n, "deleted"))
        n = StrategySession.all_objects.exclude(precall_token_hash="").update(
            precall_token_hash="")
        rows.append(("strategy_session.precall_token", n, "cleared"))
        n = Tenant.objects.filter(hold_all_digests=False).update(hold_all_digests=True)
        rows.append(("tenant.hold_all_digests", n, "turned back ON"))
        return rows
