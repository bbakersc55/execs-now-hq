"""The owner's own stays: held in ENHQ until the unit is bookable in Track,
then placed as unit blocks with the reason "Owner Reservation".

Owner, 2026-11-19:
- checked every hour, and with "Place owner dates now";
- placed once Track reports the unit bookable, however it started;
- a refusal saying the unit isn't bookable keeps the dates held; any other
  refusal goes to the managers with Track's own words;
- a range whose end has passed is marked expired and the managers told;
- held over 30 days: a weekly reminder;
- a manager may cancel held dates.
Whether Track takes a block on a bookable but inactive unit is untested.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from . import notices
from .models import OwnerDate, Submission, SubmissionEvent

REASON = "Owner Reservation"
REMIND_AFTER = timedelta(days=30)
REMIND_EVERY = timedelta(days=7)


def hold(submission):
    """Owner dates from the answers become held rows (on a successful send)."""
    stays = (submission.answers or {}).get("stays") or {}
    if stays.get("has") != "yes":
        return []
    rows = []
    for item in stays.get("ranges") or []:
        try:
            start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
        except (KeyError, ValueError):
            continue
        if end < start:
            start, end = end, start
        rows.append(OwnerDate.all_objects.create(tenant_id=submission.tenant_id,
                                                 submission=submission, start=start, end=end))
    return rows


def _not_bookable(text: str) -> bool:
    return "not bookable" in (text or "").lower()


def place(submission, client, lists, *, today=None, actor=None) -> dict:
    """Try to place every held range of `submission` now. Returns counts and
    a sentence for the person who asked."""
    from apps.scorecard import track

    today = today or timezone.localdate()
    held = list(submission.owner_dates.filter(state=OwnerDate.State.HELD))
    out = {"placed": 0, "held": 0, "refused": 0, "expired": 0, "text": ""}
    unit_id = (submission.track or {}).get("ids", {}).get("unit")
    for row in held:
        if row.end < today:
            row.state = OwnerDate.State.EXPIRED
            row.message = "The dates passed before the unit was bookable in Track."
            row.save(update_fields=["state", "message"])
            out["expired"] += 1
            notices.tell(submission, source_type="intake_dates_expired", source_id=row.pk,
                         email=True, title=f"Owner dates expired, intake #{submission.number}",
                         text=(f"The owner's dates {row.start:%b %-d} to {row.end:%b %-d} "
                               "passed before the unit was bookable in Track, so they were "
                               "never placed."))
    held = [r for r in held if r.state == OwnerDate.State.HELD]
    if not held:
        out["text"] = _words(out)
        return out
    if not unit_id:
        out["held"] = len(held)
        out["text"] = "The unit isn't in Track yet, so the dates stay held."
        return out
    try:
        unit = client.get(f"/pms/units/{unit_id}")
    except track.TrackUnavailable as exc:
        out["held"] = len(held)
        out["text"] = f"Track couldn't be read just now ({exc}). The dates stay held."
        return out
    if not (unit or {}).get("isBookable"):
        out["held"] = len(held)
        out["text"] = "The unit isn't bookable in Track yet, so the dates stay held."
        return out
    reason = next((r for r in lists.get("block_reasons") or [] if r.get("name") == REASON), None)
    if reason is None:
        out["held"] = len(held)
        out["text"] = f"Track has no block reason called {REASON}; the dates stay held."
        return out
    for row in held:
        try:
            answer = client.send("POST", "/pms/unit-blocks", {
                "unitId": unit_id, "reasonId": reason["id"], "startDate": row.start.isoformat(),
                "endDate": row.end.isoformat(), "chargeOwner": False,
                "blockNotes": "Owner's own stay, from the owner intake"})
        except track.TrackRefusal as exc:
            if _not_bookable(str(exc)):
                out["held"] += 1
                continue
            row.state, row.message = OwnerDate.State.REFUSED, str(exc)[:500]
            row.save(update_fields=["state", "message"])
            out["refused"] += 1
            notices.tell(submission, source_type="intake_dates_refused", source_id=row.pk,
                         email=True, title=f"Track refused owner dates, intake #{submission.number}",
                         text=f"{row.start:%b %-d} to {row.end:%b %-d}: {exc}")
            continue
        except track.TrackUnavailable as exc:
            out["held"] += 1
            out["text"] = f"Track couldn't be reached ({exc})."
            continue
        row.state, row.placed_at = OwnerDate.State.PLACED, timezone.now()
        row.block_id = str((answer or {}).get("id") or "")
        row.message = ""
        row.save(update_fields=["state", "placed_at", "block_id", "message"])
        out["placed"] += 1
    if out["placed"]:
        notices.tell(submission, source_type="intake_dates_placed", source_id=None,
                     title=f"Owner dates placed, intake #{submission.number}",
                     text=f"{out['placed']} of the owner's date ranges are now blocked in Track "
                          "as Owner Reservation.")
        SubmissionEvent.all_objects.create(
            tenant_id=submission.tenant_id, submission=submission,
            kind=SubmissionEvent.Kind.DATES, actor=actor,
            detail=f"Placed {out['placed']} owner date range(s) in Track")
    out["text"] = out["text"] or _words(out)
    return out


def _words(out) -> str:
    parts = []
    if out["placed"]:
        parts.append(f"{out['placed']} placed")
    if out["held"]:
        parts.append(f"{out['held']} still held")
    if out["refused"]:
        parts.append(f"{out['refused']} refused by Track")
    if out["expired"]:
        parts.append(f"{out['expired']} expired")
    return (", ".join(parts) + ".").capitalize() if parts else "No held dates."


def remind(submission, *, now=None):
    """Weekly, once dates have been held for 30 days."""
    now = now or timezone.now()
    due = [r for r in submission.owner_dates.filter(state=OwnerDate.State.HELD)
           if now - r.created_at >= REMIND_AFTER
           and (r.last_reminded_at is None or now - r.last_reminded_at >= REMIND_EVERY)]
    if not due:
        return 0
    notices.tell(submission, source_type="intake_dates_waiting", source_id=None, email=True,
                 title=f"Owner dates still held, intake #{submission.number}",
                 text=(f"{len(due)} of the owner's date ranges are still waiting for the unit "
                       "to be bookable in Track. Make it bookable, then press Place owner "
                       "dates now, or cancel the dates."))
    OwnerDate.all_objects.filter(pk__in=[r.pk for r in due]).update(last_reminded_at=now)
    return len(due)


def cancel(row, actor):
    if row.state != OwnerDate.State.HELD:
        return False
    row.state, row.cancelled_by = OwnerDate.State.CANCELLED, actor
    row.save(update_fields=["state", "cancelled_by"])
    SubmissionEvent.all_objects.create(
        tenant_id=row.tenant_id, submission=row.submission, kind=SubmissionEvent.Kind.DATES,
        actor=actor, detail=f"Cancelled held owner dates {row.start} to {row.end}")
    return True


def waiting_submissions(tenant_id):
    return Submission.all_objects.filter(
        tenant_id=tenant_id, status=Submission.Status.SENT,
        owner_dates__state=OwnerDate.State.HELD).distinct()
