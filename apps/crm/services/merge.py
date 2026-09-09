"""Contact merge (FR-1.34, FR-1.34a).

Available to FF and VA, not CF (matrix 4.5). Post-import de-duplication is the
bulk of CRM hygiene and the VA runs the imports; withholding merge would route
the cleanup half of the VA's own work back to the FF.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    ContactEmail, ContactPhone, ContactServiceCategory, ContactTypeLink,
    EmailMessage, EmailThread, OutboxMessage, StageChange, Task,
)
from apps.notes.models import Note
from apps.tenancy.models import AuditEvent, Membership, Role


class MergeNotPermitted(Exception):
    pass


@transaction.atomic
def merge_contacts(survivor, absorbed, *, actor=None, role=None, field_choices=None):
    """All history moves to the survivor; the absorbed record is soft-deleted
    with a pointer, so its old id still resolves."""
    if role is not None and role not in (Role.FF, Role.VA):
        raise MergeNotPermitted("Only the founder fractional or a VA may merge contacts.")
    if survivor.pk == absorbed.pk:
        raise ValueError("Cannot merge a contact into itself.")
    if survivor.tenant_id != absorbed.tenant_id:
        raise ValueError("Cannot merge contacts across tenants.")

    tenant = survivor.tenant

    for field, value in (field_choices or {}).items():
        setattr(survivor, field, value)

    # History moves. Emails/phones lose their primary flag so the partial
    # unique constraint (one primary per contact) is not violated.
    ContactEmail.all_objects.filter(tenant=tenant, contact=absorbed).update(
        contact=survivor, is_primary=False
    )
    ContactPhone.all_objects.filter(tenant=tenant, contact=absorbed).update(
        contact=survivor, is_primary=False
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
        },
    )
    return survivor


def resolve(contact):
    """FR-1.34 — a merged-away id still resolves to the survivor."""
    seen = set()
    while contact.merged_into_id and contact.pk not in seen:
        seen.add(contact.pk)
        contact = contact.merged_into
    return contact
