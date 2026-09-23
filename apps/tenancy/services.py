"""Tenant staff management (FR-0.8). FF-only — matrix rows 3.16-3.18."""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent, ClientAssignment, Membership, Role


class StaffActionNotPermitted(Exception):
    pass


def contact_for_staff(tenant, *, email: str, full_name: str = "", actor=None):
    """The contact row that stands for a member of staff — found, or made.

    **Every human is a Contact** (assumption F1) and a login attaches to one.
    Client users have always arrived that way round, because portal access is
    granted *on* a contact. A staff invite starts from an address instead, and
    nothing was closing the gap: the owner's own membership had no contact, so
    meeting ingestion had to find him by guessing among the "Bryan Baker" rows
    in his own CRM (FR-5.9e). This is the link that makes the guess a fallback
    instead of the only route.

    Resolution is **email, then name**, the same order as everywhere else in
    this product, and it **never modifies a contact it did not create** —
    linking is not a licence to retype somebody. A name that matches more than
    one contact is not a match: a new row carrying the address is created
    instead, which is the thing that makes the *next* lookup unambiguous.
    """
    from apps.crm.models import Contact, ContactEmail
    from apps.crm.services import referral

    address = (email or "").strip().lower()
    name = " ".join((full_name or "").strip().split())

    # `all_objects` with an explicit tenant, like everything else in this
    # module: `invite_member` runs from management commands too, which bind no
    # tenant. The filter is the scoping, and it is written out rather than
    # inherited.
    if address:
        row = (ContactEmail.all_objects.filter(tenant=tenant, address__iexact=address,
                                               contact__deleted_at__isnull=True)
               .select_related("contact").first())
        if row is not None:
            return row.contact, False

    if name:
        parts = name.split()
        found = list(Contact.all_objects.filter(
            tenant=tenant, deleted_at__isnull=True, first_name__iexact=parts[0],
            last_name__iexact=parts[-1] if len(parts) > 1 else "")[:2])
        if len(found) == 1:
            return found[0], False

    contact = Contact.all_objects.create(
        tenant=tenant,
        first_name=name.split(" ")[0] if name else (address.split("@")[0] or "Staff"),
        last_name=" ".join(name.split(" ")[1:]) if " " in name else "",
        source="staff invite",
    )
    if address:
        ContactEmail.all_objects.create(tenant=tenant, contact=contact,
                                        address=address, is_primary=True)
    # Only on a row we just made. An existing contact keeps whatever they
    # already are: the practice's own people are frequently in the CRM as
    # something else first, and an invite is no reason to overwrite that.
    referral.add_type(contact, "coworker", actor=actor)
    return contact, True


@transaction.atomic
def invite_member(*, tenant, email, role, full_name="", actor=None):
    """FR-0.8a — invitation is by email against a pre-created membership.

    Sign-in fails for any address without one (C1), so this row IS the invite.
    """
    from apps.accounts.models import User

    if role in (Role.FCC, Role.ECC):
        raise StaffActionNotPermitted(
            "Client users are granted portal access on a contact, not invited as staff."
        )

    user, _ = User.objects.get_or_create(
        email=email.strip().lower(), defaults={"full_name": full_name}
    )
    if not user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])

    membership, created = Membership.all_objects.get_or_create(
        tenant=tenant, user=user,
        defaults={"role": role, "invited_by": actor, "invited_at": timezone.now()},
    )
    if not created and membership.revoked_at is not None:
        membership.revoked_at = None
        membership.role = role
        membership.save(update_fields=["revoked_at", "role", "updated_at"])

    # F1 — a login attaches to a contact. Never overwritten: a membership that
    # already points somewhere is pointing there for a reason.
    made = False
    if membership.contact_id is None:
        contact, made = contact_for_staff(tenant, email=user.email,
                                          full_name=user.full_name, actor=actor)
        membership.contact = contact
        membership.save(update_fields=["contact", "updated_at"])

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="member.invited",
        target_type="membership", target_id=membership.pk,
        payload={"email": user.email, "role": role,
                 "contact": str(membership.contact_id) if membership.contact_id else None,
                 "contact_created": made},
    )
    return membership


@transaction.atomic
def change_role(membership, new_role, *, actor=None):
    """FR-0.8b — takes effect on the member's next request."""
    if new_role in (Role.FCC, Role.ECC) or membership.role in (Role.FCC, Role.ECC):
        raise StaffActionNotPermitted(
            "Client roles are managed through portal access, not staff roles."
        )
    old = membership.role
    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=membership.tenant, actor=actor, verb="member.role_changed",
        target_type="membership", target_id=membership.pk,
        payload={"from": old, "to": new_role},
    )
    return membership


@transaction.atomic
def remove_member(membership, *, actor=None):
    """FR-0.8c — removal CASCADES.

    Sessions invalidated; for a CF every live client_assignment closed and the
    Gmail connection deleted with its stored token. NOTHING they authored is
    removed: a departed CF's tasks, notes, and sent mail stay on the record.
    """
    from apps.crm.models import GmailConnection

    tenant = membership.tenant
    now = timezone.now()

    membership.revoked_at = now
    membership.save(update_fields=["revoked_at", "updated_at"])

    assignments = ClientAssignment.all_objects.filter(
        tenant=tenant, user=membership.user, removed_at__isnull=True
    )
    assignment_count = assignments.count()
    assignments.update(removed_at=now)

    connections = GmailConnection.all_objects.filter(tenant=tenant, user=membership.user)
    connection_count = connections.count()
    for connection in connections:
        if connection.secret_id:
            connection.secret.delete()  # the stored refresh token goes too
        connection.delete()

    session_count = _kill_sessions(membership.user)

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="member.removed",
        target_type="membership", target_id=membership.pk,
        payload={
            "email": membership.user.email, "role": membership.role,
            "assignments_closed": assignment_count,
            "gmail_connections_removed": connection_count,
            "sessions_invalidated": session_count,
        },
    )
    return {
        "assignments_closed": assignment_count,
        "gmail_connections_removed": connection_count,
        "sessions_invalidated": session_count,
    }


def _kill_sessions(user):
    killed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if str(data.get("_auth_user_id")) == str(user.pk):
            session.delete()
            killed += 1
    return killed
