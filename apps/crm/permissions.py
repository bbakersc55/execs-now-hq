"""Role enforcement for Module 1. Source of truth: `03_access_matrix.md`.

Status-code rule, applied consistently (matrix §1):
  - out-of-scope reads return 404, never 403 — a 403 would confirm the row
    exists to a CF probing an unassigned company;
  - in-scope but role-forbidden actions return 403.
"""

from __future__ import annotations

from django.db.models import Q
from rest_framework import permissions

from apps.tenancy.models import ClientAssignment, Role

TENANT_ROLES = {Role.FF, Role.CF, Role.VA}
CLIENT_ROLES = {Role.FCC, Role.ECC}


def role_of(request):
    membership = getattr(request, "membership", None)
    return membership.role if membership else None


def assigned_company_ids(request):
    """FR-1.9a — the row every "assigned accounts" rule resolves through."""
    membership = getattr(request, "membership", None)
    if membership is None:
        return []
    return list(
        ClientAssignment.all_objects.filter(
            tenant_id=membership.tenant_id, user_id=membership.user_id,
            removed_at__isnull=True,
        ).values_list("company_id", flat=True)
    )


class IsTenantStaff(permissions.BasePermission):
    """Module 1 has NO client-facing surface (matrix 4.18).

    A permanent boundary, not a Beta limitation: client users never see the CRM,
    the pipeline, vendors, referral partners, or the Outbox.
    """

    message = "This area is not available to client users."

    def has_permission(self, request, view):
        return role_of(request) in TENANT_ROLES


class IsFF(permissions.BasePermission):
    message = "Only the founder fractional may do this."

    def has_permission(self, request, view):
        return role_of(request) == Role.FF


class IsFFOrVA(permissions.BasePermission):
    """Matrix 4.5 — merge, and 3.14 contact types / service categories."""

    message = "Only the founder fractional or a VA may do this."

    def has_permission(self, request, view):
        return role_of(request) in (Role.FF, Role.VA)


class CanSend(permissions.BasePermission):
    """Matrix 5.3 — the H7 boundary. A VA may draft and reject, never send."""

    message = "A VA cannot approve or send. Ask the founder fractional."

    def has_permission(self, request, view):
        return role_of(request) in (Role.FF, Role.CF)


class CanConnectMailbox(permissions.BasePermission):
    """H7 — a VA gets no mailbox of their own in the app.

    Distinct from `CanSend` on purpose. `CanSend` is about approving somebody
    else's draft; this is about granting the app a credential that can send as
    you. Same two roles today, different reasons — and Tier 2 (FR-6.3g) widens
    only this one.
    """

    message = "A VA does not connect a mailbox. Ask the founder fractional."

    def has_permission(self, request, view):
        return role_of(request) in (Role.FF, Role.CF)


def contact_queryset_for(request, queryset):
    """FR-1.9c — a CF's visible universe is EXACTLY:
      assigned client companies + prospects they own + their own no-company
      contacts. Nothing else in the tenant.

    FR-1.9d — a VA sees all contacts. The VA restriction is financials and
    settings, not the CRM.
    """
    role = role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        membership = request.membership
        return queryset.filter(
            Q(company_id__in=assigned_company_ids(request))
            | Q(owner_id=membership.user_id)
        )
    return queryset.none()


def company_queryset_for(request, queryset):
    role = role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        return queryset.filter(pk__in=assigned_company_ids(request))
    return queryset.none()


def outbox_queryset_for(request, queryset):
    """Matrix 5.1 — CF sees messages to contacts on assigned companies."""
    role = role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        return queryset.filter(to_contact__company_id__in=assigned_company_ids(request))
    return queryset.none()
