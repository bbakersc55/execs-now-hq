"""Pipelines, positions, the client invariant, and stage automations.

A practice runs more than one pipeline (owner, Check 1): a sales pipeline for
prospects and a nurture pipeline for referral partners. A contact holds an
independent position in each pipeline it belongs to.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    Contact, ContactPipelinePosition, ContactType, ContactTypeLink, Pipeline,
    PipelineStage, StageAutomation, StageChange, StageSemantic,
)
from apps.tenancy.models import AuditEvent


class ClientInvariantError(Exception):
    pass


class PipelineConfigError(Exception):
    """A pipeline edit that would leave the practice unable to close a sale."""


# ------------------------------------------------------------------ lookups

def sales_pipeline(tenant):
    return Pipeline.all_objects.filter(
        tenant=tenant, kind=Pipeline.Kind.SALES
    ).order_by("position").first()


def referral_pipeline(tenant):
    return Pipeline.all_objects.filter(
        tenant=tenant, kind=Pipeline.Kind.REFERRAL
    ).order_by("position").first()


def entry_stage(pipeline):
    """Where a contact enters. The `entry` stage, or failing that the first."""
    return (
        pipeline.stages.filter(semantic=StageSemantic.ENTRY).order_by("position").first()
        or pipeline.stages.order_by("position").first()
    )


def position_for(contact, pipeline):
    return ContactPipelinePosition.all_objects.filter(
        tenant_id=contact.tenant_id, contact=contact, pipeline=pipeline
    ).select_related("stage", "pipeline").first()


def positions_of(contact):
    return list(
        ContactPipelinePosition.all_objects.filter(
            tenant_id=contact.tenant_id, contact=contact
        ).select_related("stage", "pipeline").order_by("pipeline__position")
    )


# ------------------------------------------------------- pipeline management

def validate_pipeline(pipeline):
    """FR-1.6 — a sales pipeline must have exactly one `won` stage.

    The database enforces *at most* one (a partial unique index). "At least one"
    is a cross-row rule, so it is checked here, on the edits that could break it:
    without a `won` stage nothing can ever become a client, and the failure would
    otherwise only show up the first time someone tried to close a deal.
    """
    if pipeline.kind != Pipeline.Kind.SALES:
        return
    won = pipeline.stages.filter(semantic=StageSemantic.WON).count()
    if won != 1:
        raise PipelineConfigError(
            f"“{pipeline.name}” is a sales pipeline and must have exactly one "
            f"stage marked won; it has {won}. Nothing can become a client "
            "without one."
        )


# -------------------------------------------------------------- stage moves

@transaction.atomic
def change_stage(contact, to_stage, *, actor=None, reason="", run_automations=True):
    """FR-1.7 + FR-1.6a — move a contact within ONE pipeline.

    Creates the position if the contact was not in that pipeline yet, which is
    how a contact joins a second pipeline.
    """
    pipeline = to_stage.pipeline
    position = position_for(contact, pipeline)
    from_stage = position.stage if position else None

    if from_stage is not None and from_stage.pk == to_stage.pk:
        return None

    if position is None:
        position = ContactPipelinePosition.all_objects.create(
            tenant=contact.tenant, contact=contact, pipeline=pipeline, stage=to_stage
        )
    else:
        position.stage = to_stage
        position.save(update_fields=["stage", "updated_at"])

    change = StageChange.all_objects.create(
        tenant=contact.tenant, contact=contact, pipeline=pipeline,
        from_stage=from_stage, to_stage=to_stage, reason=reason, actor=actor,
    )
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="stage.changed",
        target_type="contact", target_id=contact.pk,
        payload={
            "pipeline": pipeline.name,
            "from": from_stage.code if from_stage else None,
            "to": to_stage.code, "reason": reason,
        },
    )

    apply_client_invariant(contact, to_stage, actor=actor)
    if run_automations:
        run_stage_automations(contact, from_stage, to_stage, actor=actor)
    return change


@transaction.atomic
def set_stage_from_import(contact, to_stage, *, actor=None):
    """A stage set by the CSV import's value mapping.

    Identical to `change_stage` in everything that defines the record — the
    position moves, a `stage_change` is recorded, an audit event is written, and
    the SAME `apply_client_invariant` runs (FR-1.6a).

    It deliberately does NOT run stage automations. An import is a statement
    about history, not a transition happening now: replaying it through the
    rules would create a follow-up task and queue a client-facing email draft
    for every existing client in the file.
    """
    return change_stage(
        contact, to_stage, actor=actor, reason="csv import", run_automations=False,
    )


def apply_client_invariant(contact, to_stage, *, actor=None):
    """FR-1.6a — reaching a `won` stage in a SALES pipeline is what makes a client.

    Now keyed on the stage's semantic rather than a stage code, because the FF
    renames stages: "Closed Won" may become "Signed" tomorrow and the derivation
    must survive that. The direction is unchanged:

    1. Reaching `won` in a sales pipeline adds contact type `client` and flags
       the company.
    2. Leaving it for `lost` or `parked` removes NEITHER. A lost client is still
       historically a client, and the company may have other active contacts.
    3. Adding the type by hand never changes any stage, and nothing infers a
       stage from a type or a flag.
    4. A contact with no company reaches `won` fine; the company derivation is
       skipped and no placeholder company is invented.
    5. A `won` stage in a REFERRAL or CUSTOM pipeline is not a sale. Reaching
       "Active Referrer" must never flag a company as a client company.
    """
    if to_stage.semantic != StageSemantic.WON:
        return  # rule 2: nothing is ever unwound here.
    if to_stage.pipeline.kind != Pipeline.Kind.SALES:
        return  # rule 5.

    client_type = ContactType.all_objects.filter(
        tenant=contact.tenant, code="client"
    ).first()
    if client_type is not None:
        _, created = ContactTypeLink.all_objects.get_or_create(
            tenant=contact.tenant, contact=contact, contact_type=client_type
        )
        if created:
            AuditEvent.all_objects.create(
                tenant=contact.tenant, actor=actor, verb="contact_type.derived",
                target_type="contact", target_id=contact.pk,
                payload={"type": "client", "because": f"stage={to_stage.code} (won)"},
            )

    company = contact.company  # rule 4
    if company is not None and not company.is_client_company:
        company.is_client_company = True
        company.save(update_fields=["is_client_company", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=contact.tenant, actor=actor, verb="company.flagged",
            target_type="company", target_id=company.pk,
            payload={"is_client_company": True, "because": f"stage={to_stage.code} (won)"},
        )


def run_stage_automations(contact, from_stage, to_stage, *, actor=None):
    """FR-1.10-1.14, scoped to the pipeline the move happened in.

    `create_task` fires immediately and is NOT gated by a review queue: it is
    deterministic, tenant-configured, and has no effect outside the app
    (assumption F3). `draft_email` only ever produces a pending_approval Outbox
    row — it never sends.
    """
    from apps.crm.services.outbox import queue_stage_email

    rules = StageAutomation.all_objects.filter(
        tenant=contact.tenant, pipeline=to_stage.pipeline, to_stage=to_stage,
        is_active=True,
    ).filter(models_q_from_stage(from_stage))

    results = []
    for rule in rules:
        if rule.action_type == StageAutomation.Action.CREATE_TASK:
            results.append(_create_task(contact, rule, actor=actor))
        elif rule.action_type == StageAutomation.Action.DRAFT_EMAIL:
            results.append(queue_stage_email(contact, rule, actor=actor))
    return results


def from_stage_id_equal(a, b):
    return a is not None and b is not None and a.pk == b.pk


def models_q_from_stage(from_stage):
    from django.db.models import Q

    if from_stage is None:
        return Q(from_stage__isnull=True)
    return Q(from_stage__isnull=True) | Q(from_stage=from_stage)


def _create_task(contact, rule, *, actor=None):
    """FR-1.11 — fires immediately, no approval.

    Deliberately NOT gated by a review queue (assumption F3): a rule the tenant
    configured, creating an internal task from a template, is deterministic and
    has no effect outside the app. Anything that reaches a client's inbox is a
    different matter and stays behind the Outbox.
    """
    from apps.crm.models import Task

    due = None
    if rule.task_due_offset_days is not None:
        due = (timezone.now() + timezone.timedelta(days=rule.task_due_offset_days)).date()

    task = Task.all_objects.create(
        tenant=contact.tenant,
        title=rule.task_title_template or "Follow up",
        due_date=due,
        owner=contact.owner,
        contact=contact,
        source_automation=rule,
    )
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="task.created_by_rule",
        target_type="task", target_id=task.pk,
        payload={"contact_id": str(contact.pk), "rule_id": str(rule.pk)},
    )
    return task
