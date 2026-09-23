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
        # FR-5.9e — the screen shows this one rather than asking about it.
        "is_practice": bool((item.payload or {}).get("is_practice")),
    }


def represent_backfill(backfill) -> dict | None:
    """The import's state, with the estimate kept beside the real figure.

    An estimate that turned out badly wrong should be visible afterwards, not
    quietly replaced by what it actually cost.
    """
    if backfill is None:
        return None
    return {
        "id": str(backfill.pk),
        "scope": backfill.scope,
        "since": backfill.since.isoformat() if backfill.since else None,
        "state": backfill.state,
        "running": backfill.is_running,
        "planned": backfill.planned,
        "done": backfill.done,
        "skipped": backfill.skipped,
        "failed": backfill.failed,
        "remaining": backfill.remaining,
        "estimated_cost_usd": str(backfill.estimated_cost_usd),
        "cost_usd": str(backfill.cost_usd),
        "last_error": backfill.last_error,
        "started_at": backfill.created_at.isoformat(),
        "finished_at": backfill.finished_at.isoformat() if backfill.finished_at else None,
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


def represent_meeting(meeting, *, for_contact=None) -> dict:
    """One call, as it reads on a contact or company page (FR-5.8d).

    **The summary is the accepted one or nothing.** A discarded summary means a
    Meeting with none (FR-5.8b), and inventing a fallback here would put back
    exactly what somebody chose to throw away.
    """
    attendees = [
        {"contact": str(row.contact_id),
         "name": f"{row.contact.first_name} {row.contact.last_name}".strip(),
         "is_practice": row.is_practice}
        for row in meeting.participants.select_related("contact")
    ]
    return {
        "id": str(meeting.pk),
        "date": meeting.meeting_date.isoformat() if meeting.meeting_date else None,
        "title": meeting.title,
        "summary": meeting.summary,
        "client_company": (str(meeting.client_company_id)
                           if meeting.client_company_id else None),
        # Everyone else who was there — the page you are on is not news to you.
        "others": [row for row in attendees
                   if str(row["contact"]) != str(for_contact or "")],
        "practice": [row["name"] for row in attendees if row["is_practice"]],
        "source_link": meeting.web_view_link,
        "source_name": meeting.source_file.name if meeting.source_file_id else "",
    }
