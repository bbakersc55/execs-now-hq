"""Reading what was already in the folder (FR-5.1b).

**Why this exists.** Drive's `changes.list` starts from a token that means
"now". A freshly connected folder holding six months of notes is, to the
poller, empty — it will see the next meeting and never the last hundred. On the
owner's own folder that was 167 readable notes the queue could not see, and
"Sync now" honestly reporting `0 waiting`.

**Why it is a choice and not a fix.** Importing that history is one Claude call
per note. On 167 notes that is real money and a review queue holding six months
of work, most of it long settled. A practice connecting a folder mid-engagement
may want all of it; one connecting a folder of archived calls may want none.
So the app counts what is there, says what it would cost, and asks — and
`NOW` is recorded as a decision rather than left as an absence, so the queue
being empty is explicable later.

**Why it is paced.** Three notes a minute, oldest first. The cluster keeps
serving the app, the review queue fills in the order the engagement happened,
and **the spend is visible while it runs** instead of arriving as one number
afterwards. Stopping it is one click, and what has been read stays read.

Every file goes through `ingest.record` and then `parsing.parse` — the same two
steps, in the same order, as the poll. There is no second ingestion path, so
there is nothing for the two to disagree about.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from contextlib import contextmanager

from django.db import connection
from django.db.models import Avg, F
from django.utils import timezone

from apps.meetings import drive as drive_service
from apps.meetings import ingest
from apps.meetings.models import DriveBackfill, DriveWatchFolder, MeetingSourceFile

#: Files per tick, with the tick a minute apart. Deliberately unhurried: a
#: hundred Claude calls landing at once would starve the digest tick and turn
#: the spend into something you read about afterwards.
PER_TICK = 3

#: What one note costs to read, before there is any history to go on. Opus 5 at
#: $5/$25 per Mtok against a note of about 4,000 in and 1,500 out. Stated as an
#: estimate everywhere it is shown, and replaced by the practice's own average
#: as soon as it has one.
ESTIMATE_TOKENS = (4000, 1500)


class BackfillRefused(Exception):
    def __init__(self, message, status=400, extra=None):
        super().__init__(message)
        self.status = status
        #: More to say than the message — the over-balance question's figures.
        self.extra = extra or {}


def per_note_estimate(tenant) -> tuple[Decimal, bool]:
    """What a note costs to read: `(amount, measured)`.

    The practice's own average beats our model the moment there is one — note
    lengths vary far more between practices than between notes — and the
    screen says which of the two it is showing.
    """
    from django.conf import settings

    from apps.meetings.parsing import PARSE_PURPOSE
    from apps.tenancy import claude
    from apps.tenancy.models import AiCall

    average = AiCall.objects.filter(
        purpose=PARSE_PURPOSE, succeeded=True, cost_usd__gt=0
    ).aggregate(Avg("cost_usd"))["cost_usd__avg"]
    if average:
        return Decimal(average).quantize(Decimal("0.0001")), True
    modelled = claude.cost_of(settings.ANTHROPIC_MODEL, *ESTIMATE_TOKENS)
    return modelled.quantize(Decimal("0.0001")), False


def _iso(value: date) -> str:
    return datetime(value.year, value.month, value.day,
                    tzinfo=dt_timezone.utc).isoformat().replace("+00:00", "Z")


def _minutes(count: int) -> int:
    """Roughly how long, at the paced rate. Stated so nobody watches it."""
    return -(-count // PER_TICK) if count else 0


def _listing(client, folder_id, folder, *, created_from="", page_size=50,
             max_pages=1, info=None) -> list:
    """What is in a folder to import, oldest first.

    The watch's own folder, or an extra one-level folder, is listed by parent
    as it always was. A folder watched **at any depth** is searched by its
    name pattern instead and each hit placed under it (`drive.locate`) —
    Drive cannot list "everything below" in one query.
    """
    if folder is not None and folder.depth == DriveWatchFolder.Depth.ANY:
        return client.search(folder.name_pattern, roots=[folder.folder_id],
                             created_from=created_from, page_size=page_size,
                             max_pages=max_pages)
    info = info or client.describe_folder(folder_id)
    found = client.files_in(info.folder_ids, created_from=created_from,
                            page_size=page_size, max_pages=max_pages)
    return [f for f in found if ingest.name_matches(f, folder)]


def _readable_outstanding(tenant, client, info, since=None, *, folder=None,
                          watch=None) -> tuple[list, list, list]:
    """Files this would actually read — readable, not trashed, not already in,
    not excluded, not a meeting already recorded — and, separately, the ones
    the exclusion list keeps out and the ones that are the same meeting as a
    note already recorded from any watched folder (or listed earlier here).

    Filtering by what is already recorded is what makes the count honest after
    a first backfill, and what makes running a second one cheap to reason
    about — it can only ever be the part that was left out. Excluded files cost
    nothing (they are never read) and are counted apart, so the estimate is
    only ever for what will reach Claude.
    """
    already = set(MeetingSourceFile.objects.values_list("drive_file_id", flat=True))
    patterns = ingest.exclusions_for(watch) if watch else []
    found = _listing(client, info.folder_id if info else folder.folder_id, folder,
                     created_from=_iso(since) if since else "",
                     page_size=1000, max_pages=10, info=info)
    candidates = [f for f in found
                  if not f.trashed
                  and not drive_service.skip_reason(f.mime_type)
                  and f.file_id not in already]
    excluded = [f for f in candidates if ingest.excluded_by(f, patterns)]
    seen = ingest.recorded_meeting_keys()
    outstanding, same_meeting = [], []
    for f in sorted((f for f in candidates if f not in excluded),
                    key=lambda f: f.created_time):
        key = ingest.meeting_key(f.name)
        if key and key in seen:
            same_meeting.append(f)
            continue
        if key:
            seen.add(key)
        outstanding.append(f)
    return outstanding, excluded, same_meeting


def survey(tenant, *, client=None, folder=None) -> dict:
    """What the folder holds and what reading all of it would cost.

    One Drive listing, nothing written. This is what the screen shows **before**
    anything is chosen. `folder` is one of the watch's extra folders; none
    means the watch's own.
    """
    watch = ingest.watch_for(tenant)
    if watch is None:
        raise BackfillRefused("No folder is connected.", status=409)
    client = client or ingest.client_for(tenant)
    if folder is not None and folder.depth == DriveWatchFolder.Depth.ANY:
        return _survey_deep(tenant, client, watch, folder)
    info = client.describe_folder(folder.folder_id if folder else watch.folder_id)
    outstanding, excluded, same = _readable_outstanding(tenant, client, info,
                                                        folder=folder, watch=watch)
    per_note, measured = per_note_estimate(tenant)

    return {
        "folder": str(folder.pk) if folder else None,
        "excluded": len(excluded),
        "already_recorded": len(same),
        "shared_with": _shared_with_other_folders(tenant, client, watch, folder, outstanding),
        "folder_name": info.name,
        "readable_here": info.readable,
        "readable_in_subfolders": info.readable_below,
        # Named, not counted: "nothing is being read" should never be the first
        # way somebody finds out their notes are a level down.
        "subfolders": [{"name": sub.name, "readable": sub.readable}
                       for sub in info.subfolders],
        "readable_total": info.readable_total,
        "outstanding": len(outstanding),
        "oldest": (info.oldest or "")[:10],
        "newest": (info.newest or "")[:10],
        "per_note_usd": str(per_note),
        "per_note_is_measured": measured,
        "estimate_usd": str((per_note * len(outstanding)).quantize(Decimal("0.01"))),
        "minutes": _minutes(len(outstanding)),
    }


def _shared_with_other_folders(tenant, client, watch, folder, outstanding) -> list[dict]:
    """How many of these notes another watched folder's panel offers too.

    Since Google moved Meet Recordings inside Google Meet, the same file is
    under both, and two panels each saying "116 to read" read as 232. Whichever
    is imported first, the other then finds them recorded and reads none of
    them; this says so before anyone chooses. Matched by file, or by meeting.
    """
    mine_ids = {f.file_id for f in outstanding}
    mine_keys = {k for k in (ingest.meeting_key(f.name) for f in outstanding) if k}
    shared = []
    others = [None] + ingest.folders_for(watch)
    for other in others:
        if (other is None and folder is None) or (other is not None and folder is not None
                                                  and other.pk == folder.pk):
            continue
        deep = other is not None and other.depth == DriveWatchFolder.Depth.ANY
        info = None if deep else client.describe_folder(
            other.folder_id if other else watch.folder_id)
        theirs, _, _ = _readable_outstanding(tenant, client, info, folder=other,
                                             watch=watch)
        count = sum(1 for f in theirs if f.file_id in mine_ids
                    or (ingest.meeting_key(f.name) or "") in mine_keys)
        if count:
            shared.append({"folder": str(other.pk) if other else None,
                           "folder_name": other.folder_name if other else watch.folder_name,
                           "count": min(count, len(outstanding))})
    return shared


def _survey_deep(tenant, client, watch, folder) -> dict:
    """The survey for a folder watched at any depth. There is no one-level
    picture to draw of it — Google Meet holds a folder per meeting — so it is
    the matching notes found under it, and their dates."""
    outstanding, excluded, same = _readable_outstanding(tenant, client, None,
                                                        folder=folder, watch=watch)
    everything = _listing(client, folder.folder_id, folder, page_size=1000,
                          max_pages=10)
    dates = sorted(f.created_time for f in everything if f.created_time)
    per_note, measured = per_note_estimate(tenant)
    return {
        "folder": str(folder.pk),
        "excluded": len(excluded),
        "already_recorded": len(same),
        "shared_with": _shared_with_other_folders(tenant, client, watch, folder, outstanding),
        "folder_name": folder.folder_name,
        "readable_here": 0,
        "readable_in_subfolders": len(everything),
        "subfolders": [],
        "readable_total": len(everything),
        "outstanding": len(outstanding),
        "oldest": (dates[0] if dates else "")[:10],
        "newest": (dates[-1] if dates else "")[:10],
        "per_note_usd": str(per_note),
        "per_note_is_measured": measured,
        "estimate_usd": str((per_note * len(outstanding)).quantize(Decimal("0.01"))),
        "minutes": _minutes(len(outstanding)),
    }


def plan(tenant, since: date, *, client=None, folder=None) -> dict:
    """The same numbers for one cut-off date — what option (b) would take.

    Asked again each time the date changes, because a count and a cost the
    fractional has not seen is a cost they have not agreed to.
    """
    watch = ingest.watch_for(tenant)
    if watch is None:
        raise BackfillRefused("No folder is connected.", status=409)
    client = client or ingest.client_for(tenant)
    deep = folder is not None and folder.depth == DriveWatchFolder.Depth.ANY
    info = None if deep else client.describe_folder(
        folder.folder_id if folder else watch.folder_id)
    outstanding, excluded, same = _readable_outstanding(
        tenant, client, info, since=since, folder=folder, watch=watch)
    per_note, measured = per_note_estimate(tenant)
    return {
        "folder": str(folder.pk) if folder else None,
        "excluded": len(excluded),
        "already_recorded": len(same),
        "since": since.isoformat(),
        "outstanding": len(outstanding),
        "per_note_usd": str(per_note),
        "per_note_is_measured": measured,
        "estimate_usd": str((per_note * len(outstanding)).quantize(Decimal("0.01"))),
        "minutes": _minutes(len(outstanding)),
    }


def current(tenant, folder=None) -> DriveBackfill | None:
    """The backfill running on this folder, or the last decision made about it.
    `folder` is an extra folder; none means the watch's own."""
    return DriveBackfill.objects.filter(folder=folder).order_by("-created_at").first()


def start(tenant, *, scope: str, since=None, actor=None, client=None,
          folder=None, confirmed: bool = False) -> DriveBackfill:
    """Record the choice. `NOW` records it and reads nothing."""
    watch = ingest.watch_for(tenant)
    if watch is None:
        raise BackfillRefused("No folder is connected.", status=409)
    if scope not in DriveBackfill.Scope.values:
        raise BackfillRefused("Choose now, since a date, or everything.")
    if scope == DriveBackfill.Scope.SINCE and since is None:
        raise BackfillRefused("Since when? Give a date to import from.")
    if DriveBackfill.objects.filter(state=DriveBackfill.State.RUNNING).exists():
        raise BackfillRefused("An import is already running on this folder.",
                              status=409)

    if scope == DriveBackfill.Scope.NOW:
        # A decision, not an absence. Six months from now, "why did the queue
        # start empty" has an answer with a date and a name on it.
        return DriveBackfill.objects.create(
            tenant=tenant, watch=watch, scope=scope, folder=folder,
            state=DriveBackfill.State.DECLINED, started_by=actor,
            finished_at=timezone.now())

    counts = (plan(tenant, since, client=client, folder=folder)
              if scope == DriveBackfill.Scope.SINCE
              else survey(tenant, client=client, folder=folder))
    # An import that would run past the estimated balance asks first
    # (owner, 2026-09-28). A question, not a refusal: the balance is a guess.
    from apps.tenancy import ai_budget

    ask = ai_budget.over_balance(tenant, Decimal(counts["estimate_usd"]))
    if ask and not confirmed:
        raise BackfillRefused(
            f"This import should cost about ${ask['estimated_cost']}, more than the "
            f"estimated ${ask['estimated_balance']} left on the Anthropic account. "
            "Import anyway?", status=409, extra=ask)
    return DriveBackfill.objects.create(
        tenant=tenant, watch=watch, scope=scope, since=since, folder=folder,
        state=DriveBackfill.State.RUNNING, started_by=actor,
        planned=counts["outstanding"],
        estimated_cost_usd=Decimal(counts["estimate_usd"]),
        after_created_time=_iso(since) if since else "")


def cancel(backfill, *, actor=None) -> DriveBackfill:
    """Stop. **What has been read stays read** — the proposals already in the
    queue are somebody's work, not this job's property."""
    if not backfill.is_running:
        raise BackfillRefused("That import is not running.", status=409)
    backfill.state = DriveBackfill.State.CANCELLED
    backfill.finished_at = timezone.now()
    backfill.save(update_fields=["state", "finished_at", "updated_at"])
    return backfill


@contextmanager
def _one_tick_at_a_time(tenant):
    """Only one backfill tick per practice at once.

    A tick is three Claude calls and can outlast the minute between ticks. On
    2026-09-28 overlapping ticks each saved their own copy of the counters over
    the other's: the import reported 14 notes and $1.65 when the AI log shows
    29 calls and $3.82. A Postgres advisory lock, held for the tick and not in
    a transaction, so a failure part-way keeps the proposals it paid for.
    """
    key = f"meetings.backfill:{tenant.pk}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", [key])
        got = cursor.fetchone()[0]
    try:
        yield got
    finally:
        if got:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", [key])


def step(tenant, *, client=None, limit: int = PER_TICK) -> dict:
    """One tick of the import: a few files, **recorded and then parsed**, in
    exactly the two steps and the same order the poll uses.

    A Drive failure ends the tick with the cursor where it was, so the next one
    retries those files rather than walking past them — the same promise
    FR-5.5 makes about the poll.

    **It reads only files the app has never recorded, in any version.** The
    survey counts that way, so the import now does what the count said; a new
    version of a note already in is the poll's business, not history's. Before
    2026-09-28 a version bump made an already-imported note look new here.
    """
    with _one_tick_at_a_time(tenant) as ours:
        if not ours:
            return {"running": True, "busy": True}
        return _step(tenant, client=client, limit=limit)


def _step(tenant, *, client=None, limit: int = PER_TICK) -> dict:
    from apps.meetings import parsing

    backfill = DriveBackfill.objects.filter(
        state=DriveBackfill.State.RUNNING).order_by("created_at").first()
    if backfill is None:
        return {"running": False}

    page_size = max(limit * 4, 20)
    try:
        client = client or ingest.client_for(tenant)
        found = _listing(client, backfill.watch.folder_id, backfill.folder,
                         created_from=backfill.after_created_time,
                         page_size=page_size)
    except (ingest.NotConnected, drive_service.DriveUnavailable) as exc:
        DriveBackfill.objects.filter(pk=backfill.pk).update(
            last_error=str(exc), updated_at=timezone.now())
        return {"running": True, "error": str(exc)}

    patterns = ingest.exclusions_for(backfill.watch)
    meetings = ingest.recorded_meeting_keys()
    read = skipped = failed = 0
    cost = Decimal(0)
    walked, seen = backfill.after_created_time, 0
    for drive_file in found:
        if read >= limit:
            break
        seen += 1
        # Advanced per file, not per batch: the cursor is "everything up to
        # here has been looked at", which is true whether the file was read,
        # skipped, or had been recorded already.
        walked = drive_file.created_time or walked
        if MeetingSourceFile.objects.filter(drive_file_id=drive_file.file_id).exists():
            continue                  # Already in, at some version.
        key = ingest.meeting_key(drive_file.name)
        if key and key in meetings:
            continue                  # The same meeting, recorded from another file.
        if key:
            meetings.add(key)
        row, created = ingest.record(
            tenant, drive_file, folder=backfill.folder,
            excluded=ingest.excluded_by(drive_file, patterns))
        if row is None or not created:
            continue
        if row.state == MeetingSourceFile.State.SKIPPED:
            skipped += 1          # an unsupported type, or excluded: never read
            continue
        if not parsing.claim(row):
            continue                  # The poll has it.
        proposal = parsing.parse(row, client=client, trigger="backfill")
        if proposal is None:
            if row.state == MeetingSourceFile.State.SKIPPED:
                skipped += 1
            else:
                failed += 1
            continue
        read += 1
        if proposal.ai_call is not None:
            cost += proposal.ai_call.cost_usd

    # Increments, not a save of this tick's copy: a Stop pressed during the
    # tick must stay pressed, and no count is ever written over another.
    finished = not found or (seen == len(found) < page_size)
    DriveBackfill.objects.filter(pk=backfill.pk).update(
        after_created_time=walked or backfill.after_created_time,
        done=F("done") + read, skipped=F("skipped") + skipped,
        failed=F("failed") + failed, cost_usd=F("cost_usd") + cost,
        last_error="", updated_at=timezone.now())
    if finished:
        # Drive returned less than a full page and we reached the end of it, so
        # there is nothing further back there to walk to.
        DriveBackfill.objects.filter(pk=backfill.pk, state=DriveBackfill.State.RUNNING
                                     ).update(state=DriveBackfill.State.DONE,
                                              finished_at=timezone.now())
    backfill.refresh_from_db()
    return {"running": backfill.is_running, "read": read, "skipped": skipped,
            "failed": failed, "cost": str(backfill.cost_usd)}
