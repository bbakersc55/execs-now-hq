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

import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.meetings import drive as drive_service
from apps.meetings.models import (
    DriveExclusion, DriveWatch, DriveWatchFolder, MeetingSourceFile,
)


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


# ------------------------------------------------ folders, patterns, exclusions

#: What every watch starts with (owner, 2026-09-28): the owner's other work
#: shares this Google account and its Meet folder, and must never be read here.
SEED_EXCLUSIONS = ("AoA", "Academy of America")


def folders_for(watch) -> list:
    """The watch's extra folders. The watch's own folder is not among them."""
    return list(DriveWatchFolder.objects.filter(watch=watch, is_active=True))


def exclusions_for(watch) -> list[str]:
    """The live exclusion patterns, putting the starting ones on first if this
    watch has never had them. Once only: a pattern the FF removes stays gone."""
    if not watch.exclusions_seeded:
        with transaction.atomic():
            locked = DriveWatch.objects.select_for_update().get(pk=watch.pk)
            if not locked.exclusions_seeded:
                for pattern in SEED_EXCLUSIONS:
                    DriveExclusion.objects.create(
                        tenant_id=locked.tenant_id, watch=locked, pattern=pattern,
                        source=DriveExclusion.Source.SEED)
                locked.exclusions_seeded = True
                locked.save(update_fields=["exclusions_seeded", "updated_at"])
        watch.exclusions_seeded = True
    return list(DriveExclusion.objects.filter(watch=watch, deleted_at__isnull=True)
                .values_list("pattern", flat=True))


def excluded_by(drive_file, patterns) -> str:
    """The first pattern the file's name, or a folder it sits in, contains as
    a whole word or phrase, ignoring case; `""` when none does.

    Whole words, because "AoA" as a bare substring is inside other words, and
    an exclusion that quietly swallows a client's meeting is worse than one
    that misses. Folder names come from `path_names`, which is filled for
    folders watched at any depth; for the watch's own folder it is the file's
    name alone.
    """
    titles = [drive_file.name or "", *(drive_file.path_names or [])]
    for pattern in patterns:
        words = (pattern or "").strip()
        if not words:
            continue
        rx = re.compile(r"(?<!\w)" + re.escape(words) + r"(?!\w)", re.IGNORECASE)
        if any(rx.search(title) for title in titles):
            return words
    return ""


_MEETING_DATE = re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})(?:\s+(\d{1,2}):(\d{2}))?")
_KIND_SUFFIX = re.compile(r"\s*[-\u2013]\s*(notes by gemini|transcript)\s*$", re.IGNORECASE)


def meeting_key(name: str) -> str | None:
    """Which meeting a notes file is about, from its name: the title, the
    date, and the start time when the name has one (owner, 2026-09-28).

    Google names notes "<title> - 2026/09/24 17:35 MDT - Notes by Gemini", and
    since it moved Meet Recordings inside Google Meet the same meeting can be
    offered by two watched folders. The time is part of the key because
    untitled meetings are all "Meeting started" — two of them on 9/10, at 08:40
    and 08:57, are two meetings, not one. `None` when there is no date to go on:
    such a file is never treated as a duplicate.
    """
    stem = re.sub(r"\.(txt|docx?)$", "", (name or "").strip(), flags=re.IGNORECASE)
    stem = _KIND_SUFFIX.sub("", stem)
    found = _MEETING_DATE.search(stem)
    if not found:
        return None
    title = re.sub(r"[\s\-\u2013(]+$", "", stem[:found.start()])
    title = re.sub(r"\s+", " ", title).strip().lower()
    year, month, day, hour, minute = found.groups()
    when = f"{int(hour):02d}:{minute}" if hour else ""
    return f"{title}|{year}-{month}-{day}|{when}"


def recorded_meeting_keys() -> set[str]:
    """The meetings already recorded, from any watched folder, in any state —
    read, skipped, excluded or dismissed alike: each is already accounted for."""
    return {key for key in (meeting_key(name) for name in
                            MeetingSourceFile.objects.values_list("name", flat=True))
            if key}


def name_matches(drive_file, folder) -> bool:
    """Whether an extra folder's name pattern lets this file in. The watch's
    own folder (`folder is None`) has no pattern and reads every readable file,
    as it always has."""
    if folder is None or not folder.name_pattern:
        return True
    return (drive_file.mime_type == drive_service.GOOGLE_DOC
            and folder.name_pattern.lower() in (drive_file.name or "").lower())


def describe_folder(tenant, folder_id, *, client=None):
    """What that folder is, read live (FR-5.1a). Raises rather than guessing."""
    return (client or client_for(tenant)).describe_folder(folder_id)


@transaction.atomic
def record(tenant, drive_file, *, folder=None,
           excluded: str = "") -> tuple[MeetingSourceFile | None, bool]:
    """Write one file down. Returns `(row, created)`.

    Idempotent on `(tenant, file, version)`: the second poll of an unchanged
    file finds the row and changes nothing.

    `excluded` is the exclusion pattern that matched, if one did: the file is
    recorded as skipped with that reason, so it is on the record and counted,
    and **nothing downstream ever fetches it or sends it to Claude** — parsing
    only ever picks up `recorded` and `failed` rows.
    """
    if drive_file.trashed:
        return None, False
    reason = drive_service.skip_reason(drive_file.mime_type)
    if excluded:
        reason = (f"Not read: \u201c{excluded}\u201d is on the exclusion list, "
                  "and this file's title or a folder it sits in matches it.")
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
            "excluded_by": excluded,
            "folder": folder,
            "fetched_at": timezone.now(),
        },
    )
    return row, created


def ids_below(folder_id, client) -> list[str]:
    """One folder and its direct subfolders, the way `folder_ids_for` reads the
    watch's own folder. Falls back to the folder alone."""
    try:
        return client.describe_folder(folder_id).folder_ids
    except drive_service.DriveUnavailable:
        return [folder_id]


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
    from config import environment

    if environment.is_demo():
        raise NotConnected(environment.DEMO_REFUSAL)
    watch = watch_for(tenant)
    if watch is None:
        raise NotConnected("No folder is being watched for this practice.")
    client = client or client_for(tenant)
    # The folder and one level below it, re-read each poll so a subfolder added
    # last week is watched this week without anyone reconnecting anything.
    folder_ids = folder_ids_for(watch, client)
    # Extra folders: one-level ones widen the same list; any-depth ones are
    # found by walking up from each changed file, so a new meeting folder
    # Google made this morning needs no listing to be seen.
    extra = folders_for(watch)
    shallow = {fid: f for f in extra if f.depth == DriveWatchFolder.Depth.ONE
               for fid in ids_below(f.folder_id, client)}
    deep = {f.folder_id: f for f in extra if f.depth == DriveWatchFolder.Depth.ANY}
    patterns = exclusions_for(watch)

    recorded, skipped, failed = [], [], []
    token = watch.page_token or client.start_token()
    safe_token = token
    try:
        while True:
            page = client.changes(token, folder_ids=folder_ids + list(shallow),
                                  deep_roots=list(deep))
            for drive_file in page.files:
                folder = (deep.get(drive_file.root) if drive_file.root else
                          next((shallow[p] for p in drive_file.parents or []
                                if p in shallow), None))
                if not name_matches(drive_file, folder):
                    continue      # Not notes: a recording, a transcript, a chat.
                row, created = record(tenant, drive_file, folder=folder,
                                      excluded=excluded_by(drive_file, patterns))
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
        # A failed file is retried only while its billed failures are under
        # the cap; past it, the queue names it for a person (parsing._failed).
        for row in MeetingSourceFile.objects.filter(
                Q(state=MeetingSourceFile.State.RECORDED)
                | Q(state=MeetingSourceFile.State.FAILED,
                    auto_parse_failures__lt=parsing.MAX_AUTO_PARSE_FAILURES)
                ).order_by("created_at")[:PARSE_PER_POLL]:
            if paused_for_today(tenant):
                break             # Recorded, and read tomorrow (ai_guard).
            if not parsing.claim(row):
                continue          # The backfill has it.
            proposal = parsing.parse(row, client=client)
            if proposal is None:
                (skipped if row.state == MeetingSourceFile.State.SKIPPED
                 else failed).append(row)
    return {"recorded": recorded, "skipped": skipped, "failed": failed, "error": ""}


def paused_for_today(tenant) -> bool:
    """The worker has reached today's cap on unattended AI spend (owner,
    2026-09-29). New files are still recorded, so nothing is missed; they are
    read tomorrow. "Sync now" from the screen is a person asking: never paused."""
    from apps.tenancy import ai_guard, claude

    return claude.current_job() is not None and ai_guard.cap_reached(tenant)


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
        # Failed and no longer retried by itself: each is named in the queue
        # (`drive-watch/failed/`) with Read again.
        "files_needing_person": MeetingSourceFile.objects.filter(
            state=MeetingSourceFile.State.FAILED,
            auto_parse_failures__gte=_max_auto()).count(),
        "files_skipped": MeetingSourceFile.objects.filter(
            state=MeetingSourceFile.State.SKIPPED).count(),
        "backfill": _backfill_state(),
        # Kept out by the exclusion list, per folder: the watch's own here,
        # each extra folder on its own row.
        "excluded": MeetingSourceFile.objects.filter(
            folder__isnull=True).exclude(excluded_by="").count(),
        "folders": [_folder_state(f) for f in folders_for(watch)] if watch else [],
        "exclusions": _exclusion_state(watch) if watch else [],
    }


def _max_auto() -> int:
    from apps.meetings import parsing

    return parsing.MAX_AUTO_PARSE_FAILURES


def _folder_state(folder) -> dict:
    files = MeetingSourceFile.objects.filter(folder=folder)
    return {
        "id": str(folder.pk), "folder_id": folder.folder_id,
        "folder_name": folder.folder_name, "depth": folder.depth,
        "name_pattern": folder.name_pattern,
        "files_recorded": files.count(),
        "excluded": files.exclude(excluded_by="").count(),
    }


def _exclusion_state(watch) -> list[dict]:
    exclusions_for(watch)          # puts the starting ones on, the first time
    return [{"id": str(row.pk), "pattern": row.pattern, "source": row.source}
            for row in DriveExclusion.objects.filter(watch=watch, deleted_at__isnull=True)]


def _backfill_state():
    """The folder import, if one has been decided (FR-5.1b). In `health` so
    the queue screen learns about it in the call it already makes."""
    from apps.meetings.models import DriveBackfill
    from apps.meetings.serializers import represent_backfill

    return represent_backfill(
        DriveBackfill.objects.order_by("-created_at").first())
