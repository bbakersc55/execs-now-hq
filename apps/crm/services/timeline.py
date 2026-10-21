"""Activity timeline (FR-1.5).

Aggregates stage changes, notes, emails, and tasks into one reverse-
chronological view. Meetings join in Module 5.
"""

from __future__ import annotations

from apps.crm.models import EmailMessage, OutboxMessage, StageChange, Task
from apps.notes.models import Note
from apps.tenancy import words as practice_words


def _entry(kind, when, text, **extra):
    return {"kind": kind, "when": when.isoformat() if when else None, "text": text, **extra}


def _note_entry(note):
    """A locked note is a stub here too (FR-2.11): its display title and a lock,
    never a body excerpt — even for someone who has it unlocked, since a
    timeline is a list read over someone's shoulder."""
    from apps.notes.access import display_title

    if note.is_locked:
        text = f"Note (locked): {display_title(note)}"
    else:
        label = note.title or (note.body[:60] + ("…" if len(note.body) > 60 else ""))
        suffix = " (imported)" if note.source == Note.Source.IMPORT else ""
        text = f"Note: {label}{suffix}"
    return _entry("note", note.created_at, text, note_id=str(note.pk), locked=note.is_locked)


def for_contact(contact, limit=100, *, money=False):
    """`money`: whether the reader may see an invoice (matrix 13.4a). Off, an
    invoice email and the replies to it are left out of the history."""
    entries = []

    for change in StageChange.objects.filter(contact=contact).select_related(
        "from_stage", "to_stage", "pipeline"
    ):
        origin = change.from_stage.label if change.from_stage else "entered"
        text = (
            f"{change.pipeline.name}: {origin} → {change.to_stage.label}"
            if change.from_stage
            else f"{change.pipeline.name}: entered at {change.to_stage.label}"
        )
        if change.reason:
            text += f" — {change.reason}"
        entries.append(_entry("stage", change.created_at, text))

    for note in Note.objects.filter(contact=contact, deleted_at__isnull=True):
        entries.append(_note_entry(note))

    w = practice_words.of(contact.tenant)
    for task in Task.objects.filter(contact=contact, deleted_at__isnull=True):
        due = f", due {task.due_date}" if task.due_date else ""
        entries.append(_entry("task", task.created_at, f"{w.Task}: {task.title}{due}"))

    sent = OutboxMessage.objects.filter(to_contact=contact)
    replies = EmailMessage.objects.filter(contact=contact, direction="inbound")
    if not money:
        from apps.crm.permissions import MONEY_PRODUCERS

        sent = sent.exclude(producer__in=MONEY_PRODUCERS)
        replies = replies.exclude(thread__is_financial=True)
    for message in sent:
        verb = {
            "sent": "Sent", "pending_approval": "Drafted (awaiting approval)",
            "expired": "Draft expired unsent", "rejected": "Draft rejected",
        }.get(message.state, message.state)
        entries.append(_entry("email", message.sent_at or message.created_at,
                              f"{verb}: {message.subject}"))

    for message in replies:
        entries.append(_entry("email", message.received_at, f"Reply received: {message.subject}"))

    # Enrolments, and a campaign's follow-through it could not do (owner,
    # 2026-10-19). A stage move from a campaign is a stage change above, its
    # reason naming the campaign.
    from apps.tenancy.models import AuditEvent

    for event in AuditEvent.all_objects.filter(
            tenant_id=contact.tenant_id, target_type="contact", target_id=contact.pk,
            verb__in=("enrollment.started", "campaign.enrolment_skipped")):
        payload = event.payload or {}
        if event.verb == "enrollment.started":
            source = str(payload.get("source") or "")
            how = f", when {source} was sent" if source.startswith("campaign") else ""
            text = (f"Enrolled in referral touches "
                    f"({contact.get_referral_cadence_display().lower() or 'monthly'}){how}")
        else:
            text = (f"Not enrolled in referral touches when campaign "
                    f"\u201c{payload.get('campaign_name', '')}\u201d was sent: "
                    f"{payload.get('why', '')}")
        entries.append(_entry("enrollment", event.created_at, text))

    entries.sort(key=lambda e: e["when"] or "", reverse=True)
    return entries[:limit]


def for_company(company, limit=100):
    from apps.crm.models import Contact

    entries = []
    for note in Note.objects.filter(company=company, deleted_at__isnull=True):
        entries.append(_note_entry(note))

    for contact in Contact.objects.filter(company=company, deleted_at__isnull=True):
        for change in StageChange.objects.filter(contact=contact).select_related(
            "to_stage", "pipeline"
        ):
            entries.append(_entry(
                "stage", change.created_at,
                f"{contact.first_name} {contact.last_name} moved to "
                f"{change.to_stage.label} ({change.pipeline.name})",
            ))

    entries.sort(key=lambda e: e["when"] or "", reverse=True)
    return entries[:limit]
