"""One line per thing in the meeting queue (owner, 2026-10-20).

A promise to the client used to be read twice: once as an action item ("send
the SOP draft by Friday") and once as a deliverable ("the SOP draft"), and
approving both made two tasks. The prompt now asks for each item once, with a
promise flagged on the action item. Proposals read before that keep their
shape, but before one is shown, a pending deliverable that says the same as a
pending action item is folded into it: the action item is marked promised to
the client, takes the deliverable's date if it had none, and the deliverable
row goes. Nothing has been created from a pending row, so nothing is lost.
"""

from __future__ import annotations

import re

from apps.meetings.models import ProposalItem

#: Words that say nothing about which thing a line is about.
_FILLER = {
    "a", "an", "the", "to", "of", "for", "and", "or", "on", "in", "by", "with", "at",
    "from", "their", "our", "your", "his", "her", "its", "will", "would", "should",
    "send", "sends", "sent", "share", "provide", "deliver", "get", "give", "them",
    "it", "this", "that", "be", "is", "are", "up", "over", "back", "new",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _FILLER}


def same(a_text: str, a_excerpt: str, b_text: str, b_excerpt: str) -> bool:
    """Two lines about the same thing: the same sentence in the notes, or
    nearly the same words once the filler is gone."""
    if a_excerpt.strip() and a_excerpt.strip() == b_excerpt.strip():
        return True
    a, b = _words(a_text), _words(b_text)
    if not a or not b:
        return False
    if a == b:
        return True
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    if len(smaller) >= 2 and smaller <= larger:
        return True
    return len(a & b) / len(a | b) >= 0.6


def twin(items, text: str, excerpt: str):
    """The pending action item among `items` that says the same, or None."""
    return next((row for row in items
                 if same(row.payload.get("text", ""), row.source_excerpt, text, excerpt)),
                None)


def fold(proposal) -> int:
    """Fold this proposal's pending deliverables into the pending action items
    they repeat. Returns how many were folded; a second call folds none."""
    pending = list(ProposalItem.objects.filter(proposal=proposal,
                                               state=ProposalItem.State.PENDING,
                                               kind__in=(ProposalItem.Kind.ACTION_ITEM,
                                                         ProposalItem.Kind.DELIVERABLE)))
    actions = [row for row in pending if row.kind == ProposalItem.Kind.ACTION_ITEM]
    folded = 0
    for row in pending:
        if row.kind != ProposalItem.Kind.DELIVERABLE:
            continue
        body = row.payload or {}
        match = twin(actions, body.get("text", ""), row.source_excerpt)
        if match is None:
            continue
        merge_into(match, body)
        row.delete()
        folded += 1
    return folded


def merge_into(action, promise: dict) -> None:
    """Mark the action item as the promise, keeping a date it lacked."""
    body = dict(action.payload or {})
    body["promised_to_client"] = True
    if not body.get("proposed_due_date") and promise.get("proposed_due_date"):
        body["proposed_due_date"] = promise["proposed_due_date"]
    action.payload = body
    action.save(update_fields=["payload", "updated_at"])


def fold_open(proposals) -> None:
    """`fold` for each of these proposals that has a pending deliverable."""
    from apps.meetings.models import MeetingProposal

    ids = set(ProposalItem.objects.filter(
        proposal__in=proposals, kind=ProposalItem.Kind.DELIVERABLE,
        state=ProposalItem.State.PENDING).values_list("proposal_id", flat=True))
    for proposal in MeetingProposal.objects.filter(pk__in=ids):
        fold(proposal)
