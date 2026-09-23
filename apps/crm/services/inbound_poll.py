"""The poll itself (FR-6.5), and the boundary it enforces.

**Only threads the app started.** The cursor is `email_thread.last_polled_at`,
oldest first — not a Gmail `historyId`, which expires after about a week and
would turn a fortnight's downtime into a full resync (AC-6.16). `threads.get`
returns the whole thread every time, so catching up and keeping up are the same
operation and the only thing that stops a message arriving twice is the
idempotency key (FR-6.12).

A failure on one thread is recorded on that thread and does not stop the run:
one deleted conversation must not hold up the other forty.
"""

from __future__ import annotations

from django.db.models import F
from django.utils import timezone

from apps.crm.models import EmailThread, GmailConnection
from apps.crm.services import inbound, transport

#: Threads per run. Fifteen-minute schedule, so this is a ceiling on the work
#: one tick does rather than a limit on how much gets read.
THREADS_PER_RUN = 40

DRIVE_SCOPE_MISSING = (
    "The connected Google account has not granted permission to read mail, so "
    "replies cannot be collected. Reconnect Gmail and leave every box ticked."
)


class NotConnected(Exception):
    """No mailbox to read. Not an error — most tenants will be here at first."""


def reading_connection(tenant):
    """The connection that may actually read (FR-6.3g, assumption H7).

    Prefers one that holds `gmail.readonly`; a connection with only send
    scopes cannot poll, and saying so beats a 403 from Google.
    """
    from apps.crm.services.gmail_oauth import TIER2_SCOPES

    connections = list(GmailConnection.objects.filter(tenant=tenant))
    for connection in connections:
        if set(TIER2_SCOPES) <= set(connection.scopes or []):
            return connection
    if connections:
        raise NotConnected(DRIVE_SCOPE_MISSING)
    raise NotConnected("No Google account is connected for this practice.")


def due(tenant, *, limit=THREADS_PER_RUN):
    """The threads to look at, least recently polled first.

    `last_polled_at IS NULL` sorts first on Postgres with `nulls_first`, which
    is what makes a thread created between two runs get read on the next one
    rather than waiting for its turn.
    """
    return list(EmailThread.objects.exclude(gmail_thread_id="")
                .order_by(F("last_polled_at").asc(nulls_first=True))
                .values_list("pk", flat=True)[:limit])


def poll(tenant, *, client=None, limit=THREADS_PER_RUN) -> dict:
    """One run. Returns what a health line would say."""
    if client is None:
        client = transport.GmailReader(reading_connection(tenant))

    totals = {"threads": 0, "matched": 0, "unmatched": 0, "already_had": 0,
              "skipped_outbound": 0, "errors": 0}
    for pk in due(tenant, limit=limit):
        thread = EmailThread.objects.filter(pk=pk).first()
        if thread is None:                              # pragma: no cover - raced
            continue
        totals["threads"] += 1
        try:
            payload = client.thread(thread.gmail_thread_id)
        except transport.TransportUnavailable as exc:
            # Recorded on the thread, and the cursor is **not** advanced, so
            # the next run tries this one again.
            thread.poll_error = str(exc)
            thread.save(update_fields=["poll_error", "updated_at"])
            totals["errors"] += 1
            continue
        counts = inbound.ingest_thread(tenant, payload, client=client) if payload else {}
        for key, value in counts.items():
            totals[key] += value
        thread.poll_error = ""
        thread.last_polled_at = timezone.now()
        thread.save(update_fields=["poll_error", "last_polled_at", "updated_at"])
    return totals
