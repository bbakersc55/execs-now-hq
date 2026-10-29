"""Stage rules, part 2 (owner, 2026-10-24): what happens when someone enters a
stage, sits in one too long, or is won or lost, on one pipeline.

**Triggers.** A rule fires when a contact
- *enters* its stage (from any stage, or from one named stage);
- *has sat* in its stage N days with no activity, checked by a daily job and
  firing once per stay (a stay starts when they enter the stage; leaving and
  coming back is a new stay);
- is *won* or *lost* on the rule's pipeline (any stage with that meaning).

**Activity** is an email either way, a note, a meeting, a finished task or a
stage move. Each sets `ContactPipelinePosition.last_activity_at` on every
pipeline the contact is in; a stage move also sets `stage_entered_at`.

**Actions.** A task (title with merge fields, due in N days, for the
contact's owner, the practice owner or a named team member); a draft email
from the template library into the Outbox, for approval as ever; a move to
another stage; enrolling in referral touches at a cadence; a notice to a
person, listed on Home and sent in one daily email when there are any.

**Loop guard.** A move made by a rule runs the new stage's rules, but not
their move actions, so two rules can never bounce a contact back and forth.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.crm.models import (
    ContactPipelinePosition, PipelineNotice, PipelineStage, StageAutomation, StageChange,
    StageRuleFiring, StageSemantic,
)
from apps.tenancy.models import AuditEvent

R = StageAutomation
#: Merge fields a rule's task title or notice may use beyond the template
#: library's general ones.
RULE_FIELDS = (("Stage", "The stage they are in"), ("Pipeline", "The pipeline"),
               ("DaysInStage", "Days in the stage"), ("Owner", "Their owner's name"))
GENERAL = ("FirstName", "LastName", "Company", "FractionalName", "PracticeName")
ALLOWED = GENERAL + tuple(name for name, _ in RULE_FIELDS)
_FIELD = re.compile(r"\{([A-Za-z][A-Za-z ]*)\}")


class RuleRefused(ValueError):
    pass


def check_fields(text: str) -> None:
    unknown = sorted({f for f in _FIELD.findall(text or "") if f not in ALLOWED})
    if unknown:
        raise RuleRefused("There is no merge field called " + ", ".join(
            f"{{{f}}}" for f in unknown) + ". The ones you can use: "
            + ", ".join(f"{{{f}}}" for f in ALLOWED) + ".")


# ------------------------------------------------------------- the stay

def stay_started(position):
    """When the contact entered the stage they are in. Older positions carry
    no `stage_entered_at`: their last move into this stage stands in, else
    when they joined the pipeline."""
    if position.stage_entered_at:
        return position.stage_entered_at
    last = StageChange.all_objects.filter(
        tenant_id=position.tenant_id, contact_id=position.contact_id,
        pipeline_id=position.pipeline_id, to_stage_id=position.stage_id,
    ).order_by("-created_at").values_list("created_at", flat=True).first()
    return last or position.entered_at


def quiet_since(position):
    """The last sign of life in this stay: activity, or the move into it."""
    start = stay_started(position)
    activity = position.last_activity_at
    return max(start, activity) if activity else start


def touch(contact_id, tenant_id, at=None) -> int:
    """Activity on a contact: every pipeline position they hold is fresh."""
    at = at or timezone.now()
    return ContactPipelinePosition.all_objects.filter(
        tenant_id=tenant_id, contact_id=contact_id).filter(
        Q(last_activity_at__isnull=True) | Q(last_activity_at__lt=at)).update(
        last_activity_at=at)


# ------------------------------------------------------------- what fires

def rules_on_move(pipeline, from_stage, to_stage):
    entering = Q(trigger=R.Trigger.ENTERS, to_stage=to_stage) & (
        Q(from_stage__isnull=True) | Q(from_stage=from_stage) if from_stage is not None
        else Q(from_stage__isnull=True))
    meaning = Q(pk__in=[])
    if to_stage.semantic == StageSemantic.WON:
        meaning = Q(trigger=R.Trigger.WON)
    elif to_stage.semantic == StageSemantic.LOST:
        meaning = Q(trigger=R.Trigger.LOST)
    return (R.all_objects.filter(tenant_id=to_stage.tenant_id, pipeline=pipeline,
                                 is_active=True).filter(entering | meaning)
            .select_related("pipeline", "to_stage", "move_to_stage", "email_template",
                            "task_assignee")
            .order_by("position", "created_at"))


def run_on_move(contact, from_stage, to_stage, *, actor=None, allow_moves=True):
    """The rules a move fires. `allow_moves` is False when a rule made the
    move: the loop guard."""
    results = []
    for rule in rules_on_move(to_stage.pipeline, from_stage, to_stage):
        results.append(run(rule, contact, actor=actor, allow_moves=allow_moves))
    return results


def run(rule, contact, *, actor=None, allow_moves=True):
    """One rule's action. A move can come from a request or a job; the
    contact's practice is bound either way, as the shared services need."""
    from apps.tenancy.context import tenant_context

    with tenant_context(contact.tenant_id):
        return _run(rule, contact, actor=actor, allow_moves=allow_moves)


def _run(rule, contact, *, actor=None, allow_moves=True):
    from apps.crm.services.outbox import queue_stage_email

    kind = rule.action_type
    if kind == R.Action.CREATE_TASK:
        return create_task(contact, rule, actor=actor)
    if kind == R.Action.DRAFT_EMAIL:
        return queue_stage_email(contact, rule, actor=actor)
    if kind == R.Action.MOVE_STAGE:
        if not allow_moves:
            AuditEvent.all_objects.create(
                tenant_id=contact.tenant_id, actor=actor, verb="stage_rule.move_held",
                target_type="contact", target_id=contact.pk,
                payload={"rule": str(rule.pk), "why": "a rule's own move"})
            return None
        return move(contact, rule, actor=actor)
    if kind == R.Action.ENROLL_TOUCHES:
        return enroll(contact, rule, actor=actor)
    if kind == R.Action.NOTIFY:
        return notify(contact, rule)
    if kind == R.Action.START_FOLLOW_UP:
        return start_follow_up(contact, rule, actor=actor)
    if kind == R.Action.SEND_SIGNATURE:
        from apps.esign import services as esign

        return esign.from_rule(contact, rule, actor=actor)
    # CALENDAR_EVENT never runs by itself: it needs a time, so it is offered
    # to the person who made the move (`calendar_offers`) and made when they
    # pick one. A move with nobody to ask (an import, a rule) offers nothing.
    return None


def calendar_offers(contact, from_stage, to_stage) -> list[dict]:
    """The calendar events a move into `to_stage` offers: each rule's title
    for this contact, a suggested day and a length. The screen asks."""
    from datetime import timedelta

    today = timezone.localdate()
    offers = []
    for rule in rules_on_move(to_stage.pipeline, from_stage, to_stage).filter(
            action_type=R.Action.CALENDAR_EVENT):
        days = rule.task_due_offset_days if rule.task_due_offset_days is not None else 1
        offers.append({
            "rule": str(rule.pk), "contact": str(contact.pk),
            "title": merged(rule.task_title_template, contact, rule) or "Follow up",
            "date": (today + timedelta(days=max(0, days))).isoformat(),
            "minutes": rule.event_minutes or 30,
        })
    return offers


def start_follow_up(contact, rule, *, actor=None):
    """Part 3: the stage's follow-up, started without asking. The stage is
    the rule's own; for won and lost, wherever the contact now is."""
    from apps.crm.services import follow_ups, pipeline

    stage = rule.to_stage
    if stage is None:
        position = pipeline.position_for(contact, rule.pipeline)
        stage = position.stage if position else None
    try:
        run, _ = follow_ups.start(contact, stage, actor=actor, via="rule")
    except follow_ups.FollowUpRefused as exc:
        AuditEvent.all_objects.create(
            tenant_id=contact.tenant_id, actor=actor, verb="stage_rule.follow_up_skipped",
            target_type="contact", target_id=contact.pk,
            payload={"rule": str(rule.pk), "why": str(exc)})
        return None
    return run


# ------------------------------------------------------------- actions

def merged(text, contact, rule=None, position=None):
    from apps.crm.services import templates

    values = templates.values_for(contact, tenant=contact.tenant,
                                  sender=getattr(contact, "owner", None))
    if position is None and rule is not None:
        position = ContactPipelinePosition.all_objects.filter(
            tenant_id=contact.tenant_id, contact=contact,
            pipeline_id=rule.pipeline_id).select_related("stage", "pipeline").first()
    days = ""
    if position is not None:
        days = str(max(0, (timezone.now() - stay_started(position)).days))
    owner = getattr(contact, "owner", None)
    values.update({
        "Stage": position.stage.label if position is not None else "",
        "Pipeline": position.pipeline.name if position is not None else
        (rule.pipeline.name if rule is not None else ""),
        "DaysInStage": days,
        "Owner": (getattr(owner, "full_name", "") or getattr(owner, "email", "")) if owner else "",
    })
    # The library's renderer knows its own fields only: the rule's are filled first.
    text = text or ""
    for name, _ in RULE_FIELDS:
        text = text.replace(f"{{{name}}}", values.pop(name))
    out = templates.render(text, values, fallback="", drop_empty_lines=False)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def person_for(rule, contact):
    """Who a task or notice is for: the contact's owner, the practice owner,
    or a named team member; the practice owner when the first has none or
    the named one has left."""
    from apps.tenancy.models import Membership, Role

    if rule.task_for == R.For.MEMBER and rule.task_assignee_id:
        if Membership.all_objects.filter(tenant_id=contact.tenant_id, user_id=rule.task_assignee_id,
                                         revoked_at__isnull=True).exists():
            return rule.task_assignee
    if rule.task_for == R.For.CONTACT_OWNER and contact.owner_id:
        return contact.owner
    owner = Membership.all_objects.filter(tenant_id=contact.tenant_id, role=Role.FF,
                                          revoked_at__isnull=True) \
        .select_related("user").order_by("created_at").first()
    return owner.user if owner else None


def create_task(contact, rule, *, actor=None):
    """A task, as every task is made (`work.services.create_task`): filed
    under the contact's company when it is a client company, internal unless
    the rule says the client sees it."""
    from apps.crm.models import Company
    from apps.tenancy.context import tenant_context
    from apps.work import services as work_services
    from apps.work.models import TaskUpdate

    due = None
    if rule.task_due_offset_days is not None:
        due = (timezone.now() + timedelta(days=rule.task_due_offset_days)).date()
    client_company = None
    if contact.company_id:
        client_company = Company.all_objects.filter(
            pk=contact.company_id, tenant=contact.tenant, is_client_company=True,
            deleted_at__isnull=True).first()
    title = merged(rule.task_title_template, contact, rule) or "Follow up"
    with tenant_context(contact.tenant_id):
        task = work_services.create_task(
            tenant=contact.tenant, actor=actor, role=None,
            source=TaskUpdate.Source.STAGE_AUTOMATION, source_id=rule.pk,
            title=title[:255], due_date=due, owner=person_for(rule, contact),
            contact=contact, client_company=client_company,
            is_client_visible=rule.task_client_visible and client_company is not None,
            source_automation=rule,
        )
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="task.created_by_rule",
        target_type="task", target_id=task.pk,
        payload={"contact_id": str(contact.pk), "rule_id": str(rule.pk)})
    return task


def move(contact, rule, *, actor=None):
    from apps.crm.services import pipeline

    target = rule.move_to_stage
    if target is None or target.pipeline_id != rule.pipeline_id:
        return None
    return pipeline.change_stage(contact, target, actor=actor, from_rule=True,
                                 reason=f"Stage rule: {summary(rule)}")


def enroll(contact, rule, *, actor=None):
    """Referral touches at the rule's cadence, as a campaign's follow-through
    does: only for a referral partner, and never someone already on them."""
    from apps.crm.models import Enrollment
    from apps.crm.services import enrollment

    program = Enrollment.Program.REFERRAL_TOUCHES
    why = ""
    if enrollment.is_enrolled(contact, program):
        why = "already on referral touches"
    elif not enrollment._is_partner(contact):
        why = "not a referral partner"
    if why:
        AuditEvent.all_objects.create(
            tenant_id=contact.tenant_id, actor=actor, verb="stage_rule.enrolment_skipped",
            target_type="contact", target_id=contact.pk,
            payload={"rule": str(rule.pk), "why": why})
        return None
    if rule.touch_cadence:
        contact.referral_cadence = rule.touch_cadence
        contact.save(update_fields=["referral_cadence", "updated_at"])
    row, _ = enrollment.enroll(contact, program, actor=actor,
                               source=f"stage rule on {rule.pipeline.name}")
    return row


def notify(contact, rule):
    who = person_for(rule, contact)
    if who is None:
        return None
    text = merged(rule.notice_text, contact, rule) or \
        f"{contact.first_name} {contact.last_name}".strip()
    row = PipelineNotice.all_objects.create(
        tenant_id=contact.tenant_id, recipient=who, contact=contact,
        pipeline_id=rule.pipeline_id, rule=rule, text=text[:500])
    # On the person's Notices list too, and so to their browser if they asked.
    from apps.notify import producers

    producers.pipeline_notice(row)
    return row


# ------------------------------------------------------------- the daily job

@transaction.atomic
def check_idle(tenant, now=None) -> int:
    """Every idle rule, against every contact sitting in its stage: fire
    once per stay when the stay has been quiet for the rule's days."""
    now = now or timezone.now()
    fired = 0
    for rule in R.all_objects.filter(tenant=tenant, is_active=True, trigger=R.Trigger.IDLE,
                                     idle_days__isnull=False, to_stage__isnull=False) \
            .select_related("pipeline", "to_stage", "move_to_stage", "task_assignee"):
        positions = ContactPipelinePosition.all_objects.filter(
            tenant=tenant, pipeline_id=rule.pipeline_id, stage_id=rule.to_stage_id,
            contact__deleted_at__isnull=True).select_related(
            "contact", "contact__company", "contact__owner", "stage", "pipeline")
        for position in positions:
            start = stay_started(position)
            if now - quiet_since(position) < timedelta(days=rule.idle_days):
                continue
            _, created = StageRuleFiring.all_objects.get_or_create(
                tenant=tenant, rule=rule, contact=position.contact, stay_started_at=start,
                defaults={"pipeline_id": rule.pipeline_id})
            if not created:
                continue                        # once per stay
            run(rule, position.contact, actor=None, allow_moves=True)
            fired += 1
    return fired


def send_notice_emails(tenant, now=None) -> int:
    """One email a day to each person with notices not yet emailed."""
    from django.conf import settings

    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.tenancy.context import tenant_context

    now = now or timezone.now()
    pending = PipelineNotice.all_objects.filter(tenant=tenant, emailed_at__isnull=True,
                                                dismissed_at__isnull=True) \
        .select_related("recipient", "contact", "pipeline").order_by("created_at")
    by_person = {}
    for n in pending:
        by_person.setdefault(n.recipient, []).append(n)
    sent = 0
    link = f"{settings.APP_ROOT_URL.rstrip('/')}/"
    for person, notices in by_person.items():
        if not person.email:
            continue
        count = len(notices)
        subject = f"Pipeline: {count} notice{'s' if count != 1 else ''}"
        lines = [f"- {n.text}" + (f" ({n.pipeline.name})" if n.pipeline_id else "")
                 for n in notices]
        body = ("Your stage rules raised these since yesterday:\n\n" + "\n".join(lines)
                + f"\n\nThey are on Home in Execs NOW HQ: {link}")
        with tenant_context(tenant.pk):
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.PIPELINE_NOTICES,
                to_address=person.email, subject=subject, body_text=body, force_direct=True)
        PipelineNotice.all_objects.filter(pk__in=[n.pk for n in notices]).update(emailed_at=now)
        sent += 1
    return sent


# ------------------------------------------------------------- words

def summary(rule) -> str:
    """FR-1.13: the rule in a sentence."""
    from apps.tenancy import words

    task = words.of(rule.tenant).task
    where = f" in {rule.pipeline.name}"
    if rule.trigger == R.Trigger.IDLE:
        when = (f"When a contact has sat in {rule.to_stage.label if rule.to_stage else '?'} "
                f"{rule.idle_days} days with no activity{where}")
    elif rule.trigger == R.Trigger.WON:
        when = f"When a contact is won{where}"
    elif rule.trigger == R.Trigger.LOST:
        when = f"When a contact is lost{where}"
    elif rule.trigger == R.Trigger.DOC_SENT:
        when = f"When a contact is sent a document to sign{where}"
    elif rule.trigger == R.Trigger.DOC_SIGNED:
        when = f"When a contact signs a document{where}"
    elif rule.from_stage is not None:
        when = (f"When a contact moves from {rule.from_stage.label} to "
                f"{rule.to_stage.label}{where}")
    else:
        when = f"When a contact reaches {rule.to_stage.label}{where}"
    who = {R.For.CONTACT_OWNER: "their owner", R.For.PRACTICE_OWNER: "the practice owner",
           R.For.MEMBER: (getattr(rule.task_assignee, "full_name", "") or "a team member")
           if rule.task_assignee_id else "a team member"}[rule.task_for]
    kind = rule.action_type
    if kind == R.Action.CREATE_TASK:
        due = (f" due in {rule.task_due_offset_days} days"
               if rule.task_due_offset_days is not None else "")
        seen = ("the client can see it" if rule.task_client_visible
                else "internal, hidden from the client")
        return f"{when}, create {task} '{rule.task_title_template}' for {who}{due} ({seen})."
    if kind == R.Action.DRAFT_EMAIL:
        name = f" '{rule.email_template.name}'" if rule.email_template_id else ""
        return (f"{when}, draft the email{name} into the Outbox for approval "
                f"(expires after {rule.send_by_offset_days} days).")
    if kind == R.Action.MOVE_STAGE:
        return (f"{when}, move them to "
                f"{rule.move_to_stage.label if rule.move_to_stage else '?'}.")
    if kind == R.Action.ENROLL_TOUCHES:
        return (f"{when}, put them on referral touches"
                f"{', ' + rule.touch_cadence.replace('bimonthly', 'every two months') if rule.touch_cadence else ''}.")
    if kind == R.Action.START_FOLLOW_UP:
        return f"{when}, start the stage's follow-up without asking."
    if kind == R.Action.SEND_SIGNATURE:
        name = f" '{rule.document_template.name}'" if rule.document_template_id else ""
        return (f"{when}, make the document{name} for them to sign and put its email in "
                "the Outbox for approval.")
    if kind == R.Action.CALENDAR_EVENT:
        days = rule.task_due_offset_days if rule.task_due_offset_days is not None else 1
        return (f"{when}, offer a calendar event '{rule.task_title_template}' "
                f"({rule.event_minutes or 30} minutes, suggested {days} "
                f"day{'' if days == 1 else 's'} ahead) at a time the person moving them picks.")
    return f"{when}, tell {who}: “{rule.notice_text}”."


# ------------------------------------------------------------- starter examples

#: One-click examples for a practice's pipelines (owner, 2026-10-24). Found by
#: the seeded stage codes, which survive a rename; an example whose stages a
#: practice has removed is not offered.
EXAMPLES = {
    "sales": [
        {"key": "first_call", "trigger": "enters", "stage": "initial_contact_made",
         "action_type": "create_task",
         "task_title_template": "Call {FirstName} {LastName} at {Company}",
         "task_due_offset_days": 1},
        {"key": "prospecting_quiet", "trigger": "idle", "stage": "prospecting", "idle_days": 14,
         "action_type": "move_stage", "move_to": "follow_up_needed"},
        {"key": "follow_up", "trigger": "enters", "stage": "follow_up_needed",
         "action_type": "create_task",
         "task_title_template": "Follow up with {FirstName} {LastName}",
         "task_due_offset_days": 2},
        {"key": "proposal_follow_up", "trigger": "enters", "stage": "proposal_given",
         "action_type": "create_task",
         "task_title_template": "Follow up on the proposal with {FirstName}",
         "task_due_offset_days": 3},
        {"key": "decision_quiet", "trigger": "idle", "stage": "decision_making", "idle_days": 10,
         "action_type": "notify",
         "notice_text": "{FirstName} {LastName} ({Company}) has been in {Stage} {DaysInStage} "
                        "days with no activity"},
        {"key": "won_kickoff", "trigger": "won", "action_type": "create_task",
         "task_title_template": "Kick off with {Company}", "task_due_offset_days": 2,
         "task_client_visible": True},
        {"key": "lost_check_in", "trigger": "lost", "action_type": "create_task",
         "task_title_template": "Check in with {FirstName} {LastName}",
         "task_due_offset_days": 90},
        # E-signature (owner, 2026-10-29): the two a new practice starts with,
        # and the welcome letter when won.
        {"key": "document_sent", "trigger": "sent", "action_type": "move_stage",
         "move_to": "proposal_given"},
        {"key": "document_signed", "trigger": "signed", "action_type": "move_stage",
         "move_to": "closed_won"},
        {"key": "welcome_letter", "trigger": "enters", "stage": "closed_won",
         "action_type": "draft_email", "email_original": "welcome_letter"},
    ],
    "referral": [
        {"key": "partner_touches", "trigger": "enters", "stage": "new_partner",
         "action_type": "enroll_touches", "touch_cadence": "monthly"},
        {"key": "active_referrer", "trigger": "enters", "stage": "active_referrer",
         "action_type": "notify",
         "notice_text": "{FirstName} {LastName} is now an active referrer"},
        {"key": "nurturing_quiet", "trigger": "idle", "stage": "nurturing", "idle_days": 90,
         "action_type": "move_stage", "move_to": "dormant"},
    ],
}


def examples_for(pipeline) -> list[dict]:
    """The examples this pipeline can take, as rule fields, with whether an
    equal rule is there already."""
    stages = {s.code: s for s in PipelineStage.all_objects.filter(pipeline=pipeline)}
    out = []
    for ex in EXAMPLES.get(pipeline.kind, []):
        fields = {k: v for k, v in ex.items() if k not in ("key", "stage", "move_to")}
        if "stage" in ex:
            if ex["stage"] not in stages:
                continue
            fields["to_stage"] = stages[ex["stage"]]
        if "move_to" in ex:
            if ex["move_to"] not in stages:
                continue
            fields["move_to_stage"] = stages[ex["move_to"]]
        if "email_original" in ex:
            from apps.crm import template_seed
            from apps.crm.models import EmailTemplate

            template_seed.seed_tenant(pipeline.tenant)
            template = EmailTemplate.all_objects.filter(
                tenant_id=pipeline.tenant_id, original=fields.pop("email_original")).first()
            if template is None:
                continue
            fields["email_template"] = template
        rule = R(tenant_id=pipeline.tenant_id, pipeline=pipeline, **fields)
        have = R.all_objects.filter(pipeline=pipeline, trigger=rule.trigger,
                                    to_stage=fields.get("to_stage"),
                                    move_to_stage=fields.get("move_to_stage"),
                                    action_type=rule.action_type).exists()
        out.append({"key": ex["key"], "summary": summary(rule), "added": have,
                    "fields": fields})
    return out
