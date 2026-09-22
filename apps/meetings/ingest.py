"""Polling the folder, and the two-step commit (FR-5.2 to FR-5.7).

The discipline that makes three days of a closed laptop lose nothing:

1. **Record every file in a page before the cursor moves.** The cursor is
   Drive's promise that we have seen everything up to here; advancing it past a
   file we failed to write is how a note disappears for good.
2. **Recording and parsing are separate steps.** A parse failure leaves the
   file recorded, visible, and retryable — and **does not advance the cursor
   past unprocessed work** (FR-5.5, AC-5.10).
3. **A file version is recorded once** (FR-5.4). Three polls over an unchanged
   folder produce nothing on the second and third.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.meetings import drive as drive_service
from apps.meetings.models import DriveWatch, MeetingSourceFile


#: How many files one poll will parse. See the note at its use.
PARSE_PER_POLL = 20


class NotConnected(Exception):
    """No folder is being watched, so there is nothing to poll."""


def watch_for(tenant):
    return DriveWatch.objects.filter(tenant=tenant, is_active=True).first()


def drive_connection(tenant):
    """The connection that may actually read Drive, or `None`.

    **A connection is not automatically a Drive connection.** `drive.readonly`
    is asked for separately (assumption C1), so a practice can have a perfectly
    healthy Gmail connection that Drive will refuse — and in a tenant with
    several connected accounts, the one that granted Drive is not necessarily
    the first one made. Prefer a connection that holds the scope.
    """
    from apps.crm.models import GmailConnection
    from apps.crm.services.gmail_oauth import DRIVE_SCOPES

    connections = list(GmailConnection.objects.filter(tenant=tenant))
    for connection in connections:
        if set(DRIVE_SCOPES) <= set(connection.scopes or []):
            return connection
    return None


def client_for(tenant):
    """The Drive client for this tenant's connection, or a refusal that says
    what is missing rather than a stack trace."""
    from apps.crm.models import GmailConnection

    connection = drive_connection(tenant)
    if connection is not None:
        return drive_service.DriveClient(connection)
    if GmailConnection.objects.filter(tenant=tenant).exists():
        # The failure the folder screen exists to prevent: a connection that
        # sends mail perfectly well and cannot see a single file.
        raise NotConnected(
            "The connected Google account has not granted access to Drive. "
            "Allow Drive access on the meeting queue, then try again.")
    raise NotConnected("No Google account is connected for this practice.")


def describe_folder(tenant, folder_id, *, client=None):
    """What that folder is, read live (FR-5.1a). Raises rather than guessing."""
    return (client or client_for(tenant)).describe_folder(folder_id)


@transaction.atomic
def record(tenant, drive_file) -> tuple[MeetingSourceFile | None, bool]:
    """Write one file down. Returns `(row, created)`.

    Idempotent on `(tenant, file, version)`: the second poll of an unchanged
    file finds the row and changes nothing.
    """
    if drive_file.trashed:
        return None, False
    reason = drive_service.skip_reason(drive_file.mime_type)
    row, created = MeetingSourceFile.objects.get_or_create(
        tenant=tenant, drive_file_id=drive_file.file_id,
        drive_version=str(drive_file.version),
        defaults={
            "name": drive_file.name,
            "mime_type": drive_file.mime_type,
            # Captured at ingestion because permissions depend on it later
            # (matrix §11, the CF's second limb).
            "drive_file_owner_email": drive_file.owner_email,
            "web_view_link": drive_file.web_view_link,
            "state": (MeetingSourceFile.State.SKIPPED if reason
                      else MeetingSourceFile.State.RECORDED),
            "skip_reason": reason,
            "fetched_at": timezone.now(),
        },
    )
    return row, created


def folder_ids_for(watch, client) -> list[str]:
    """The watched folder, plus its direct subfolders (FR-5.1c).

    **One level, and one only.** Some practices keep a folder per client or per
    month, and a watcher reading only direct children finds nothing in those.
    Two levels would be a crawl of somebody's whole Drive from a single link.
    A listing failure here is not fatal: fall back to the folder itself rather
    than skip the poll.
    """
    try:
        return client.describe_folder(watch.folder_id).folder_ids
    except drive_service.DriveUnavailable:
        return [watch.folder_id]


def poll(tenant, *, client=None, parse=True) -> dict:
    """One run of the poller. Also what "Sync now" calls (FR-5.3).

    Returns a small report the health screen reads: what was recorded, what was
    skipped and why, what failed to parse.
    """
    watch = watch_for(tenant)
    if watch is None:
        raise NotConnected("No folder is being watched for this practice.")
    client = client or client_for(tenant)
    # The folder and one level below it, re-read each poll so a subfolder added
    # last week is watched this week without anyone reconnecting anything.
    folder_ids = folder_ids_for(watch, client)

    recorded, skipped, failed = [], [], []
    token = watch.page_token or client.start_token()
    safe_token = token
    try:
        while True:
            page = client.changes(token, folder_ids=folder_ids)
            for drive_file in page.files:
                row, created = record(tenant, drive_file)
                if row is None:
                    continue
                if row.state == MeetingSourceFile.State.SKIPPED:
                    skipped.append(row)
                elif created:
                    recorded.append(row)
            # Every file in this page is durably written, so the cursor may
            # move to the next page — and no further.
            safe_token = page.next_page_token or page.new_start_page_token or token
            if not page.next_page_token:
                break
            token = page.next_page_token
    except drive_service.DriveUnavailable as exc:
        watch.last_error = str(exc)
        watch.last_polled_at = timezone.now()
        watch.save(update_fields=["last_error", "last_polled_at", "updated_at"])
        return {"recorded": [], "skipped": [], "failed": [], "error": str(exc)}

    watch.page_token = safe_token
    watch.last_error = ""
    watch.last_polled_at = timezone.now()
    watch.save(update_fields=["page_token", "last_error", "last_polled_at",
                              "updated_at"])

    if parse:
        from apps.meetings import parsing

        # Everything recorded and not yet parsed, including anything left over
        # from a previous run that failed — which is why a bad key costs a
        # retry and not a document.
        # Capped. A backlog — a restored database, an interrupted backfill —
        # must not turn one poll into a hundred Claude calls at once. What is
        # left over is picked up by the next poll, oldest first.
        for row in MeetingSourceFile.objects.filter(
                state__in=[MeetingSourceFile.State.RECORDED,
                           MeetingSourceFile.State.FAILED]
                ).order_by("created_at")[:PARSE_PER_POLL]:
            proposal = parsing.parse(row, client=client)
            if proposal is None:
                failed.append(row)
    return {"recorded": recorded, "skipped": skipped, "failed": failed, "error": ""}


def health(tenant) -> dict:
    """One screen's worth: where we are, when we last looked, what is stuck."""
    from apps.crm.models import GmailConnection

    watch = watch_for(tenant)
    connection = drive_connection(tenant)
    pending = MeetingSourceFile.objects.filter(
        state__in=[MeetingSourceFile.State.RECORDED, MeetingSourceFile.State.PARSING,
                   MeetingSourceFile.State.FAILED]).count()
    return {
        "connected": watch is not None,
        # The two steps of connecting, reported separately, because they fail
        # separately and the screen has to say which one is not done.
        "google_connected": GmailConnection.objects.filter(tenant=tenant).exists(),
        "drive_access": connection is not None,
        "drive_account": connection.email_address if connection else "",
        "folder_id": watch.folder_id if watch else "",
        "folder_name": watch.folder_name if watch else "",
        "last_polled_at": watch.last_polled_at.isoformat()
        if watch and watch.last_polled_at else None,
        "last_error": watch.last_error if watch else "",
        "has_cursor": bool(watch.page_token) if watch else False,
        "files_pending": pending,
        "files_failed": MeetingSourceFile.objects.filter(
            state=MeetingSourceFile.State.FAILED).count(),
        "files_skipped": MeetingSourceFile.objects.filter(
            state=MeetingSourceFile.State.SKIPPED).count(),
        "backfill": _backfill_state(),
    }


def _backfill_state():
    """The folder import, if one has been decided (FR-5.1b). In `health` so
    the queue screen learns about it in the call it already makes."""
    from apps.meetings.models import DriveBackfill
    from apps.meetings.serializers import represent_backfill

    return represent_backfill(
        DriveBackfill.objects.order_by("-created_at").first())
