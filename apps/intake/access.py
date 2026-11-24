"""Who may see and run a company's intake forms.

Owner, 2026-11-23: one permissions screen (apps/agreements/access.py) ticks,
per person, "Owner intake: review, edit and send to Track, and get the team
notices". That tick replaced the level-based rule (the Client owner, Senior
leadership, and Managers on a team): intake no longer looks at team levels.
The practice owner always has it.

Nobody else: for anyone else a company's intake is a 404, as if it did not
exist. The same people are told, in the app and by email, when an owner
submits.
"""

from __future__ import annotations

from django.http import Http404

from apps.tenancy.models import Membership, Role


def _active(qs):
    return qs.filter(revoked_at__isnull=True)


def manager_memberships(company):
    """The company's users ticked for intake (active memberships)."""
    from apps.agreements.models import StaffAccess

    ticked = StaffAccess.all_objects.filter(company=company, intake=True) \
        .values_list("user_id", flat=True)
    return _active(Membership.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, role__in=[Role.FCC, Role.ECC],
        user_id__in=ticked))


def practice_owners(tenant_id):
    return _active(Membership.all_objects.filter(tenant_id=tenant_id, role=Role.FF))


def recipients(company) -> list:
    """Users told about this company's intakes: everyone ticked for intake,
    and the practice owner(s)."""
    ids = set(manager_memberships(company).values_list("user_id", flat=True))
    ids |= set(practice_owners(company.tenant_id).values_list("user_id", flat=True))
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(pk__in=ids, is_active=True))


def is_manager(membership, company) -> bool:
    """May run this company's intakes: the practice owner, or someone ticked."""
    if membership is None or company is None:
        return False
    if membership.role == Role.FF:
        return membership.tenant_id == company.tenant_id
    if membership.role not in (Role.FCC, Role.ECC) \
            or membership.client_company_id != company.pk or membership.revoked_at is not None:
        return False
    return manager_memberships(company).filter(pk=membership.pk).exists()


def companies_for(membership):
    """The companies whose intakes this person runs (intake switched on)."""
    from apps.crm.models import Company

    if membership is None:
        return Company.objects.none()
    qs = Company.all_objects.filter(tenant_id=membership.tenant_id, deleted_at__isnull=True,
                                    is_client_company=True, intake_forms_enabled=True)
    if membership.role == Role.FF:
        return qs
    if membership.role in (Role.FCC, Role.ECC):
        company = qs.filter(pk=membership.client_company_id).first()
        if company and is_manager(membership, company):
            return qs.filter(pk=company.pk)
    return qs.none()


def company_or_404(request, company_id, *, enabled=True):
    """The company, if this person runs its intakes; 404 otherwise."""
    from apps.crm.models import Company

    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    company = Company.all_objects.filter(pk=company_id, tenant_id=membership.tenant_id,
                                         deleted_at__isnull=True,
                                         is_client_company=True).first() \
        if _uuid(company_id) else None
    if company is None or not is_manager(membership, company):
        raise Http404
    if enabled and not company.intake_forms_enabled:
        raise Http404
    return company


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def has_intake(membership) -> bool:
    return companies_for(membership).exists()
