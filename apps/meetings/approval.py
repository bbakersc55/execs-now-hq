"""What approval creates (FR-5.15, FR-5.18, FR-5.19).

**Approving creates records through the same paths as manual creation**, so
every Module 1 and Module 3 rule applies identically and none of them is
reimplemented here: `referral.add_type` for a contact type, `work.services
.create_task` for a task, `stakeholders` for who hears about it. That is the
whole point of FR-5.18 — the queue is a different way in, not a different set
of rules.

**Approving never sends.** Confirming a referral partner *queues* an onboarding
draft in the Outbox at `pending_approval` (FR-1.23a); approving a deliverable
with stakeholders creates the task and the stakeholder rows and leaves the
notification to the flow that already gates sends (FR-5.19). A test asserts the
dev outbox is empty afterwards, because that is the promise this module's whole
design rests on.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Company, Contact, ContactEmail, ContactType, ServiceCategory
from apps.crm.models import ContactServiceCategory
from apps.crm.services import referral
from apps.meetings import practice
from apps.meetings.models import (
    Meeting, MeetingParticipant, MeetingProposal, ProposalItem,
)
from apps.work import services as work_services


class ApprovalRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ participants

def _company_for(tenant, name: str):
    name = (name or "").strip()
    if not name:
        return None
    return Company.objects.filter(name__iexact=name).first()


@transaction.atomic
def approve_participant(item, *, actor, role, choice: dict):
    """Create or link the contact the reviewer picked (FR-5.9, R10).

    `choice` is what the person decided: `contact_id` to link an existing one,
    or nothing to take the new-contact path, plus the **confirmed** type and,
    for a vendor, the service categories captured inline.
    """
    payload = item.payload or {}
    tenant = item.tenant
    confirmed_type = (choice.get("contact_type")
                      or payload.get("proposed_contact_type") or "").strip()
    if not confirmed_type:
        raise ApprovalRefused("Confirm what this person is to the practice.")

    contact_id = (choice.get("contact_id") or "").strip()
    if contact_id:
        contact = Contact.objects.filter(pk=contact_id, deleted_at__isnull=True).first()
        if contact is None:
            raise ApprovalRefused("That contact is not in this practice.", status=404)
    else:
        candidate = {**(payload.get("new_contact_candidate") or {}),
                     **(choice.get("new_contact") or {})}
        first = (candidate.get("first_name") or "").strip()
        last = (candidate.get("last_name") or "").strip()
        if not first and not last:
            raise ApprovalRefused("A new contact needs a name.")
        contact = Contact.objects.create(
            tenant=tenant, first_name=first, last_name=last,
            title=(candidate.get("title") or "").strip(),
            company=_company_for(tenant, candidate.get("company")),
            source="meeting notes",
        )
        address = (candidate.get("email") or "").strip()
        if address:
            ContactEmail.objects.create(tenant=tenant, contact=contact,
                                        address=address, is_primary=True)

    # FR-5.9d — a confirmed type is **added**; it never replaces what the
    # contact already is, and it never touches their pipeline stage.
    # `referral.add_type` is the same call the contact screen makes, which is
    # how confirming `referral_partner` queues onboarding (FR-5.9b) without
    # this module knowing anything about flyers or cadences.
    if ContactType.objects.filter(code=confirmed_type).exists():
        referral.add_type(contact, confirmed_type, actor=actor)

    if confirmed_type == "vendor":
        categories = choice.get("service_categories") or payload.get("service_categories")
        if not categories:
            # FR-5.9c — inline, before approval completes, so a vendor is
            # searchable the moment they exist rather than being fixed later.
            raise ApprovalRefused(
                "A vendor needs at least one service category, so they can be "
                "found by what they do.")
        for name in categories:
            name = str(name).strip()
            if not name:
                continue
            category, _ = ServiceCategory.objects.get_or_create(
                tenant=tenant, name=name)
            ContactServiceCategory.objects.get_or_create(
                tenant=tenant, contact=contact, service_category=category)

    _mark(item, actor, "contact", contact.pk)
    return contact


# ------------------------------------------------- action items and deliverables

@transaction.atomic
def approve_task_item(item, *, actor, role, choice: dict):
    """One task, through `work.services.create_task` (FR-5.18).

    The proposed owner becomes the task's **`client_owner_contact_id`**; where
    that contact also holds a portal login the caller may assign it to them, and
    where they do not, the client owner is recorded as such — **no user is
    invented to hold the field** (FR-5.12).
    """
    payload = item.payload or {}
    owner_id = choice.get("client_owner_contact_id", payload.get("proposed_owner_contact_id"))
    owner = Contact.objects.filter(pk=owner_id).first() if owner_id else None
    company = None
    if choice.get("client_company"):
        company = Company.objects.filter(pk=choice["client_company"]).first()
    elif owner is not None and owner.company_id:
        company = owner.company

    task = work_services.create_task(
        tenant=item.tenant, actor=actor, role=role,
        title=(choice.get("title") or payload.get("text") or "").strip()[:255],
        description=item.source_excerpt,
        client_company=company,
        client_owner_contact=owner,
        due_date=choice.get("due_date") or payload.get("proposed_due_date") or None,
        contact=owner,
    )

    # FR-5.13 / FR-5.19 — stakeholders are created; the notification they will
    # eventually receive is somebody else's gate, and this module does not
    # open it.
    for row in (choice.get("stakeholders") or payload.get("proposed_stakeholders") or []):
        contact = Contact.objects.filter(pk=row.get("contact_id")).first()
        if contact is None:
            continue
        from apps.work.models import Cadence, Stakeholder

        Stakeholder.objects.get_or_create(
            tenant=item.tenant, contact=contact, task=task,
            defaults={"cadence": row.get("cadence") or Cadence.WEEKLY})

    _mark(item, actor, "task", task.pk)
    return task


# ------------------------------------------------------------------- the meeting

@transaction.atomic
def create_meeting(proposal, *, actor) -> Meeting:
    """The meeting itself, on every approved participant's timeline (FR-5.8a).

    Created once: approving a second participant later joins them to the
    meeting that already exists rather than making another.
    """
    attended = []
    for item in ProposalItem.objects.filter(
            proposal=proposal, kind=ProposalItem.Kind.PARTICIPANT,
            state=ProposalItem.State.APPROVED, created_record_type="contact"):
        contact = Contact.objects.filter(pk=item.created_record_id).first()
        if contact is not None:
            attended.append((contact, item.payload or {}))
    # The client's side only: the practice is in the room, not a party to the
    # engagement, so it never decides which company the meeting belongs to.
    contacts = [c for c, body in attended if not body.get("is_practice")]

    meeting = proposal.meeting
    if meeting is None:
        # FR-5.8b — a discarded summary means a Meeting with none, not no
        # Meeting.
        summary = "" if proposal.summary_discarded else (
            proposal.summary or proposal.proposed_summary)
        company = next((c.company for c in contacts
                        if c.company_id and c.company.is_client_company), None)
        meeting = Meeting.objects.create(
            tenant=proposal.tenant, source_file=proposal.source_file,
            proposal=proposal, meeting_date=proposal.meeting_date,
            title=proposal.title, summary=summary,
            client_company=company,
            web_view_link=proposal.source_file.web_view_link,
        )
        proposal.meeting = meeting
        proposal.save(update_fields=["meeting", "updated_at"])

    for contact, body in attended:
        row, created = MeetingParticipant.objects.get_or_create(
            tenant=proposal.tenant, meeting=meeting, contact=contact,
            defaults={"is_practice": bool(body.get("is_practice")),
                      "staff_user_id": body.get("practice_user_id")})
        if not created and body.get("is_practice") and not row.is_practice:
            row.is_practice = True
            row.staff_user_id = body.get("practice_user_id")
            row.save(update_fields=["is_practice", "staff_user", "updated_at"])
    return meeting


# ------------------------------------------------------------------- the plumbing

def _mark(item, actor, record_type, record_id):
    item.state = ProposalItem.State.APPROVED
    item.created_record_type = record_type
    item.created_record_id = record_id
    item.actioned_by = actor
    item.actioned_at = timezone.now()
    item.save(update_fields=["state", "created_record_type", "created_record_id",
                             "actioned_by", "actioned_at", "updated_at"])
    settle(item.proposal)


def reject(item, *, actor):
    """**Rejection is persistent** (FR-5.16): the row stays, visible as
    rejected, and the next poll does not bring it back."""
    item.state = ProposalItem.State.REJECTED
    item.actioned_by = actor
    item.actioned_at = timezone.now()
    item.save(update_fields=["state", "actioned_by", "actioned_at", "updated_at"])
    settle(item.proposal)
    return item


def settle(proposal):
    """Where the proposal has got to, from its items. Derived, never stored
    ahead of them.

    **A participant who is the practice is not an open question** (FR-5.9e),
    so a pending one does not hold the proposal at `partially_actioned`. Items
    parsed after that rule existed are approved on arrival and never reach
    this; the live check is for the ones parsed before it — there were eight
    in the owner's queue, each stuck on his own name.
    """
    items = list(ProposalItem.objects.filter(proposal=proposal))
    roster = None
    theirs = []
    for item in items:
        if item.kind == ProposalItem.Kind.PARTICIPANT:
            if roster is None:
                roster = practice.staff(proposal.tenant)
            if practice.is_practice_item(item, tenant=proposal.tenant, roster=roster):
                # Whatever its state. It is not a question that was answered,
                # so it is not evidence the proposal has been worked on either.
                continue
        theirs.append(item)

    states = {item.state for item in theirs}
    if not theirs:
        # Everything in it was us. Nothing for anybody to decide.
        state = (MeetingProposal.State.ACTIONED if items
                 else MeetingProposal.State.PENDING)
    elif not states or states == {ProposalItem.State.PENDING}:
        state = MeetingProposal.State.PENDING
    elif ProposalItem.State.PENDING in states:
        state = MeetingProposal.State.PARTIALLY_ACTIONED
    elif states == {ProposalItem.State.REJECTED}:
        state = MeetingProposal.State.REJECTED
    else:
        state = MeetingProposal.State.ACTIONED
    if proposal.state != state and proposal.state != MeetingProposal.State.SUPERSEDED:
        proposal.state = state
        proposal.save(update_fields=["state", "updated_at"])
    return proposal
