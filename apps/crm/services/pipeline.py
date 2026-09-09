"""Pipeline stage changes, the client invariant, and stage automations."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    Contact, ContactType, ContactTypeLink, PipelineStage, StageAutomation, StageChange,
)
from apps.tenancy.models import AuditEvent


class ClientInvariantError(Exception):
    pass


@transaction.atomic
def change_stage(contact: Contact, to_stage: PipelineStage, *, actor=None, reason=""):
    """FR-1.7 + FR-1.6a. Records the change, derives the client invariant, and
    fires any matching automations."""
    from_stage = contact.stage
    if from_stage_id_equal(from_stage, to_stage):
        return None

    contact.stage = to_stage
    contact.save(update_fields=["stage", "updated_at"])

    change = StageChange.all_objects.create(
        tenant=contact.tenant, contact=contact, from_stage=from_stage,
        to_stage=to_stage, reason=reason, actor=actor,
    )
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="stage.changed",
        target_type="contact", target_id=contact.pk,
        payload={
            "from": from_stage.code if from_stage else None,
            "to": to_stage.code, "reason": reason,
        },
    )

    apply_client_invariant(contact, to_stage, actor=actor)
    run_stage_automations(contact, from_stage, to_stage, actor=actor)
    return change


def from_stage_id_equal(a, b):
    return a is not None and b is not None and a.pk == b.pk


def apply_client_invariant(contact: Contact, to_stage: PipelineStage, *, actor=None):
    """FR-1.6a — pipeline stage is the SINGLE SOURCE OF TRUTH for "is a client".

    The derivation runs in ONE direction only:

    1. Reaching stage `client` adds contact type `client` and flags the company.
    2. Leaving `client` for `lost` or `dormant` removes NEITHER. A lost client is
       still historically a client, and the company may have other active
       contacts. Unsetting either is a deliberate manual act.
    3. Adding the type by hand never changes the stage, and nothing infers a
       stage from a type or a flag.
    4. A contact with no company reaches `client` fine; the company derivation
       is skipped and no placeholder company is invented.
    """
    if to_stage.code != "client":
        return  # rule 2: nothing is ever unwound here.

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
                payload={"type": "client", "because": "stage=client"},
            )

    company = contact.company  # rule 4
    if company is not None and not company.is_client_company:
        company.is_client_company = True
        company.save(update_fields=["is_client_company", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=contact.tenant, actor=actor, verb="company.flagged",
            target_type="company", target_id=company.pk,
            payload={"is_client_company": True, "because": "stage=client"},
        )


def run_stage_automations(contact, from_stage, to_stage, *, actor=None):
    """FR-1.10-1.14.

    `create_task` fires immediately and is NOT gated by a review queue: it is
    deterministic, tenant-configured, and has no effect outside the app
    (assumption F3). `draft_email` only ever produces a pending_approval Outbox
    row — it never sends.
    """
    from apps.crm.services.outbox import queue_stage_email

    rules = StageAutomation.all_objects.filter(
        tenant=contact.tenant, to_stage=to_stage, is_active=True
    ).filter(models_q_from_stage(from_stage))

    results = []
    for rule in rules:
        if rule.action_type == StageAutomation.Action.CREATE_TASK:
            results.append(_create_task(contact, rule, actor=actor))
        elif rule.action_type == StageAutomation.Action.DRAFT_EMAIL:
            results.append(queue_stage_email(contact, rule, actor=actor))
    return results


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
