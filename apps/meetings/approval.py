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
from apps.tenancy import words as practice_words
from apps.tenancy.models import AuditEvent
from apps.work import services as work_services


class ApprovalRefused(Exception):
    def __init__(self, message, status=400, extra=None):
        super().__init__(message)
        self.status = status
        #: Anything the screen needs to act on the refusal, beside the words.
        self.extra = extra or {}


#: A match this strong is the same person unless the reviewer says otherwise
#: (owner, 2026-09-29). Only an email match reaches it.
STRONG_MATCH = 0.95


def strong_match(tenant, *, name: str, email: str):
    """The existing contact a new one would duplicate, or None — looked up
    **now**, not taken from the candidates stored at parse time, so a contact
    created a minute ago by another proposal is found too."""
    from apps.meetings import matching

    if not (email or "").strip():
        return None
    return next((row for row in matching.candidates_for(tenant, name=name, email=email)
                 if row["match_reason"] == matching.EMAIL
                 and row["confidence"] >= STRONG_MATCH), None)


# ------------------------------------------------------------------ participants

def _company_for(tenant, name: str):
    name = (name or "").strip()
    if not name:
        return None
    return Company.objects.filter(name__iexact=name, deleted_at__isnull=True).first()


def resolve_company(item, *, actor, choice: dict, request=None):
    """The company a new contact belongs to (FR-5.10a).

    **A contact created without its company is a contact somebody has to go
    back and fix**, which is what happened to Mike Eller. Three ways, in the
    order the screen offers them:

    1. `company_id` — link to one we already hold.
    2. `create_company` — make it, **through `CompanySerializer`**, so the Add
       company form's rules apply here too: the duplicate-name refusal, the
       domain rows, all of it. There is no second set of rules for companies
       created from a meeting.
    3. Nothing — the notes named no company, or the reviewer chose neither.

    Returns `(company, created)`.
    """
    payload = item.payload or {}
    tenant = item.tenant

    company_id = (choice.get("company_id") or "").strip()
    if company_id:
        company = Company.objects.filter(pk=company_id,
                                         deleted_at__isnull=True).first()
        if company is None:
            raise ApprovalRefused("That company is not in this practice.", status=404)
        return company, False

    asked = choice.get("create_company")
    if not asked:
        return _company_for(tenant, payload.get("parsed_company")), False

    from apps.crm.serializers import CompanySerializer

    name = (asked.get("name") if isinstance(asked, dict) else None) \
        or payload.get("parsed_company") or ""
    domain = (asked.get("domain") if isinstance(asked, dict) else None)
    if domain is None:
        domain = payload.get("parsed_company_domain") or ""
    body = {"name": str(name).strip()}
    if domain:
        body["domains"] = [str(domain).strip().lower()]

    serializer = CompanySerializer(data=body, context={"request": request})
    if not serializer.is_valid():
        # The Add company form's own words, including "already exists — open it
        # instead of creating a second one".
        detail = serializer.errors.get("name") or serializer.errors
        raise ApprovalRefused(
            detail[0] if isinstance(detail, list) else str(detail))
    company = serializer.save(tenant=tenant)
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="company.created",
        target_type="company", target_id=company.pk,
        payload={"name": company.name, "from": "meeting proposal",
                 "domains": body.get("domains", [])})
    return company, True


def _spread_company(item, company):
    """One create covers the meeting (FR-5.10a).

    Several people from the same company arrive in one set of notes. Having
    made the company for the first of them, the rest should find it already
    matched rather than offering to make it again — which is how you end up
    with three Acmes.
    """
    named = (item.payload or {}).get("parsed_company", "").strip().lower()
    if not named:
        return 0
    touched = 0
    siblings = ProposalItem.objects.filter(
        proposal=item.proposal, kind=ProposalItem.Kind.PARTICIPANT,
        state=ProposalItem.State.PENDING).exclude(pk=item.pk)
    for sibling in siblings:
        payload = sibling.payload or {}
        if (payload.get("parsed_company", "").strip().lower() != named):
            continue
        candidates = payload.get("company_candidates") or []
        if any(row.get("company_id") == str(company.pk) for row in candidates):
            continue
        payload["company_candidates"] = [{
            "company_id": str(company.pk), "name": company.name,
            "match_reason": "created_in_this_review",
            "confidence": 0.99, "rank": 0,
        }] + candidates
        sibling.payload = payload
        sibling.save(update_fields=["payload", "updated_at"])
        touched += 1
    return touched


@transaction.atomic
def approve_participant(item, *, actor, role, choice: dict, request=None):
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
        # Owner, 2026-09-29, after a second Mike Eller was created with the
        # first one offered at 0.98: creating someone new over a strong email
        # match needs a confirmation that **names the match** — the contact's
        # id, not a bare "yes", so it cannot be given without seeing who.
        address = (candidate.get("email") or "").strip()
        match = strong_match(tenant, name=f"{first} {last}".strip(), email=address)
        if match is not None:
            if str(choice.get("create_despite_match") or "") != match["contact_id"]:
                raise ApprovalRefused(
                    f"{match['name'] or 'Someone'} ({match['email'] or address}) is already "
                    "a contact, matched on email address. Link to them, or confirm that "
                    "this is a different person.",
                    status=409, extra={"match": match})
            AuditEvent.all_objects.create(
                tenant=tenant, actor=actor, verb="meeting.contact_created_despite_match",
                target_type="proposal_item", target_id=item.pk,
                payload={"matched_contact": match["contact_id"], "email": address,
                         "confidence": match["confidence"]})
        company, made = resolve_company(item, actor=actor, choice=choice,
                                        request=request)
        contact = Contact.objects.create(
            tenant=tenant, first_name=first, last_name=last,
            title=(candidate.get("title") or "").strip(),
            company=company,
            source="meeting notes",
        )
        if made and company is not None:
            _spread_company(item, company)
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
    # "Promised to <company>" (2026-10-20): ticked, the task is also the
    # practice's commitment to the client, filed under them.
    # A deliverable from before the change is a promise by definition.
    promised = bool(choice.get("promised", payload.get("promised_to_client")
                                if item.kind == ProposalItem.Kind.ACTION_ITEM else True))
    promised_to = promise_company(item.proposal) if promised else None
    if promised and company is None:
        company = promised_to

    task = work_services.create_task(
        tenant=item.tenant, actor=actor, role=role,
        title=(choice.get("title") or payload.get("text") or "").strip()[:255],
        description=item.source_excerpt,
        client_company=company,
        client_owner_contact=owner,
        due_date=choice.get("due_date") or payload.get("proposed_due_date") or None,
        contact=owner,
        # Anyone on the practice's team, not only whoever is reviewing
        # (owner, 2026-10-12). Nobody chosen leaves it unassigned, as before.
        assignee=_team_member(item.tenant, choice.get("assignee_id")),
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

    if promised:
        from apps.meetings.models import Commitment

        due = task.due_date
        Commitment.objects.create(
            tenant=item.tenant, side=Commitment.Side.OURS,
            outcome=Commitment.Outcome.PROMISED, task=task,
            company=promised_to or company, owner_name=item.tenant.name, owner_kind="practice",
            text=task.title, due_date=due, follow_up_date=due,
            meeting=item.proposal.meeting, proposal_item=item,
            source_excerpt=item.source_excerpt, created_by=actor)

    _mark(item, actor, "task", task.pk)
    return task


def promise_company(proposal):
    """The client a promise in this meeting is made to: the meeting's client
    company once there is one, else the client company of a participant
    approved or proposed, else None."""
    if proposal.meeting_id and proposal.meeting.client_company_id:
        return proposal.meeting.client_company
    for row in ProposalItem.objects.filter(proposal=proposal,
                                           kind=ProposalItem.Kind.PARTICIPANT):
        body = row.payload or {}
        if body.get("is_practice"):
            continue
        if row.created_record_type == "contact" and row.created_record_id:
            contact = Contact.objects.filter(pk=row.created_record_id).select_related(
                "company").first()
            if contact and contact.company_id and contact.company.is_client_company:
                return contact.company
        for found in body.get("company_candidates") or []:
            company = Company.objects.filter(pk=found.get("company_id"),
                                             is_client_company=True).first()
            if company is not None:
                return company
    return None


# ------------------------------------------------------- someone else's item

@transaction.atomic
def approve_action_item(item, *, actor, role, choice: dict, request=None):
    """An action item, by who owns it (owner, 2026-09-28).

    The practice's own (or nobody named) is one of the practice's tasks, as it
    always was. Someone else's is a commitment, with the outcome the reviewer
    confirmed: a follow-up task for the practice, a record on the person, or —
    only for a client user who holds a portal seat — their task in the portal.
    """
    from apps.meetings import ownership
    from apps.meetings.models import Commitment

    payload = item.payload or {}
    side = choice.get("owner_side", payload.get("owner_side") or "")
    if side != ownership.OTHER:
        return approve_task_item(item, actor=actor, role=role, choice=choice)

    owner_id = choice.get("owner_contact_id", payload.get("proposed_owner_contact_id"))
    contact = (Contact.objects.filter(pk=owner_id, deleted_at__isnull=True)
               .select_related("company").first() if owner_id else None)
    seat = ownership.seat_for(contact)
    kind = choice.get("owner_kind") or payload.get("owner_kind") or "third_party"
    outcome = choice.get("outcome") or payload.get("proposed_outcome") or \
        ownership.default_outcome(side, kind, seat is not None)
    if outcome not in ownership.OUTCOMES:
        raise ApprovalRefused("Choose what should happen: follow up, record only, or "
                              "assign in the portal.")
    text = (choice.get("title") or payload.get("text") or "").strip()
    name = (f"{contact.first_name} {contact.last_name}".strip() if contact
            else (payload.get("proposed_owner_text") or "").strip())
    if not name:
        raise ApprovalRefused("Say who owns it.")
    due = _date(choice.get("due_date") or payload.get("proposed_due_date"))
    company = contact.company if contact and contact.company_id else None
    commitment = Commitment(
        tenant=item.tenant, contact=contact, owner_name=name, owner_kind=kind,
        company=company, text=text, due_date=due, outcome=outcome,
        meeting=item.proposal.meeting, proposal_item=item,
        source_excerpt=item.source_excerpt, created_by=actor)

    if outcome == ownership.PORTAL:
        if seat is None:
            # Bounded to a real seat: without one there is nobody to hold it.
            raise ApprovalRefused(
                f"{name} has no portal seat, so the {practice_words.of(item.tenant).task} "
                "cannot be theirs in the portal. Follow up, or record it.")
        task = _file_for_client(
            item, actor=actor, role=role, choice=choice, seat=seat, contact=contact,
            title=text[:255], due=due)
        if choice.get("notify_me"):
            _attach_practice_stakeholder(task, actor)
        commitment.task = task
        commitment.follow_up_date = due
    elif outcome == ownership.FOLLOW_UP:
        follow_up = _date(choice.get("follow_up_date")) or ownership.default_follow_up(due)
        task = work_services.create_task(
            tenant=item.tenant, actor=actor, role=role,
            title=f"Check that {name} {_lower_first(text)}"[:255],
            description=(f"{name} committed to this in a meeting"
                         + (f", due {due:%Y-%m-%d}" if due else "") + ".\n\n"
                         + item.source_excerpt).strip(),
            client_company=company, contact=contact, due_date=follow_up,
            # The practice's own check, never shown to a client even when it
            # is filed under their company.
            is_client_visible=False)
        commitment.task = task
        commitment.follow_up_date = follow_up
    else:
        commitment.follow_up_date = due
    commitment.save()
    _mark(item, actor, "commitment", commitment.pk)
    return commitment


def _team_member(tenant, user_id):
    """The practice's own person a task is assigned to, or None when nobody
    was chosen. Anyone else is refused: a client is assigned work in the
    portal, by its own choice below."""
    from apps.tenancy.models import TENANT_ROLES, Membership

    if not user_id:
        return None
    member = Membership.all_objects.filter(
        tenant=tenant, user_id=_uuid(user_id), role__in=TENANT_ROLES,
        revoked_at__isnull=True).select_related("user").first()
    if member is None:
        raise ApprovalRefused("Choose someone on the practice's team to assign it to.")
    return member.user


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _file_for_client(item, *, actor, role, choice, seat, contact, title, due):
    """The client's task, where the reviewer filed it (owner, 2026-10-12).

    `choice["file"]` walks the three levels in order: an existing goal or a
    new one, then an existing project or a new one, then an existing task or
    a new one. Nothing chosen at a level leaves that level out, and nothing
    chosen at all is what this did before: a new task filed under nothing.
    **Whoever was chosen is kept on what this creates**: the assignee of a
    new task, and the client-side owner of a new goal or project.
    """
    from apps.crm.models import Task
    from apps.work import permissions as work_perms
    from apps.work.models import Goal, Project

    tenant, company = item.tenant, seat.client_company
    w = practice_words.of(tenant)
    assignee = seat.user
    if choice.get("assignee_id"):
        chosen = _uuid(choice["assignee_id"])
        if not work_perms.is_client_side_user(tenant.pk, chosen, company.pk):
            raise ApprovalRefused(
                f"Choose one of {company.name}'s own portal users to assign it to.")
        from apps.tenancy.models import Membership

        seat = Membership.all_objects.filter(
            tenant=tenant, user_id=chosen, client_company=company,
            revoked_at__isnull=True).select_related("user", "contact").first()
        assignee = seat.user
        contact = seat.contact or contact
    place = choice.get("file") or {}

    def one(model, pk, what):
        row = model.all_objects.filter(
            tenant=tenant, pk=_uuid(pk), client_company=company,
            deleted_at__isnull=True).first()
        if row is None:
            raise ApprovalRefused(f"That {what} is not one of {company.name}'s.")
        return row

    def named(key, what):
        text = (place.get(key) or "").strip()[:255]
        if not text:
            raise ApprovalRefused(f"Give the new {what} a name.")
        return text

    goal = project = None
    if place.get("goal") == "new":
        goal = Goal.objects.create(
            tenant=tenant, owner=actor, client_company=company,
            title=named("goal_title", w.goal), client_owner_contact=contact)
    elif place.get("goal"):
        goal = one(Goal, place["goal"], w.goal)
    if place.get("project") == "new":
        project = Project.objects.create(
            tenant=tenant, owner=actor, client_company=company, goal=goal,
            title=named("project_title", w.project), client_owner_contact=contact)
    elif place.get("project"):
        project = one(Project, place["project"], w.project)
        if goal is not None and project.goal_id != goal.pk:
            raise ApprovalRefused(f"That {w.project} is not under the {w.goal} you chose.")

    if place.get("task") and place["task"] != "new":
        # An existing task: it becomes theirs. Nothing else about it changes.
        task = one(Task, place["task"], w.task)
        if not task.is_client_visible:
            raise ApprovalRefused(f"That {w.task} is not one the client can see.")
        if project is not None and task.project_id != project.pk:
            raise ApprovalRefused(f"That {w.task} is not in the {w.project} you chose.")
        if project is None and goal is not None and task.goal_id != goal.pk and (
                task.project is None or task.project.goal_id != goal.pk):
            raise ApprovalRefused(f"That {w.task} is not under the {w.goal} you chose.")
        work_services.apply_task_changes(task, actor=actor, role=role,
                                         changes={"assignee": assignee})
        return task
    return work_services.create_task(
        tenant=tenant, actor=actor, role=role, title=title,
        description=item.source_excerpt, client_company=company,
        client_owner_contact=contact, contact=contact, assignee=assignee,
        project=project, goal=None if project is not None else goal,
        due_date=due, status=Task.Status.WAITING_ON_CLIENT)


def _date(value):
    from datetime import date

    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _lower_first(text: str) -> str:
    return (text[:1].lower() + text[1:]) if text else text


def _attach_practice_stakeholder(task, actor):
    """The reviewer hears about every update on the client's task — through
    their own contact row, since stakeholders are contacts."""
    from apps.meetings import practice
    from apps.work.models import Cadence, Stakeholder

    me = next((m for m in practice.staff(task.tenant) if m.user_id == str(actor.pk)), None)
    if me is None or me.contact is None:
        raise ApprovalRefused("You have no contact row to be notified through; attach "
                              f"yourself from the {practice_words.of(task.tenant).task} "
                              "instead.")
    Stakeholder.objects.get_or_create(tenant=task.tenant, contact=me.contact, task=task,
                                      defaults={"cadence": Cadence.EVERY_UPDATE})


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


def approve_reading(item, *, actor, request, choice: dict):
    """A stated value, entered on the scorecard (2026-10-27): through the
    scorecard's own entry, as this person, so who may enter it, the period
    and the value are its rules, and an earlier value is kept in the
    reading's history. The value may be corrected before confirming."""
    from apps.meetings import permissions as meeting_perms
    from apps.scorecard import readings
    from apps.scorecard.models import KpiReading

    kpi, reader = meeting_perms.reading_kpi(request, item)
    if kpi is None:
        raise ApprovalRefused("That KPI is gone from the scorecard, or isn't one you can "
                              "see. Reject this one.", status=409)
    if not reader.may_enter(kpi):
        raise ApprovalRefused("You can't enter readings for this KPI. Its reading owner, "
                              "the practice owner or an associate can.", status=403)
    period = item.payload.get("period_start")
    value = str(choice.get("value") or "").strip() or item.payload.get("value")
    with transaction.atomic():
        result = readings.save(reader, kpi.scorecard,
                               [{"kpi": str(kpi.pk), "period_start": period, "value": value}],
                               timezone.localdate())
        if result["errors"]:
            raise ApprovalRefused(next(iter(result["errors"].values())))
        reading = KpiReading.objects.get(kpi=kpi, period_start=period, membership__isnull=True)
        _mark(item, actor, "kpi_reading", reading.pk)
    return reading


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
