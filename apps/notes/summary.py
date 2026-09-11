"""Claude's summary of a transcript — REVIEW QUEUE R3 (FR-2.17).

Claude's draft goes to `proposed_summary`. It reaches `summary` only when a
person accepts it (as drafted or edited), and a check constraint refuses any
other way in. Discarding leaves the transcript and no summary.

Who reviews: the note's author, or the FF (whose access is "everything").
"""

from __future__ import annotations

from django.db import transaction

from apps.tenancy import claude
from apps.tenancy.models import AuditEvent, Role

SYSTEM_PROMPT = """\
You summarize a recorded conversation for a fractional executive's private \
working notes. The reader was on the call; this summary is what they keep \
instead of listening again.

Write plain markdown with these sections, leaving out any that would be empty:

**Summary** — two to four sentences: what the conversation was about and where it landed.
**Decisions** — what was agreed.
**Action items** — what, who, and when, only as stated. Write "owner not stated" \
or "no date given" rather than inferring either.
**Open questions** — what was left unresolved.
**Details worth keeping** — figures, names, dates, and commitments someone may \
need in writing later.

The transcript is automatic speech-to-text with no speaker labels. It contains \
recognition errors and does not say who is speaking. Attribute a statement to a \
named person only when the transcript makes the speaker clear. Never add a fact, \
figure, name, date, or commitment that is not in the transcript; if a passage is \
unintelligible, say so rather than guessing. Keep it short enough to read in a \
minute."""


class SummaryError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def can_review(note, membership) -> bool:
    return membership.role == Role.FF or note.created_by_id == membership.user_id


def _audit(note, actor, verb, **payload):
    AuditEvent.all_objects.create(
        tenant=note.tenant, actor=actor, verb=verb,
        target_type="note", target_id=note.pk, payload=payload,
    )


def draft(note) -> None:
    """Ask Claude for a proposal. Failure keeps the transcript (FR-2.18)."""
    from apps.notes.models import Note

    if not (note.transcript or "").strip():
        return
    minutes = round((note.audio_duration_seconds or 0) / 60)
    try:
        text = claude.complete(
            tenant=note.tenant, purpose="note_summary",
            system=SYSTEM_PROMPT,
            user_text=(
                f"Transcript of a recorded call"
                f"{f' ({minutes} minutes)' if minutes else ''}:\n\n"
                f"<transcript>\n{note.transcript}\n</transcript>"
            ),
            target_type="note", target_id=note.pk, trigger="auto",
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused) as exc:
        note.summary_state = Note.SummaryState.FAILED
        note.save(update_fields=["summary_state", "updated_at"])
        _audit(note, None, "note.summary_failed", error=str(exc))
        return
    note.proposed_summary = text
    note.summary_state = Note.SummaryState.PROPOSED
    note.save(update_fields=["proposed_summary", "summary_state", "updated_at"])


@transaction.atomic
def accept(note, *, actor, text=None):
    from apps.notes.models import Note

    if note.summary_state != Note.SummaryState.PROPOSED or not note.proposed_summary:
        raise SummaryError("There is no proposed summary to accept.", status=409)
    edited = text is not None and text.strip() != note.proposed_summary.strip()
    final = (text if text is not None else note.proposed_summary).strip()
    if not final:
        raise SummaryError("An empty summary cannot be accepted. Discard it instead.")
    note.summary = final
    note.summary_state = Note.SummaryState.ACCEPTED
    note.save(update_fields=["summary", "summary_state", "updated_at"])
    _audit(note, actor, "note.summary_accepted", edited=edited)
    return note


@transaction.atomic
def discard(note, *, actor):
    from apps.notes.models import Note

    if note.summary_state != Note.SummaryState.PROPOSED:
        raise SummaryError("There is no proposed summary to discard.", status=409)
    note.proposed_summary = None
    note.summary_state = Note.SummaryState.DISCARDED
    note.save(update_fields=["proposed_summary", "summary_state", "updated_at"])
    _audit(note, actor, "note.summary_discarded")
    return note


@transaction.atomic
def request_redraft(note, *, actor):
    """Queue another draft; the next job run picks it up."""
    from apps.notes.models import Note

    if not (note.transcript or "").strip():
        raise SummaryError("There is no transcript to summarize yet.", status=409)
    if note.summary_state not in (Note.SummaryState.FAILED, Note.SummaryState.DISCARDED):
        raise SummaryError("A summary can be redrafted after it fails or is discarded.",
                           status=409)
    note.summary_state = Note.SummaryState.DRAFTING
    note.save(update_fields=["summary_state", "updated_at"])
    _audit(note, actor, "note.summary_redraft_requested")
    return note
