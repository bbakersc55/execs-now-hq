"""Dismissing a proposal (owner, 2026-09-28).

**Dismiss is not reject.** Rejecting answers one item: "not this task". A
dismissal answers the whole proposal: there was no meeting, it was not the
practice's business, it was a vendor's pitch. Rejecting ten items one by one to
say that is ten clicks and a proposal that still reads as reviewed work.

Three promises, each with a test:

1. **It creates nothing.** Items are left exactly as they were, and closed by
   the proposal's state: nothing is approved, nothing is rejected on anyone's
   behalf, so Restore has nothing to undo but the state.
2. **It never resurfaces.** The source file is marked dismissed; a later
   version of the same Drive file is recorded as skipped rather than read
   (`parsing.parse`), and the backfill never re-reads a file it has recorded.
3. **It is reversible.** Restore puts back the state it replaced and clears the
   file's mark. Both are audited, with the reason.

The one exception to "creates nothing" is the vendor path, which the reviewer
asks for by name: the pitching vendor is recorded through the ordinary
participant approval — so a vendor still cannot exist without the service
categories that find them (FR-5.9c) — and everything else is dismissed.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.meetings import approval
from apps.meetings.models import MeetingProposal, ProposalItem
from apps.tenancy.models import AuditEvent

P = MeetingProposal.State
R = MeetingProposal.DismissReason

#: What can be dismissed. An actioned proposal has nothing left to close.
OPEN = (P.PENDING, P.PARTIALLY_ACTIONED)


@transaction.atomic
def dismiss(proposal, *, actor, reason: str, note: str = "",
            _states=OPEN) -> MeetingProposal:
    if proposal.state not in _states:
        raise approval.ApprovalRefused(
            "Only a proposal still waiting for review can be dismissed.", status=409)
    if reason not in R.values:
        raise approval.ApprovalRefused(
            "Say why: no meeting happened, not relevant, a vendor pitch, or other.")
    note = (note or "").strip()
    if reason == R.OTHER and not note:
        raise approval.ApprovalRefused("“Other” needs a word on why.")

    now = timezone.now()
    open_items = ProposalItem.objects.filter(
        proposal=proposal, state=ProposalItem.State.PENDING).count()
    proposal.state_before_dismissal = proposal.state
    proposal.state = P.DISMISSED
    proposal.dismissed_reason, proposal.dismissed_note = reason, note
    proposal.dismissed_by, proposal.dismissed_at = actor, now
    proposal.save(update_fields=["state", "state_before_dismissal", "dismissed_reason",
                                 "dismissed_note", "dismissed_by", "dismissed_at",
                                 "updated_at"])
    source = proposal.source_file
    source.dismissed_at = now
    source.save(update_fields=["dismissed_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="meeting.proposal_dismissed",
        target_type="meeting_proposal", target_id=proposal.pk,
        payload={"reason": reason, "note": note, "file": source.name,
                 "items_left_open": open_items,
                 "state_before": proposal.state_before_dismissal})
    return proposal


@transaction.atomic
def restore(proposal, *, actor) -> MeetingProposal:
    """Back to where it was, from the Archived filter."""
    if proposal.state != P.DISMISSED:
        raise approval.ApprovalRefused("That proposal is not dismissed.", status=409)
    was = {"reason": proposal.dismissed_reason, "note": proposal.dismissed_note,
           "dismissed_at": proposal.dismissed_at.isoformat() if proposal.dismissed_at else None}
    proposal.state = proposal.state_before_dismissal or P.PENDING
    proposal.state_before_dismissal = ""
    proposal.dismissed_reason, proposal.dismissed_note = "", ""
    proposal.dismissed_by, proposal.dismissed_at = None, None
    proposal.save(update_fields=["state", "state_before_dismissal", "dismissed_reason",
                                 "dismissed_note", "dismissed_by", "dismissed_at",
                                 "updated_at"])
    source = proposal.source_file
    source.dismissed_at = None
    source.save(update_fields=["dismissed_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="meeting.proposal_restored",
        target_type="meeting_proposal", target_id=proposal.pk,
        payload={"was": was, "state": proposal.state})
    return proposal


@transaction.atomic
def dismiss_as_vendor(proposal, *, actor, role, item_id, choice: dict,
                      note: str = "", request=None):
    """"Record as vendor and dismiss the rest": one participant becomes a
    vendor contact, with service categories; every other item — the tasks
    above all — is left uncreated and the proposal is dismissed as a pitch.

    All or nothing: a vendor without categories is refused and nothing is
    dismissed either.
    """
    if proposal.state not in OPEN:
        raise approval.ApprovalRefused(
            "Only a proposal still waiting for review can be dismissed.", status=409)
    item = ProposalItem.objects.filter(
        proposal=proposal, pk=item_id, kind=ProposalItem.Kind.PARTICIPANT,
        state=ProposalItem.State.PENDING).first()
    if item is None:
        raise approval.ApprovalRefused("Choose who the vendor is.", status=400)

    contact = approval.approve_participant(
        item, actor=actor, role=role, request=request,
        choice={**(choice or {}), "contact_type": "vendor"})
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="meeting.item_approved",
        target_type="proposal_item", target_id=item.pk,
        payload={"kind": item.kind, "created": "contact", "as": "vendor"})
    proposal.refresh_from_db()
    name = f"{contact.first_name} {contact.last_name}".strip()
    # Approving the one participant may already have settled the proposal as
    # actioned (it was the only open question); it is still dismissed, so the
    # reason is on the record either way.
    dismiss(proposal, actor=actor, reason=R.VENDOR_PITCH,
            note=note or f"Recorded {name} as a vendor.",
            _states=OPEN + (P.ACTIONED,))
    return contact
