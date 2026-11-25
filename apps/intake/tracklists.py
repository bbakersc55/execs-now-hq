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
    """Keep what Track sent. A list that comes back empty never replaces a
    copy that has rows (owner, 2026-11-24: the last good copy of each list):
    that copy stays, with the time it was read, so its age still shows."""
    now = timezone.now()
    kept = {s.kind: s for s in TrackListSnapshot.all_objects.filter(company=company)}
    for kind in KINDS:
        rows = lists.get(kind) or []
        if not rows and kind in kept and kept[kind].payload:
            continue
        TrackListSnapshot.all_objects.update_or_create(
            company=company, kind=kind,
            defaults={"tenant_id": company.tenant_id, "payload": rows, "fetched_at": now})


#: The lists an owner chooses from on the form, by the form's name for each,
#: with the copy's kind and what people call it (owner, 2026-11-24).
OWNER_CHOICES = {
    "bed_types": ("bed_types", "bed types"),
    "bathroom_fixtures": ("bathroom_amenities", "bathroom features"),
    "lodging_types": ("lodging_types", "kinds of property"),
    "code_types": ("code_types", "kinds of code (garage, gate, pool…)"),
    "amenity_groups": ("amenities", "amenities"),
}


def missing_for_owners(lists: dict) -> list[str]:
    """The owner's lists this company has no copy of (Track never read for
    it, or read empty), by the form's names, in the form's order."""
    return [name for name, (kind, _) in OWNER_CHOICES.items()
            if not any(row.get("isActive", True) for row in lists.get(kind) or [])]


def said(names) -> str:
    """"bed types, bathroom features and amenities"."""
    words = [OWNER_CHOICES[n][1] for n in names if n in OWNER_CHOICES]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


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
            save(company, fetch(client))
            fetched_at = timezone.now()
        except track.TrackUnavailable as exc:
            error = str(exc)
        else:
            # What was kept, not what came back: a list Track sent back empty
            # is the last good copy here too (`save`).
            lists, _ = stored(company)
    return lists, {"fetched_at": fetched_at.isoformat() if fetched_at else None,
                   "stale": bool(error) or fetched_at is None, "error": error}
