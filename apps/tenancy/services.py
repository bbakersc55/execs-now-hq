"""Tenant staff management (FR-0.8). FF-only — matrix rows 3.16-3.18."""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent, ClientAssignment, Membership, Role


class StaffActionNotPermitted(Exception):
    pass


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

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="member.invited",
        target_type="membership", target_id=membership.pk,
        payload={"email": user.email, "role": role},
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
