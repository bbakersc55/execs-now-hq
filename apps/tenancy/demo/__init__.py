"""The demo practice (owner, 2026-09-29; rebuilt 2026-10-08): what
demo.getexecutivesnow.com shows.

**Summit Operations Partners**, a fictional operations practice with its
owner, two associates and two assistants; eleven paying clients with goals,
readings, milestones, projects and tasks moving; a sales pipeline with
prospects at every stage; several dozen referral partners; strategy sessions
at each point in their life; a meeting queue; digests waiting and sent; and
invoices and books from January 2025 to the day it is seeded.

**Entirely fictional.** `cast.py` holds who is in it. Every address is at
`.example`, a reserved domain that cannot receive mail, and nothing leaves
while it is being built (`config.environment.quiet_mail`).

Built through the app's own code wherever a person's action would have made
the thing, with the app's clock moved to when they would have done it
(`clock.at`): an invoice of March 2025 is drafted by its schedule, numbered,
stored as a PDF, marked sent, paid and entered in the books by the same
functions that do those things on a real day. So the demo shows what the app
produces, not rows arranged to look like it. Dates are relative to the day it
is seeded.
"""

from __future__ import annotations

from django.db import connection

from .cast import PRACTICE, SLUG  # noqa: F401  (what the command and tests name)


def kept_mail_connection():
    """The demo's own send-only Gmail connection, lifted out before the reset
    so that re-seeding does not mean connecting Gmail again. Returned as plain
    values; `foundation.restore_mail_connection` puts it back."""
    from apps.crm.models import GmailConnection

    row = (GmailConnection.all_objects.select_related("user", "secret", "tenant")
           .filter(send_as_verified_at__isnull=False, secret__isnull=False)
           .order_by("-send_as_verified_at").first())
    if row is None:
        return None
    return {"user_email": row.user.email, "email_address": row.email_address,
            "scopes": row.scopes, "send_as_address": row.send_as_address,
            "send_as_verified_at": row.send_as_verified_at,
            "ciphertext": bytes(row.secret.ciphertext), "last4": row.secret.last4,
            "oauth_client": row.tenant.oauth_client}


def stored_objects():
    """Every file the demo holds, so the reset can take them out of its bucket
    as well as out of its database."""
    from apps.tenancy.models import StoredFile

    return list(StoredFile.all_objects.all())


def reset_database() -> int:
    """Empty every table the app has, so a re-run starts clean. Demo only —
    the command that calls this refuses anywhere else."""
    tables = [t for t in connection.introspection.table_names()
              if t != "django_migrations"]
    with connection.cursor() as cursor:
        # Django's foreign keys are deferred; Postgres will not truncate a
        # table with checks still pending in this transaction.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables)
                       + " RESTART IDENTITY CASCADE")
    return len(tables)


def build(*, ff_email: str, ff_name: str = "", oauth_client: str = "internal",
          mail_connection=None, today=None) -> dict:
    """The whole practice. Returns the practice and what was made, in counts."""
    from django.utils import timezone

    from apps.tenancy.context import tenant_context
    from config import environment

    from . import comms, foundation, money, sessions, work

    today = today or timezone.localdate()
    with environment.quiet_mail():
        world = foundation.practice(ff_email=ff_email, ff_name=ff_name,
                                    oauth_client=oauth_client, today=today)
        with tenant_context(world.tenant.pk):
            foundation.people(world)
            money.history(world)
            sessions.strategy(world)
            work.engagements(world)
            comms.everything(world)
            foundation.restore_mail_connection(world, mail_connection)
            counts = foundation.counts(world)
    return {"tenant": world.tenant, "counts": counts}
