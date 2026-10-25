"""A stage's follow-up (pipeline part 3, owner, 2026-10-24; S3's "Enroll in
X?").

A stage carries at most one follow-up of two or three steps: the first is
drafted the moment it starts (owner, 2026-10-24: so Stop can be seen
withdrawing it), and each after it is "template X from the library, N days
after the previous step was sent", drafted by the daily job. Moving someone into the stage asks "Start the <stage>
follow-up?", default No; a stage rule can start it without asking.

**Each step is a draft.** On its day it goes into the Outbox and waits for
approval like everything else; the next step's day is counted from when that
one was actually sent. A step is drafted once per run, ever (the unique
`follow_up_run_step` pair), so a job that runs twice drafts nothing twice.

**It stops** when the contact sends any email, moves to another stage,
unsubscribes from marketing, a step expires or is refused unsent, or someone
presses Stop. Stopping withdraws any draft still waiting.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.crm.models import (
    FollowUp, FollowUpRun, FollowUpRunStep, FollowUpStep, OutboxMessage, PipelineStage,
)
from apps.tenancy.models import AuditEvent

Run = FollowUpRun
S = OutboxMessage.State
WAITING = (S.DRAFT, S.PENDING_APPROVAL)
#: How long a step's draft waits for approval before it expires (and the
#: follow-up stops), as a stage rule's draft does by default.
DRAFT_EXPIRES_DAYS = 7
REASONS = {
    "replied": "they sent an email",
    "moved": "they moved to another stage",
    "unsubscribed": "they unsubscribed",
    "expired": "a step expired unsent",
    "refused": "a step was refused in the Outbox",
    "stopped": "it was stopped",
    "no_email": "they have no email address",
}


class FollowUpRefused(ValueError):
    pass


def _today(tenant):
    from zoneinfo import ZoneInfo

    return timezone.now().astimezone(ZoneInfo(tenant.timezone)).date() \
        if getattr(tenant, "timezone", "") else timezone.localdate()


def follow_up_of(stage):
    """The stage's follow-up, if it has a usable one (two or three steps)."""
    if stage is None:
        return None
    found = FollowUp.all_objects.filter(stage=stage, is_active=True).first()
    if found is None or not 2 <= FollowUpStep.all_objects.filter(follow_up=found).count() <= 3:
        return None
    return found


def running(contact):
    return Run.all_objects.filter(tenant_id=contact.tenant_id, contact=contact,
                                  status=Run.Status.ACTIVE).select_related(
        "follow_up", "stage", "stage__pipeline")


def offer(contact, stage) -> dict | None:
    """What the move's question offers: the stage's follow-up, unless they are
    already on it."""
    found = follow_up_of(stage)
    if found is None or running(contact).filter(follow_up=found).exists():
        return None
    steps = list(FollowUpStep.all_objects.filter(follow_up=found).select_related("template"))
    return {"stage": str(stage.pk), "stage_label": stage.label, "steps": len(steps),
            "question": f"Start the {stage.label} follow-up?",
            "detail": ", then ".join(
                f"“{s.template.name}” when it starts" if s.position == 1 else
                f"“{s.template.name}” {s.days_after} days after the one before is sent"
                for s in steps)}


# ------------------------------------------------------------- start and stop

@transaction.atomic
def start(contact, stage, *, actor=None, via="asked"):
    """Start the stage's follow-up for a contact sitting in it, its first
    step drafted into the Outbox now. Starting one already running changes
    nothing."""
    from apps.crm.services import pipeline, unsubscribe

    found = follow_up_of(stage)
    if found is None:
        raise FollowUpRefused(f"{stage.label} has no follow-up.")
    position = pipeline.position_for(contact, stage.pipeline)
    if position is None or position.stage_id != stage.pk:
        raise FollowUpRefused(f"{contact.first_name} is not in {stage.label}.")
    if not contact.primary_email:
        raise FollowUpRefused(f"{contact.first_name} has no email address.")
    existing = running(contact).filter(follow_up=found).first()
    if existing is not None:
        return existing, False
    if unsubscribe.suppressed_for_marketing(contact):
        raise FollowUpRefused(f"{contact.first_name} has unsubscribed.")
    first = FollowUpStep.all_objects.filter(follow_up=found).select_related(
        "template").order_by("position").first()
    run = Run.all_objects.create(
        tenant_id=contact.tenant_id, follow_up=found, contact=contact, stage=stage,
        started_by=actor, started_via=via, next_on=_today(contact.tenant))
    AuditEvent.all_objects.create(
        tenant_id=contact.tenant_id, actor=actor, verb="follow_up.started",
        target_type="contact", target_id=contact.pk,
        payload={"stage": stage.label, "pipeline": stage.pipeline.name, "via": via,
                 "run": str(run.pk), "first_on": run.next_on.isoformat()})
    draft_step(run, first)
    run.refresh_from_db()
    return run, True


@transaction.atomic
def stop(run, *, reason="stopped", actor=None):
    """Stop a run and withdraw any of its drafts still waiting for approval."""
    from apps.crm.services import outbox

    run = Run.all_objects.select_for_update().get(pk=run.pk)
    if run.status != Run.Status.ACTIVE:
        return run
    withdrawn = []
    for step in FollowUpRunStep.all_objects.filter(run=run).select_related("outbox_message"):
        message = step.outbox_message
        if message is not None and message.state in WAITING:
            outbox.reject(message, actor=actor)
            OutboxMessage.all_objects.filter(pk=message.pk).update(
                warning=f"Withdrawn: the follow-up stopped because {REASONS.get(reason, reason)}.")
            withdrawn.append(str(message.pk))
    run.status, run.stop_reason = Run.Status.STOPPED, reason
    run.stopped_at, run.stopped_by, run.next_on = timezone.now(), actor, None
    run.save(update_fields=["status", "stop_reason", "stopped_at", "stopped_by", "next_on",
                            "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=run.tenant_id, actor=actor, verb="follow_up.stopped",
        target_type="contact", target_id=run.contact_id,
        payload={"stage": run.stage.label, "reason": reason, "run": str(run.pk),
                 "withdrawn": withdrawn})
    return run


def stop_all(contact, *, reason, actor=None, except_stage=None, pipeline=None) -> int:
    rows = running(contact)
    if pipeline is not None:
        rows = rows.filter(stage__pipeline=pipeline)
    if except_stage is not None:
        rows = rows.exclude(stage=except_stage)
    stopped = 0
    for run in rows:
        stop(run, reason=reason, actor=actor)
        stopped += 1
    return stopped


# ------------------------------------------------------------- the daily pass

def advance(tenant, today=None) -> dict:
    """Every running follow-up of one practice: a step whose draft was sent
    sets the next day; one that expired or was refused stops the run; a run
    whose day has come gets its next step drafted (once); the last step sent
    finishes it."""
    from apps.crm.services import unsubscribe

    today = today or _today(tenant)
    done = {"drafted": 0, "stopped": 0, "finished": 0}
    for run in Run.all_objects.filter(tenant=tenant, status=Run.Status.ACTIVE).select_related(
            "contact", "contact__company", "contact__owner", "stage", "follow_up"):
        steps = list(FollowUpStep.all_objects.filter(follow_up=run.follow_up)
                     .select_related("template").order_by("position"))
        drafted = list(FollowUpRunStep.all_objects.filter(run=run)
                       .select_related("outbox_message").order_by("position"))
        last = drafted[-1] if drafted else None
        if last is not None:
            message = last.outbox_message
            state = message.state if message is not None else S.REJECTED
            if state in (S.EXPIRED,):
                stop(run, reason="expired")
                done["stopped"] += 1
                continue
            if state in (S.REJECTED, S.SUPPRESSED):
                stop(run, reason="unsubscribed" if state == S.SUPPRESSED else "refused")
                done["stopped"] += 1
                continue
            if state in WAITING or state == S.APPROVED:
                continue                                 # waiting for approval or delivery
            # Sent: the next day counts from when it went.
            if last.position >= len(steps):
                Run.all_objects.filter(pk=run.pk).update(status=Run.Status.FINISHED,
                                                         next_on=None, updated_at=timezone.now())
                done["finished"] += 1
                continue
            if run.next_on is None:
                sent = (message.sent_at or message.updated_at)
                # The day it was sent where the practice is, not in UTC.
                from zoneinfo import ZoneInfo

                zone = ZoneInfo(tenant.timezone) if getattr(tenant, "timezone", "") else None
                sent_day = sent.astimezone(zone).date() if zone else sent.date()
                run.next_on = sent_day + timedelta(days=steps[last.position].days_after)
                Run.all_objects.filter(pk=run.pk).update(next_on=run.next_on,
                                                         updated_at=timezone.now())
        if run.next_on is None or run.next_on > today:
            continue
        position = (last.position + 1) if last is not None else 1
        if position > len(steps):
            continue
        contact = run.contact
        if contact.deleted_at is not None:
            stop(run, reason="stopped")
            done["stopped"] += 1
            continue
        if unsubscribe.suppressed_for_marketing(contact):
            stop(run, reason="unsubscribed")
            done["stopped"] += 1
            continue
        if draft_step(run, steps[position - 1]):
            done["drafted"] += 1
    return done


def draft_step(run, step) -> bool:
    """Draft one step into the Outbox, once per run ever."""
    from apps.crm.services import outbox, templates

    contact = run.contact
    try:
        with transaction.atomic():
            row = FollowUpRunStep.all_objects.create(tenant_id=run.tenant_id, run=run,
                                                     position=step.position)
            subject, body = templates.compose(step.template, contact, actor=contact.owner)
            message = outbox.create_message(
                tenant=contact.tenant, producer=OutboxMessage.Producer.FOLLOW_UP,
                to_contact=contact, to_address=contact.primary_email or "",
                subject=subject, body_text=body, actor=contact.owner,
                send_by=timezone.now() + timedelta(days=DRAFT_EXPIRES_DAYS),
                source_type="follow_up", source_id=run.pk)
            row.outbox_message = message
            row.save(update_fields=["outbox_message", "updated_at"])
            Run.all_objects.filter(pk=run.pk).update(next_on=None, updated_at=timezone.now())
    except IntegrityError:
        return False                                     # drafted already
    AuditEvent.all_objects.create(
        tenant_id=run.tenant_id, verb="follow_up.step_drafted", target_type="contact",
        target_id=contact.pk, payload={"stage": run.stage.label, "step": step.position,
                                       "message": str(message.pk)})
    return True


# ------------------------------------------------------------- the contact's page

def line_for(run) -> dict:
    """"Follow-up: step 2 of 3, next on <date>", for the contact's page."""
    total = FollowUpStep.all_objects.filter(follow_up=run.follow_up).count()
    drafted = list(FollowUpRunStep.all_objects.filter(run=run).select_related(
        "outbox_message").order_by("position"))
    last = drafted[-1] if drafted else None
    waiting = last is not None and last.outbox_message is not None and \
        last.outbox_message.state in WAITING
    step = last.position if waiting else (last.position + 1 if last else 1)
    if waiting:
        text = f"Follow-up: step {step} of {total}, waiting for approval in the Outbox"
    elif run.next_on is not None:
        text = f"Follow-up: step {step} of {total}, next on {run.next_on:%B} {run.next_on.day}"
    else:
        text = f"Follow-up: step {step} of {total}, sending"
    return {"id": str(run.pk), "stage": str(run.stage_id), "stage_label": run.stage.label,
            "step": step, "of": total, "next_on": run.next_on.isoformat() if run.next_on
            else None, "waiting": waiting, "text": text}


# ------------------------------------------------------------- setting one up

@transaction.atomic
def save(stage, steps, *, actor=None, is_active=True):
    """Set a stage's follow-up: two or three steps of [{template, days_after}].
    The first step is drafted when it starts, so its days are kept as 0.
    Changing it leaves runs already going on the steps they were drafted
    from, and reads the new ones for what is still to come."""
    from apps.crm.models import EmailTemplate

    if not 2 <= len(steps) <= 3:
        raise FollowUpRefused("A follow-up has two or three steps.")
    rows = []
    for i, raw in enumerate(steps, start=1):
        template = EmailTemplate.all_objects.filter(
            tenant_id=stage.tenant_id, pk=raw.get("template")).first() \
            if _uuid(raw.get("template")) else None
        if template is None:
            raise FollowUpRefused(f"Choose a template for step {i}.")
        if i == 1:
            rows.append((i, template, 0))
            continue
        try:
            days = int(raw.get("days_after"))
        except (TypeError, ValueError):
            raise FollowUpRefused(f"Step {i}: how many days after?") from None
        if not 1 <= days <= 365:
            raise FollowUpRefused(f"Step {i}: between 1 and 365 days.")
        rows.append((i, template, days))
    found, _ = FollowUp.all_objects.get_or_create(
        stage=stage, defaults={"tenant_id": stage.tenant_id, "created_by": actor})
    found.is_active = is_active
    found.save(update_fields=["is_active", "updated_at"])
    FollowUpStep.all_objects.filter(follow_up=found).delete()
    for i, template, days in rows:
        FollowUpStep.all_objects.create(tenant_id=stage.tenant_id, follow_up=found,
                                        position=i, template=template, days_after=days)
    AuditEvent.all_objects.create(
        tenant_id=stage.tenant_id, actor=actor, verb="follow_up.saved",
        target_type="pipeline_stage", target_id=stage.pk,
        payload={"stage": stage.label, "steps": [[t.name, d] for _, t, d in rows]})
    return found


def describe(stage) -> dict | None:
    found = FollowUp.all_objects.filter(stage=stage).first()
    if found is None:
        return None
    steps = list(FollowUpStep.all_objects.filter(follow_up=found).select_related("template"))
    return {"id": str(found.pk), "stage": str(stage.pk), "is_active": found.is_active,
            "running": Run.all_objects.filter(follow_up=found, status=Run.Status.ACTIVE).count(),
            "steps": [{"position": s.position, "template": str(s.template_id),
                       "template_name": s.template.name, "days_after": s.days_after}
                      for s in steps]}


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


# ------------------------------------------------------------- starters

#: One-click starters (owner, 2026-10-24): two templates each, written here,
#: added to the practice's library as ordinary editable templates.
STARTERS = {
    "proposal_follow_up_sequence": {
        "stage": "proposal_given", "days": (0, 7),
        "templates": [
            ("Proposal follow-up 1", "Checking in on the proposal",
             "Hi {FirstName},\n\nI wanted to check that the proposal reached you and see "
             "whether any questions have come up as you've looked it over. Happy to walk "
             "through it on a short call if that's easier."),
            ("Proposal follow-up 2", "Any thoughts on the proposal?",
             "Hi {FirstName},\n\nFollowing up on the proposal for {Company}. If the timing or "
             "the scope needs adjusting, tell me what would work better and I'll revise it."),
        ]},
    "new_partner_follow_up_sequence": {
        "stage": "new_partner", "days": (0, 20),
        "templates": [
            ("New partner follow-up 1", "Good to connect",
             "Hi {FirstName},\n\nThanks again for making time to connect. I'd like to know "
             "more about the clients you serve best, so I can send good introductions your way."),
            ("New partner follow-up 2", "Staying in touch",
             "Hi {FirstName},\n\nA quick note to stay in touch. If you meet a business owner "
             "who could use help with {PracticeNews}, I'd be glad to talk with them."),
        ]},
}


def starters_for(pipeline) -> list[dict]:
    stages = {s.code: s for s in PipelineStage.all_objects.filter(pipeline=pipeline)}
    out = []
    for key, spec in STARTERS.items():
        stage = stages.get(spec["stage"])
        if stage is None:
            continue
        days = spec["days"]
        names = [t[0] for t in spec["templates"]]
        out.append({"key": key, "stage": stage, "added": FollowUp.all_objects.filter(
            stage=stage).exists(),
            "summary": f"When someone enters {stage.label}, offer a follow-up: "
                       f"“{names[0]}” drafted when it starts, then “{names[1]}” "
                       f"{days[1]} days after that one is sent."})
    return out


@transaction.atomic
def add_starter(pipeline, key, *, actor=None):
    from apps.crm.models import EmailTemplate

    spec = STARTERS.get(key)
    offered = {s["key"]: s for s in starters_for(pipeline)}
    if spec is None or key not in offered:
        raise FollowUpRefused("That example isn't offered for this pipeline.")
    stage = offered[key]["stage"]
    steps = []
    for (name, subject, body), days in zip(spec["templates"], spec["days"]):
        template = EmailTemplate.all_objects.filter(tenant_id=pipeline.tenant_id,
                                                    name=name).first()
        if template is None:
            template = EmailTemplate.all_objects.create(
                tenant_id=pipeline.tenant_id, name=name, kind="stage", subject=subject,
                body=body)
        steps.append({"template": str(template.pk), "days_after": days})
    return save(stage, steps, actor=actor)
