"""Portal access and seats — FR-3.33c to FR-3.33h.

Access is granted **per Contact** by a tenant user, and a seat is consumed from
the company's `seat_count`, counted from live memberships so it cannot drift.
Revoking frees the seat and ends the person's sessions, but leaves the Contact,
their stakeholder rows, their comments and their tasks alone: **revocation is
not deletion**, and a revoked person still receives digests if they are still a
stakeholder, because those are separate entitlements (FR-3.20).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent, Membership, Role


class SeatsExhausted(Exception):
    pass


class PortalAccessRefused(Exception):
    pass


def default_role_for(contact) -> str:
    """FR-3.33d — the company's primary contact is its founder by default."""
    company = contact.company
    if company is not None and company.primary_contact_id == contact.pk:
        return Role.FCC
    return Role.ECC


def access_rows(company):
    return Membership.all_objects.filter(
        client_company=company, role__in=[Role.FCC, Role.ECC], revoked_at__isnull=True
    ).select_related("user", "contact")


@transaction.atomic
def grant(*, tenant, contact, role=None, actor):
    """Create the login, consume a seat, send the magic link."""
    from apps.accounts.models import MagicLinkToken, User
    from apps.accounts.views import _send_magic_link

    company = contact.company
    if company is None or not company.is_client_company:
        raise PortalAccessRefused(
            f"{contact.first_name} is not at a client company, so there is nothing "
            f"to give them access to."
        )
    if not contact.primary_email:
        raise PortalAccessRefused(
            f"{contact.first_name} has no email address, so no sign-in link can be sent."
        )
    role = role or default_role_for(contact)
    if role not in (Role.FCC, Role.ECC):
        raise PortalAccessRefused("Portal access is FCC or ECC.")

    existing = Membership.all_objects.filter(tenant=tenant, contact=contact).first()
    if existing is not None and existing.revoked_at is None:
        raise PortalAccessRefused(f"{contact.first_name} already has access.")

    # FR-3.33e — counted from live memberships, and named in the refusal.
    if company.seats_available is not None and company.seats_available < 1:
        raise SeatsExhausted(
            f"{company.name} has {company.seat_count} seat"
            f"{'s' if company.seat_count != 1 else ''} and "
            f"{company.seats_in_use} in use. Free one, or raise the seat count."
        )

    user, _ = User.objects.get_or_create(
        email=contact.primary_email.lower(),
        defaults={"full_name": f"{contact.first_name} {contact.last_name}".strip()},
    )
    if not user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])

    if existing is not None:
        existing.revoked_at = None
        existing.role = role
        existing.client_company = company
        existing.save(update_fields=["revoked_at", "role", "client_company", "updated_at"])
        membership = existing
    else:
        membership = Membership.all_objects.create(
            tenant=tenant, user=user, role=role, client_company=company,
            contact=contact, invited_by=actor, invited_at=timezone.now(),
        )

    _, raw = MagicLinkToken.issue(tenant=tenant, user=user)
    _send_magic_link(membership, raw)
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="portal.access_granted",
        target_type="membership", target_id=membership.pk,
        payload={"contact": str(contact.pk), "role": role, "company": str(company.pk),
                 "seats_in_use": company.seats_in_use},
    )
    return membership


@transaction.atomic
def revoke(membership, *, actor):
    """FR-3.33g — frees the seat, ends sessions and outstanding links, and
    leaves everything the person authored in place."""
    from apps.accounts.models import MagicLinkToken
    from apps.tenancy.services import _kill_sessions

    links = MagicLinkToken.all_objects.filter(
        tenant_id=membership.tenant_id, user_id=membership.user_id, used_at__isnull=True
    ).update(used_at=timezone.now())
    membership.revoked_at = timezone.now()
    membership.save(update_fields=["revoked_at", "updated_at"])
    sessions = _kill_sessions(membership.user)
    AuditEvent.all_objects.create(
        tenant_id=membership.tenant_id, actor=actor, verb="portal.access_revoked",
        target_type="membership", target_id=membership.pk,
        payload={"sessions_ended": sessions, "links_invalidated": links,
                 "note": "Stakeholder rows, comments and tasks are untouched; "
                         "digests continue if they are still a stakeholder."},
    )
    return {"sessions_ended": sessions, "links_invalidated": links}
