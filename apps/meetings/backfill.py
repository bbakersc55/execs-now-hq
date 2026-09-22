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

from django.db.models import Avg
from django.utils import timezone

from apps.meetings import drive as drive_service
from apps.meetings import ingest
from apps.meetings.models import DriveBackfill, MeetingSourceFile

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
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


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


def _readable_outstanding(tenant, client, info, since=None) -> list:
    """Files this would actually read: readable, not trashed, not already in.

    Filtering by what is already recorded is what makes the count honest after
    a first backfill, and what makes running a second one cheap to reason
    about — it can only ever be the part that was left out.
    """
    already = set(MeetingSourceFile.objects.values_list("drive_file_id", flat=True))
    found = client.files_in(info.folder_ids,
                            created_from=_iso(since) if since else "",
                            page_size=1000, max_pages=10)
    return [f for f in found
            if not f.trashed
            and not drive_service.skip_reason(f.mime_type)
            and f.file_id not in already]


def survey(tenant, *, client=None) -> dict:
    """What the folder holds and what reading all of it would cost.

    One Drive listing, nothing written. This is what the screen shows **before**
    anything is chosen.
    """
    watch = ingest.watch_for(tenant)
    if watch is None:
        raise BackfillRefused("No folder is connected.", status=409)
    client = client or ingest.client_for(tenant)
    info = client.describe_folder(watch.folder_id)
    outstanding = _readable_outstanding(tenant, client, info)
    per_note, measured = per_note_estimate(tenant)

    return {
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


def plan(tenant, since: date, *, client=None) -> dict:
    """The same numbers for one cut-off date — what option (b) would take.

    Asked again each time the date changes, because a count and a cost the
    fractional has not seen is a cost they have not agreed to.
    """
    watch = ingest.watch_for(tenant)
    if watch is None:
        raise BackfillRefused("No folder is connected.", status=409)
    client = client or ingest.client_for(tenant)
    info = client.describe_folder(watch.folder_id)
    outstanding = _readable_outstanding(tenant, client, info, since=since)
    per_note, measured = per_note_estimate(tenant)
    return {
        "since": since.isoformat(),
        "outstanding": len(outstanding),
        "per_note_usd": str(per_note),
        "per_note_is_measured": measured,
        "estimate_usd": str((per_note * len(outstanding)).quantize(Decimal("0.01"))),
        "minutes": _minutes(len(outstanding)),
    }


def current(tenant) -> DriveBackfill | None:
    """The backfill running on this folder, or the last decision made about it."""
    return DriveBackfill.objects.order_by("-created_at").first()


def start(tenant, *, scope: str, since=None, actor=None, client=None) -> DriveBackfill:
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
            tenant=tenant, watch=watch, scope=scope,
            state=DriveBackfill.State.DECLINED, started_by=actor,
            finished_at=timezone.now())

    counts = (plan(tenant, since, client=client) if scope == DriveBackfill.Scope.SINCE
              else survey(tenant, client=client))
    return DriveBackfill.objects.create(
        tenant=tenant, watch=watch, scope=scope, since=since,
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


def step(tenant, *, client=None, limit: int = PER_TICK) -> dict:
    """One tick of the import: a few files, **recorded and then parsed**, in
    exactly the two steps and the same order the poll uses.

    A Drive failure ends the tick with the cursor where it was, so the next one
    retries those files rather than walking past them — the same promise
    FR-5.5 makes about the poll.
    """
    from apps.meetings import parsing

    backfill = DriveBackfill.objects.filter(
        state=DriveBackfill.State.RUNNING).order_by("created_at").first()
    if backfill is None:
        return {"running": False}

    page_size = max(limit * 4, 20)
    try:
        client = client or ingest.client_for(tenant)
        info = client.describe_folder(backfill.watch.folder_id)
        found = client.files_in(info.folder_ids,
                                created_from=backfill.after_created_time,
                                page_size=page_size)
    except (ingest.NotConnected, drive_service.DriveUnavailable) as exc:
        backfill.last_error = str(exc)
        backfill.save(update_fields=["last_error", "updated_at"])
        return {"running": True, "error": str(exc)}

    read = skipped = failed = 0
    walked, seen = backfill.after_created_time, 0
    for drive_file in found:
        if read >= limit:
            break
        seen += 1
        # Advanced per file, not per batch: the cursor is "everything up to
        # here has been looked at", which is true whether the file was read,
        # skipped, or had been recorded already.
        walked = drive_file.created_time or walked
        row, created = ingest.record(tenant, drive_file)
        if row is None or not created:
            continue
        if row.state == MeetingSourceFile.State.SKIPPED:
            skipped += 1
            continue
        proposal = parsing.parse(row, client=client, trigger="backfill")
        if proposal is None:
            failed += 1
            continue
        read += 1
        if proposal.ai_call is not None:
            backfill.cost_usd += proposal.ai_call.cost_usd

    backfill.after_created_time = walked or backfill.after_created_time
    backfill.done += read
    backfill.skipped += skipped
    backfill.failed += failed
    backfill.last_error = ""
    # Drive returned less than a full page and we reached the end of it, so
    # there is nothing further back there to walk to.
    if not found or (seen == len(found) < page_size):
        backfill.state = DriveBackfill.State.DONE
        backfill.finished_at = timezone.now()
    backfill.save()
    return {"running": backfill.is_running, "read": read, "skipped": skipped,
            "failed": failed, "cost": str(backfill.cost_usd)}
