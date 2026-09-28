"""Who is on which recurring email, and how they got there (owner, 2026-09-28).

**Enrolment is explicit.** A contact is on a cadence only because the FF or a
CF put them there — never as a side effect of a type, an import or an approval.
The referral-touch scheduler reads `Enrollment`; a partner without an open row
gets nothing drafted, whatever their `referral_next_touch_at` says.

Digest stakeholders are the one exception by design: attaching someone to a
task, project or goal is the deliberate act, so it counts as enrolment and is
shown alongside the rest, with the same way off.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Contact, Enrollment, OutboxMessage
from apps.tenancy.models import AuditEvent

PROGRAMS = Enrollment.Program


class EnrollmentRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def open_row(contact, program):
    return Enrollment.all_objects.filter(tenant_id=contact.tenant_id, contact=contact,
                                         program=program, ended_at__isnull=True).first()


def is_enrolled(contact, program) -> bool:
    return open_row(contact, program) is not None


def _is_partner(contact) -> bool:
    return contact.type_links.filter(contact_type__code="referral_partner").exists()


@transaction.atomic
def enroll(contact, program, *, actor, source="manual") -> tuple[Enrollment, bool]:
    """Put a contact on a program. Returns `(row, created)`; enrolling someone
    already enrolled changes nothing.

    For referral touches the partner gets a cadence if they had none, and a
    first touch no earlier than the drafting lead from now: a date already in
    the future is kept (the one they were on before), a missing or past one is
    replaced, so enrolling today never drafts a touch that was "due" a month ago.
    """
    from apps.crm.services import referral

    if program not in PROGRAMS.values:
        raise EnrollmentRefused("Unknown program.")
    if program == PROGRAMS.REFERRAL_TOUCHES and not _is_partner(contact):
        raise EnrollmentRefused(
            f"{contact.first_name} {contact.last_name} is not a referral partner.".strip())
    existing = open_row(contact, program)
    if existing is not None:
        return existing, False

    row = Enrollment.all_objects.create(tenant_id=contact.tenant_id, contact=contact,
                                        program=program, enrolled_by=actor)
    if program == PROGRAMS.REFERRAL_TOUCHES:
        soonest = timezone.now() + timezone.timedelta(days=referral.DRAFT_LEAD_DAYS)
        updates = []
        if not contact.referral_cadence:
            contact.referral_cadence = referral.DEFAULT_CADENCE
            updates.append("referral_cadence")
        if contact.referral_next_touch_at is None or contact.referral_next_touch_at < soonest:
            contact.referral_next_touch_at = soonest
            updates.append("referral_next_touch_at")
        if updates:
            contact.save(update_fields=[*updates, "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=contact.tenant_id, actor=actor, verb="enrollment.started",
        target_type="contact", target_id=contact.pk,
        payload={"program": program, "source": source,
                 "next_touch_at": contact.referral_next_touch_at.isoformat()
                 if program == PROGRAMS.REFERRAL_TOUCHES and contact.referral_next_touch_at
                 else None})
    return row, True


#: What a program's unsent drafts are, so ending it can withdraw them.
PENDING_PRODUCERS = {
    PROGRAMS.REFERRAL_TOUCHES: [OutboxMessage.Producer.REFERRAL_TOUCH],
}


@transaction.atomic
def unenroll(contact, program, *, actor, reason=Enrollment.EndReason.UNENROLLED) -> bool:
    """Take a contact off a program. Their drafts for it that nobody has
    approved yet are withdrawn (rejected, with the reason), because an
    unenrolled partner's touch still sitting in the queue is one approval away
    from going out. Sent mail is history and is not touched."""
    row = open_row(contact, program)
    if row is None:
        return False
    row.ended_at, row.ended_by, row.ended_reason = timezone.now(), actor, reason
    row.save(update_fields=["ended_at", "ended_by", "ended_reason", "updated_at"])
    withdrawn = list(OutboxMessage.all_objects.filter(
        tenant_id=contact.tenant_id, to_contact=contact,
        producer__in=PENDING_PRODUCERS.get(program, []),
        state=OutboxMessage.State.PENDING_APPROVAL).values_list("pk", flat=True))
    if withdrawn:
        OutboxMessage.all_objects.filter(pk__in=withdrawn).update(
            state=OutboxMessage.State.REJECTED,
            warning=f"Withdrawn: {contact.first_name} was {reason} from "
                    f"{PROGRAMS(program).label.lower()}.",
            updated_at=timezone.now())
    AuditEvent.all_objects.create(
        tenant_id=contact.tenant_id, actor=actor, verb="enrollment.ended",
        target_type="contact", target_id=contact.pk,
        payload={"program": program, "reason": reason,
                 "withdrawn_drafts": [str(pk) for pk in withdrawn]})
    return True


def _stakeholder_label(row) -> str:
    target = row.task or row.project or row.goal
    kind = "task" if row.task_id else "project" if row.project_id else "goal"
    return f"Progress digest — {kind} “{getattr(target, 'title', '')}”"


def enrollments_for(contact) -> list[dict]:
    """Everything this person is on, in one list: open programs and digest
    attachments that are not muted. Each says how to come off it."""
    from apps.work.models import Stakeholder

    rows = []
    for row in Enrollment.all_objects.filter(
            tenant_id=contact.tenant_id, contact=contact,
            ended_at__isnull=True).select_related("enrolled_by"):
        rows.append({
            "kind": row.program, "id": str(row.pk),
            "label": PROGRAMS(row.program).label,
            "detail": (f"{contact.get_referral_cadence_display() or 'monthly'} · next "
                       f"{timezone.localdate(contact.referral_next_touch_at):%Y-%m-%d}"
                       if row.program == PROGRAMS.REFERRAL_TOUCHES
                       and contact.referral_next_touch_at else ""),
            "since": row.created_at.isoformat(),
            "by": (row.enrolled_by.full_name or row.enrolled_by.email)
            if row.enrolled_by_id else "",
        })
    for row in Stakeholder.all_objects.filter(
            tenant_id=contact.tenant_id, contact=contact, is_muted=False
            ).select_related("task", "project", "goal"):
        rows.append({
            "kind": "digest", "id": str(row.pk), "label": _stakeholder_label(row),
            "detail": row.get_cadence_display(), "since": row.created_at.isoformat(),
            "by": "",
        })
    return rows


def unenroll_digest(stakeholder, *, actor) -> None:
    """Off a digest from the contact page: muted, as the recipient's own
    "stop" link does, so the attachment and its history stay."""
    stakeholder.is_muted = True
    stakeholder.save(update_fields=["is_muted", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=stakeholder.tenant_id, actor=actor, verb="enrollment.ended",
        target_type="stakeholder", target_id=stakeholder.pk,
        payload={"program": "digest", "contact": str(stakeholder.contact_id)})


def contacts_enrolled(program):
    """The open enrolments of one program, as a contact queryset filter."""
    return Contact.objects.filter(enrollments__program=program,
                                  enrollments__ended_at__isnull=True)
