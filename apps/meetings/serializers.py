"""How a proposal reads on the review screen."""

from __future__ import annotations

from apps.meetings.models import ProposalItem


def represent_item(item) -> dict:
    return {
        "id": str(item.pk),
        "kind": item.kind,
        "state": item.state,
        # FR-5.14 — the passage it came from, so the reviewer can check the
        # claim rather than trust it.
        "source_excerpt": item.source_excerpt,
        "payload": item.payload,
        "position": item.position,
        "created_record_type": item.created_record_type,
        "created_record_id": (str(item.created_record_id)
                              if item.created_record_id else None),
        "actioned_at": item.actioned_at.isoformat() if item.actioned_at else None,
    }


def represent_source_file(source_file) -> dict:
    return {
        "id": str(source_file.pk),
        "name": source_file.name,
        "mime_type": source_file.mime_type,
        "state": source_file.state,
        "skip_reason": source_file.skip_reason,
        "error": source_file.error,
        "owner_email": source_file.drive_file_owner_email,
        "web_view_link": source_file.web_view_link,
        "fetched_at": (source_file.fetched_at.isoformat()
                       if source_file.fetched_at else None),
    }


def represent_proposal(proposal, *, full=False) -> dict:
    payload = {
        "id": str(proposal.pk),
        "state": proposal.state,
        "title": proposal.title,
        "meeting_date": (proposal.meeting_date.isoformat()
                         if proposal.meeting_date else None),
        "proposed_summary": proposal.proposed_summary,
        "summary": proposal.summary,
        "summary_discarded": proposal.summary_discarded,
        "source_file": represent_source_file(proposal.source_file),
        "meeting": str(proposal.meeting_id) if proposal.meeting_id else None,
        "counts": {},
    }
    items = list(ProposalItem.objects.filter(proposal=proposal))
    payload["counts"] = {
        "pending": sum(1 for i in items if i.state == ProposalItem.State.PENDING),
        "approved": sum(1 for i in items if i.state == ProposalItem.State.APPROVED),
        "rejected": sum(1 for i in items if i.state == ProposalItem.State.REJECTED),
    }
    if full:
        payload["items"] = [represent_item(item) for item in items]
        # The document itself, so a reviewer can read past the excerpt.
        payload["source_text"] = proposal.source_file.text
    return payload
