"""Track's lists a form draws its choices from, kept per company.

Read live from Track at most about once an hour (or at once with "Refresh
from Track now"), stored in `TrackListSnapshot`, and read from there: the form
still works from the last copy while Track is down.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import TrackListSnapshot
from .trackread import fetch  # noqa: F401  (the lists' reading is pure, for the proof)

FRESH_FOR = timedelta(hours=1)

KINDS = ("bed_types", "bathroom_amenities", "amenities", "amenity_groups", "lodging_types",
         "unit_types", "nodes", "code_types", "custom_fields", "contracts", "block_reasons")


def stored(company) -> tuple[dict, object]:
    """(lists, fetched_at of the oldest) from the snapshots; empty lists for
    any never fetched."""
    rows = {s.kind: s for s in TrackListSnapshot.all_objects.filter(company=company)}
    lists = {kind: (rows[kind].payload if kind in rows else []) for kind in KINDS}
    oldest = min((r.fetched_at for r in rows.values()), default=None)
    return lists, oldest


def save(company, lists: dict):
    now = timezone.now()
    for kind in KINDS:
        TrackListSnapshot.all_objects.update_or_create(
            company=company, kind=kind,
            defaults={"tenant_id": company.tenant_id, "payload": lists.get(kind) or [],
                      "fetched_at": now})


def lists_for(company, *, refresh=False, client_factory=None) -> tuple[dict, dict]:
    """(lists, status). Refreshes from Track when asked or when the copy is
    over an hour old; if Track can't be read, the last copy is used and the
    status says so. `status`: {"fetched_at", "stale", "error"}."""
    from apps.scorecard import feeds, track

    lists, fetched_at = stored(company)
    due = refresh or fetched_at is None or timezone.now() - fetched_at > FRESH_FOR
    error = ""
    if due:
        try:
            client = (client_factory or feeds.track_client)(company)
            lists = fetch(client)
            save(company, lists)
            fetched_at = timezone.now()
        except track.TrackUnavailable as exc:
            error = str(exc)
    return lists, {"fetched_at": fetched_at.isoformat() if fetched_at else None,
                   "stale": bool(error) or fetched_at is None, "error": error}
