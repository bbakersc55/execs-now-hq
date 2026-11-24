"""Who may do what for a company's owner agreements and intakes (owner,
2026-11-23).

One screen lists every active user of the client company, with three ticks:

a. Owner agreements: create and send, and see agreements and their documents.
b. Receives signed agreement PDFs.
c. Owner intake: review, edit and send to Track, and get the team notices.

It is edited by the practice owner and the company's Client owner (for SkyRun
Park City: Bryan and Michael). The practice owner always has a and c. A new
user starts with nothing ticked. Tick c replaced intake's level-based "Manager
or above" rule: intake no longer looks at team levels.

Countersigning is separate: the signer's standing authorization names who may
apply the signer's signature (`CountersignAuthority`).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.tenancy.models import Membership, Role

from .models import CountersignAuthority, Program, StaffAccess

FLAGS = ("agreements", "signed_pdfs", "intake")


def _active(qs):
    return qs.filter(revoked_at__isnull=True, user__is_active=True)


def is_practice_owner(membership, company) -> bool:
    return bool(membership and company and membership.role == Role.FF
                and membership.tenant_id == company.tenant_id)


def is_client_owner(membership, company) -> bool:
    return bool(membership and company and membership.role == Role.FCC
                and membership.client_company_id == company.pk
                and membership.revoked_at is None)


def may_edit_access(membership, company) -> bool:
    """The permissions screen: the practice owner and the Client owner."""
    return is_practice_owner(membership, company) or is_client_owner(membership, company)


def _in_company(membership, company) -> bool:
    return bool(membership and company and membership.role in (Role.FCC, Role.ECC)
                and membership.client_company_id == company.pk
                and membership.revoked_at is None)


def ticked(membership, company, flag: str) -> bool:
    if not _in_company(membership, company):
        return False
    return StaffAccess.all_objects.filter(company=company, user_id=membership.user_id,
                                          **{flag: True}).exists()


def may_intake(membership, company) -> bool:
    return is_practice_owner(membership, company) or ticked(membership, company, "intake")


def may_agreements(membership, company) -> bool:
    return is_practice_owner(membership, company) or ticked(membership, company, "agreements")


def may_see_documents(membership, company) -> bool:
    """Final agreements in the company's Documents: ticks a or b, plus the
    practice owner and the Client owner."""
    return (may_edit_access(membership, company) or ticked(membership, company, "agreements")
            or ticked(membership, company, "signed_pdfs"))


def company_users(company) -> list:
    """Every active user of the company, and the practice owner(s): the rows
    of the permissions screen."""
    rows = []
    for m in _active(Membership.all_objects.filter(tenant_id=company.tenant_id,
                                                   role=Role.FF)).select_related("user"):
        rows.append((m, True))
    for m in _active(Membership.all_objects.filter(
            tenant_id=company.tenant_id, client_company=company,
            role__in=[Role.FCC, Role.ECC])).select_related("user").order_by("user__full_name"):
        rows.append((m, False))
    return rows


def users_with(company, flag: str, *, practice_owner=False) -> list:
    """Active company users ticked for `flag` (and the practice owner(s), when
    asked or when they ticked it themselves)."""
    User = get_user_model()
    ids = set(StaffAccess.all_objects.filter(company=company, **{flag: True})
              .values_list("user_id", flat=True))
    members = set(_active(Membership.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company,
        role__in=[Role.FCC, Role.ECC])).values_list("user_id", flat=True))
    owners = set(_active(Membership.all_objects.filter(
        tenant_id=company.tenant_id, role=Role.FF)).values_list("user_id", flat=True))
    keep = (ids & members) | (ids & owners)
    if practice_owner:
        keep |= owners
    return list(User.objects.filter(pk__in=keep, is_active=True).order_by("full_name"))


def program_of(company):
    return Program.all_objects.filter(company=company).first()


def is_on(company) -> bool:
    program = program_of(company) if company is not None else None
    return bool(program and program.enabled and company.deleted_at is None)


# ------------------------------------------------------------ countersigning

def authority_in_force(company):
    return (CountersignAuthority.all_objects.filter(company=company, ended_at__isnull=True)
            .order_by("-recorded_at").first())


def is_signer(user, company) -> bool:
    program = program_of(company)
    return bool(program and program.signer_id and user is not None
                and program.signer_id == user.pk)


def may_countersign(user, company) -> tuple[bool, object]:
    """(may, authority). The signer always may (their own signature); anyone
    the authorization in force names may apply it. Without an authorization,
    only the signer."""
    if user is None or company is None:
        return False, None
    if is_signer(user, company):
        return True, authority_in_force(company)
    authority = authority_in_force(company)
    if authority and any(str(p.get("user_id")) == str(user.pk) for p in authority.people):
        member = Membership.all_objects.filter(
            tenant_id=company.tenant_id, user=user, revoked_at__isnull=True).filter(
            client_company=company) | Membership.all_objects.filter(
            tenant_id=company.tenant_id, user=user, revoked_at__isnull=True, role=Role.FF)
        return member.exists(), authority
    return False, authority


def countersigners(company) -> list:
    """Who gets the countersign request: the signer, and the people the
    authorization in force names."""
    User = get_user_model()
    program = program_of(company)
    ids = {program.signer_id} if program and program.signer_id else set()
    authority = authority_in_force(company)
    if authority:
        ids |= {p.get("user_id") for p in authority.people}
    return list(User.objects.filter(pk__in=[i for i in ids if i], is_active=True))


def companies_for(membership):
    """Companies with owner agreements on that this person may see (ticked
    a, the practice owner, or someone who may countersign)."""
    from apps.crm.models import Company

    if membership is None:
        return Company.objects.none()
    on = Program.all_objects.filter(tenant_id=membership.tenant_id, enabled=True) \
        .values_list("company_id", flat=True)
    qs = Company.all_objects.filter(tenant_id=membership.tenant_id, deleted_at__isnull=True,
                                    is_client_company=True, pk__in=on)
    if membership.role == Role.FF:
        return qs
    if membership.role in (Role.FCC, Role.ECC) and membership.revoked_at is None:
        company = qs.filter(pk=membership.client_company_id).first()
        if company and (may_agreements(membership, company)
                        or may_countersign(membership.user, company)[0]
                        or may_see_documents(membership, company)):
            return qs.filter(pk=company.pk)
    return qs.none()


def has_agreements(membership) -> bool:
    return companies_for(membership).exists()


def ticked_or_owner(membership, company, flag: str) -> bool:
    """Ticked for `flag` on the permissions screen, the practice owner's own
    row included (the practice owner ticks "signed PDFs" like anyone)."""
    if membership is None or company is None:
        return False
    if is_practice_owner(membership, company):
        return StaffAccess.all_objects.filter(company=company, user_id=membership.user_id,
                                              **{flag: True}).exists()
    return ticked(membership, company, flag)


def columns_on(company) -> dict:
    """Which ticks the permissions screen shows: agreements and signed PDFs
    while owner agreements are on, intake while intake forms are on."""
    agreements_on = is_on(company)
    return {"agreements": agreements_on, "signed_pdfs": agreements_on,
            "intake": bool(company.intake_forms_enabled)}


def permissions_company_or_404(request, company_id):
    """The company, for its permissions screen: intake forms or owner
    agreements on, and the person may edit it (practice owner, Client owner)."""
    import uuid

    from django.http import Http404

    from apps.crm.models import Company

    membership = getattr(request, "membership", None)
    try:
        uuid.UUID(str(company_id))
    except (TypeError, ValueError):
        raise Http404 from None
    if membership is None:
        raise Http404
    company = Company.all_objects.filter(pk=company_id, tenant_id=membership.tenant_id,
                                         deleted_at__isnull=True,
                                         is_client_company=True).first()
    if company is None or not (company.intake_forms_enabled or is_on(company)) \
            or not may_edit_access(membership, company):
        raise Http404
    return company, membership
