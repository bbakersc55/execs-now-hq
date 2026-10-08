"""The notes of the call, attached to its session as context for Claude's
drafts (owner, 2026-10-08).

The practice attaches the meeting-notes document for the call: a file the
meeting queue has already read, a Drive document by its link, or pasted text.
From then on "Draft rows", "Consolidate" and the pros-and-cons draft are given
the notes beside the answers, and a row that rests on the notes says so, with
the passage it rests on.

What this module keeps:

- **The notes are the practice's own.** Read by the practice owner and by an
  associate on their own prospect. Never on the pre-call form, in an email, on
  the PDF, to the prospect, or in an assistant's payload.
- **The faithfulness rule is unchanged.** The notes are input, like the
  answers: a draft may rest on them and on nothing beyond them and the answers.
- **Notes hold both sides of a conversation.** Claude is told so, and told to
  attribute a statement to the prospect only where the notes do.
- **A passage is shown only if it is in the notes.** What Claude cites is
  checked against the text; a citation that is not there is dropped, and the
  row is left unmarked rather than marked on Claude's word.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlparse

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.strategy.models import StrategyCallNotes
from apps.strategy.services import SessionError
from apps.tenancy.models import AuditEvent

S = StrategyCallNotes.Source

#: A long call's notes with a transcript run to tens of thousands of
#: characters. Past this it is more than one call, or not notes.
MOST = 150_000
PASSAGE_MOST = 400
_ID = re.compile(r"[A-Za-z0-9_-]{20,128}")

ROWS_ADDENDUM = """

You are also given THE CALL NOTES: the notes of the conversation itself, taken \
during or after it. They are input, like the answers: a row may rest on what the \
notes record, and you must still assert nothing that is in neither the notes \
nor the answers.

The notes may contain both sides of the conversation, including what the \
advisor said, suggested or asked. Attribute a statement, a figure or a view to \
the prospect ONLY where the notes do. What the advisor said is not something \
the prospect told us, and an advisor's suggestion is not the prospect's plan.

For each row that rests on the notes, add the key "passage": the passage of \
the notes it rests on, copied word for word, one or two sentences. Leave \
"passage" out of a row that rests on the answers alone."""

PATHS_ADDENDUM = """

You are also given THE CALL NOTES: the notes of the conversation itself. They \
are part of this session's own material, and the rule is the same: assert \
nothing that is in neither the notes nor the rest of the input. The notes may \
contain both sides of the conversation, including what the advisor said. \
Attribute a statement or a view to the prospect only where the notes do."""


def of(session) -> StrategyCallNotes | None:
    return StrategyCallNotes.all_objects.filter(
        tenant_id=session.tenant_id, session=session).first()


def block(session) -> str:
    """The notes as Claude is given them, or "" when there are none."""
    notes = of(session)
    if notes is None or not notes.text.strip():
        return ""
    return ("\n\nTHE CALL NOTES (both sides of the conversation may be in them):\n"
            + notes.text.strip())


def _plain(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def passage_in(session_or_text, passage) -> str:
    """The passage, if it really is in the notes (spacing and capitals aside);
    otherwise "". What is shown beside a row as its source is never taken on
    Claude's word."""
    if not isinstance(passage, str) or not passage.strip():
        return ""
    text = session_or_text if isinstance(session_or_text, str) else getattr(
        of(session_or_text), "text", "")
    passage = " ".join(passage.split()).strip(" \"'“”")
    if len(passage) < 12 or _plain(passage) not in _plain(text):
        return ""
    return passage[:PASSAGE_MOST]


# ---------------------------------------------------------------- attaching

def file_id_from(link: str) -> str:
    """A Drive file's id out of whatever was pasted: a Docs or Drive address,
    or the id itself."""
    value = (link or "").strip().strip("<>")
    if not value:
        return ""
    if "/" not in value and "?" not in value:
        return value if _ID.fullmatch(value) else ""
    parsed = urlparse(value if "//" in value else f"https://{value}")
    parts = [part for part in parsed.path.split("/") if part]
    if "d" in parts and parts.index("d") + 1 < len(parts):
        candidate = parts[parts.index("d") + 1]
        return candidate if _ID.fullmatch(candidate) else ""
    for found in parse_qs(parsed.query).get("id", []):
        if _ID.fullmatch(found):
            return found
    return ""


def _clean(text) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise SessionError("There is nothing in those notes.")
    if len(text) > MOST:
        raise SessionError(f"Those notes are {len(text):,} characters; {MOST:,} is the "
                           "most. Attach the notes of this one call.")
    return text


def _from_drive(tenant, link: str) -> tuple[str, str, str]:
    """`(text, title, file id)` through the practice's existing Drive grant,
    or a refusal that says what is missing."""
    from apps.meetings import drive, ingest

    file_id = file_id_from(link)
    if not file_id:
        raise SessionError("That does not look like a Drive or Docs link. Open the "
                           "document and copy its address.")
    try:
        client = ingest.client_for(tenant)
    except ingest.NotConnected as exc:
        raise SessionError(f"{exc} The notes can be pasted in instead.", status=409) from exc
    try:
        found = client.file(file_id)
        if found is None or found.trashed:
            raise SessionError("That document could not be found with the practice's "
                               "Drive access. Check that it is shared with the "
                               "connected account.", status=404)
        reason = drive.skip_reason(found.mime_type)
        if reason:
            raise SessionError(reason)
        text = client.text_of(found)
    except drive.DriveUnavailable as exc:
        raise SessionError(f"Drive could not be read just now: {exc}", status=503) from exc
    return text, found.name, file_id


@transaction.atomic
def attach(session, *, actor, source, text=None, source_file=None, link=None):
    """Attach, or replace, the notes of this session's call."""
    title, drive_file_id, file_row = "", "", None
    if source == S.PASTED:
        title = "Pasted notes"
    elif source == S.MEETING_FILE:
        file_row = source_file
        if file_row is None or file_row.tenant_id != session.tenant_id:
            raise SessionError("That file is not in this practice's meeting queue.",
                               status=404)
        if not (file_row.text or "").strip():
            raise SessionError(f"“{file_row.name}” has not been read into the meeting "
                               "queue, so there is no text to attach.")
        text, title, drive_file_id = file_row.text, file_row.name, file_row.drive_file_id
    elif source == S.DRIVE:
        text, title, drive_file_id = _from_drive(session.tenant, link)
    else:
        raise SessionError("source is meeting_file, drive or pasted.")
    text = _clean(text)
    notes, made = StrategyCallNotes.all_objects.update_or_create(
        tenant_id=session.tenant_id, session=session,
        defaults={"text": text, "source": source, "title": title[:255],
                  "source_file": file_row, "drive_file_id": drive_file_id,
                  "added_by": actor})
    # What was attached, never the notes themselves.
    AuditEvent.all_objects.create(
        tenant_id=session.tenant_id, actor=actor,
        verb="strategy.call_notes_attached" if made else "strategy.call_notes_replaced",
        target_type="strategy_session", target_id=session.pk,
        payload={"source": source, "title": title[:255], "characters": len(text)})
    return notes


@transaction.atomic
def remove(session, *, actor) -> bool:
    notes = of(session)
    if notes is None:
        return False
    AuditEvent.all_objects.create(
        tenant_id=session.tenant_id, actor=actor, verb="strategy.call_notes_removed",
        target_type="strategy_session", target_id=session.pk,
        payload={"source": notes.source, "title": notes.title})
    notes.delete()
    return True


# ------------------------------------------------- what the screen is given

def day_of(session):
    moment = session.scheduled_at or session.started_at or session.created_at
    return timezone.localtime(moment).date()


def candidates(session) -> list[dict]:
    """The meeting queue's recorded files for the day of the call, in any
    state (pending, actioned, dismissed, skipped), that have text."""
    from apps.meetings.models import MeetingSourceFile

    day = day_of(session)
    start = timezone.make_aware(datetime.combine(day, time.min))
    rows = (MeetingSourceFile.all_objects.filter(tenant_id=session.tenant_id)
            .exclude(text="")
            .filter(Q(proposals__meeting_date=day)
                    | Q(fetched_at__gte=start, fetched_at__lt=start + timedelta(days=1))
                    | Q(created_at__gte=start, created_at__lt=start + timedelta(days=1)))
            .distinct().order_by("-created_at"))
    out, seen = [], set()
    for row in rows:
        # One line per document: the newest version the queue has read.
        if row.drive_file_id in seen:
            continue
        seen.add(row.drive_file_id)
        out.append({"id": str(row.pk), "name": row.name,
                    "state": row.get_state_display(), "characters": len(row.text)})
    return out


def represent(session) -> dict | None:
    """The attached notes, for the practice owner or an associate on their own
    prospect. The caller has already decided this reader may have them."""
    notes = of(session)
    if notes is None:
        return None
    by = notes.added_by
    return {"source": notes.source, "source_label": notes.get_source_display(),
            "title": notes.title, "characters": len(notes.text), "text": notes.text,
            "added_by": (by.full_name or by.email) if by else "",
            "added_at": notes.updated_at.isoformat()}
