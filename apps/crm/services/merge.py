"""Contact merge (FR-1.34, FR-1.34a).

Available to FF and VA, not CF (matrix 4.5). Post-import de-duplication is the
bulk of CRM hygiene and the VA runs the imports; withholding merge would route
the cleanup half of the VA's own work back to the FF.
"""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone

from apps.crm.models import (
    ContactEmail, ContactPhone, ContactServiceCategory, ContactTypeLink,
    EmailMessage, EmailThread, OutboxMessage, StageChange, Task,
)
from apps.notes.models import Note
from apps.tenancy.models import AuditEvent, Membership, Role


class MergeNotPermitted(PermissionDenied):
    """A 403 with its message wherever it is raised, not a server error."""


@transaction.atomic
def merge_contacts(survivor, absorbed, *, actor=None, role=None, field_choices=None):
    """All history moves to the survivor; the absorbed record is soft-deleted
    with a pointer, so its old id still resolves."""
    if role is not None and role not in (Role.FF, Role.VA):
        raise MergeNotPermitted("Only the practice owner or an assistant can merge contacts.")
    if survivor.pk == absorbed.pk:
        raise ValueError("Cannot merge a contact into itself.")
    if survivor.tenant_id != absorbed.tenant_id:
        raise ValueError("Cannot merge contacts across tenants.")

    tenant = survivor.tenant

    for field, value in (field_choices or {}).items():
        setattr(survivor, field, value)

    # FR-1.34 — emails and phones move, DE-DUPLICATED. Two records for the same
    # person usually hold the same mobile number, and a bulk move produced a
    # survivor carrying it twice: the merge screen exists to clean duplicates
    # up, so it must not manufacture new ones.
    #
    # Matching mirrors the rules used elsewhere: addresses case-insensitively,
    # numbers on their digits, so "+1 555-0100" and "15550100" are one number.
    _merge_child_values(
        ContactEmail, tenant, survivor, absorbed,
        value_field="address", key=lambda v: v.strip().lower(),
    )
    _merge_child_values(
        ContactPhone, tenant, survivor, absorbed,
        value_field="number", key=lambda v: "".join(c for c in v if c.isdigit()) or v.strip(),
    )

    for link in ContactTypeLink.all_objects.filter(tenant=tenant, contact=absorbed):
        if not ContactTypeLink.all_objects.filter(
            tenant=tenant, contact=survivor, contact_type_id=link.contact_type_id
        ).exists():
            link.contact = survivor
            link.is_primary = False
            link.save(update_fields=["contact", "is_primary", "updated_at"])
        else:
            link.delete()

    for link in ContactServiceCategory.all_objects.filter(tenant=tenant, contact=absorbed):
        if not ContactServiceCategory.all_objects.filter(
            tenant=tenant, contact=survivor, service_category_id=link.service_category_id
        ).exists():
            link.contact = survivor
            link.save(update_fields=["contact", "updated_at"])
        else:
            link.delete()

    for model in (Note, Task, StageChange, EmailThread, EmailMessage, OutboxMessage):
        field = "to_contact" if model is OutboxMessage else "contact"
        model.all_objects.filter(**{"tenant": tenant, field: absorbed}).update(
            **{field: survivor}
        )

    moved = _merge_later_tables(tenant, survivor, absorbed, actor=actor)

    absorbed.deleted_at = timezone.now()
    absorbed.merged_into = survivor
    absorbed.save(update_fields=["deleted_at", "merged_into", "updated_at"])
    survivor.save()

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="contact.merged",
        target_type="contact", target_id=survivor.pk,
        payload={
            "survivor": str(survivor.pk),
            "absorbed": str(absorbed.pk),
            "actor_role": role,
            "moved": moved,
        },
    )
    return survivor


#: Every relation onto a contact, and what a merge does with it. The test
#: `test_every_contact_relation_has_a_merge_rule` fails when a new table points
#: at contacts and is not listed here — which is how the tables added after
#: Module 1 (meetings, commitments, stakeholders, suppressions…) were missed
#: until 2026-09-29.
HANDLED_RELATIONS = {
    # Moved above, de-duplicated by value.
    "contact_email.contact", "contact_phone.contact",
    "contact_type_link.contact", "contact_service_category.contact",
    # Moved above, wholesale.
    "note.contact", "task.contact", "stage_change.contact", "email_thread.contact",
    "email_message.contact", "outbox_message.to_contact",
    # _merge_later_tables.
    "membership.contact", "company.primary_contact", "contact.merged_into",
    "contact_pipeline_position.contact", "enrollment.contact",
    "email_suppression.contact", "campaign_recipient.contact",
    "stakeholder.contact", "digest.contact", "strategy_session.contact",
    "meeting_participant.contact", "commitment.contact",
}


def _merge_later_tables(tenant, survivor, absorbed, *, actor=None) -> dict:
    """The relations added after Module 1 (owner, 2026-09-29: "Merge
    duplicates" is one click, so the merge behind it must leave nothing
    behind).

    Each row moves to the survivor unless the survivor already holds the same
    thing (the same meeting, the same task's stakeholder, the same pipeline).
    Then the survivor's row stands and the absorbed one stays where it is, on a
    record that is soft-deleted and still resolves — nothing historical is
    destroyed. Two exceptions, both so the absorbed record can do nothing
    further: a duplicate stakeholder row is deleted (a deleted contact must
    not be sent digests), and a duplicate open enrollment is ended.
    """
    from apps.crm.models import (
        CampaignRecipient, Company, Contact, ContactPipelinePosition, EmailSuppression,
        Enrollment,
    )
    from apps.meetings.models import Commitment, MeetingParticipant
    from apps.strategy.models import StrategySession
    from apps.work.models import Digest, Stakeholder

    counts: dict[str, int] = {}

    def note(label, n):
        if n:
            counts[label] = counts.get(label, 0) + n

    def move_all(model, field="contact"):
        note(model._meta.db_table, model.all_objects.filter(
            tenant=tenant, **{field: absorbed}).update(**{field: survivor}))

    def move_unless_held(model, keys, *, live=None, on_conflict="leave"):
        """`keys`: the fields that, with the contact, make a row unique.
        `live`: a filter limiting the uniqueness to some rows (a partial
        index), applied to both sides."""
        rows = model.all_objects.filter(tenant=tenant, contact=absorbed)
        for row in rows:
            same = model.all_objects.filter(
                tenant=tenant, contact=survivor, **{k: getattr(row, k) for k in keys})
            clash = same.exists()
            if clash and live is not None:
                clash = (model.all_objects.filter(pk=row.pk, **live).exists()
                         and same.filter(**live).exists())
            if not clash:
                model.all_objects.filter(pk=row.pk).update(contact=survivor)
                note(model._meta.db_table, 1)
            elif on_conflict == "delete":
                row.delete()
                note(f"{model._meta.db_table} (duplicate removed)", 1)
            elif on_conflict == "end":
                model.all_objects.filter(pk=row.pk).update(
                    ended_at=timezone.now(), ended_by=actor,
                    ended_reason=Enrollment.EndReason.UNENROLLED)
                note(f"{model._meta.db_table} (duplicate ended)", 1)
            else:
                note(f"{model._meta.db_table} (kept on the merged record)", 1)

    # A portal login follows the person.
    move_all(Membership)
    move_all(Company, "primary_contact")
    move_all(Contact, "merged_into")
    move_all(StrategySession)
    move_all(Commitment)
    move_unless_held(ContactPipelinePosition, ["pipeline_id"])
    move_unless_held(Enrollment, ["program"], live={"ended_at__isnull": True},
                     on_conflict="end")
    # An unsubscribe must follow the person, or the survivor becomes mailable.
    move_unless_held(EmailSuppression, ["category"], live={"lifted_at__isnull": True})
    move_unless_held(CampaignRecipient, ["campaign_id"])
    move_unless_held(Stakeholder, ["goal_id", "project_id", "task_id"],
                     on_conflict="delete")
    move_unless_held(Digest, ["cadence", "period_start"],
                     live={"state__in": [s for s in Digest.State.values
                                         if s not in ("expired", "skipped")]})
    move_unless_held(MeetingParticipant, ["meeting_id"], on_conflict="delete")
    return counts


def _merge_child_values(model, tenant, survivor, absorbed, *, value_field, key):
    """Move the absorbed record's rows onto the survivor, skipping duplicates.

    The survivor keeps exactly one primary: its own if it had one, otherwise the
    first row promoted from the absorbed record. The partial unique index allows
    only one, so this is enforcement, not tidiness.
    """
    existing = list(model.all_objects.filter(tenant=tenant, contact=survivor))
    seen = {key(getattr(row, value_field)) for row in existing}
    survivor_has_primary = any(row.is_primary for row in existing)

    for row in model.all_objects.filter(tenant=tenant, contact=absorbed).order_by(
        "-is_primary", "created_at"
    ):
        fingerprint = key(getattr(row, value_field))
        if fingerprint in seen:
            # The survivor already holds this value. Dropping the duplicate row
            # loses nothing: the value itself is preserved on the survivor.
            row.delete()
            continue
        seen.add(fingerprint)
        row.contact = survivor
        row.is_primary = not survivor_has_primary
        survivor_has_primary = True
        row.save(update_fields=["contact", "is_primary", "updated_at"])


def resolve(contact):
    """FR-1.34 — a merged-away id still resolves to the survivor."""
    seen = set()
    while contact.merged_into_id and contact.pk not in seen:
        seen.add(contact.pk)
        contact = contact.merged_into
    return contact
