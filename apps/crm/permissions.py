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
    message = "Only the practice owner can do this."

    def has_permission(self, request, view):
        return role_of(request) == Role.FF


class IsFFOrVA(permissions.BasePermission):
    """Matrix 4.5 — merge, and 3.14 contact types / service categories."""

    message = "Only the practice owner or an assistant can do this."

    def has_permission(self, request, view):
        return role_of(request) in (Role.FF, Role.VA)


class CanSend(permissions.BasePermission):
    """Matrix 5.3 — the H7 boundary. A VA may draft and reject, never send."""

    message = "Assistants can't approve or send. Ask the practice owner."

    def has_permission(self, request, view):
        return role_of(request) in (Role.FF, Role.CF)


class CanConnectMailbox(permissions.BasePermission):
    """H7 — a VA gets no mailbox of their own in the app.

    Distinct from `CanSend` on purpose. `CanSend` is about approving somebody
    else's draft; this is about granting the app a credential that can send as
    you. Same two roles today, different reasons — and Tier 2 (FR-6.3g) widens
    only this one.
    """

    message = "Assistants don't connect a mailbox. Ask the practice owner."

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


#: The Outbox producers that carry money: the invoice (P4A), and a card
#: payment's receipt and notice (P4 part 2).
INVOICE_PRODUCER = "client_invoice"
MONEY_PRODUCERS = (INVOICE_PRODUCER, "payment_receipt", "payment_notice", "autopay_notice",
                   "subscription_receipt", "subscription_notice")


def sees_money(request, company_id=None) -> bool:
    """Matrix 13.4a — who may see an invoice, and so any email that is one.

    The practice owner, always. An associate for a client company they are
    assigned to, and never for an invoice to a contact (which has no company).
    An assistant, never: `CLAUDE.md`, "no financials".
    """
    role = role_of(request)
    if role == Role.FF:
        return True
    if role == Role.CF:
        return company_id is not None and company_id in assigned_company_ids(request)
    return False


def without_money(request, queryset, *, thread="thread"):
    """An Outbox queryset with every invoice the requester may not see left
    out. The company an invoice bills is on its thread, which is its own
    (`EmailThread.is_financial`), so this needs nothing from the billing app.
    `thread` is the path to the thread from the rows being filtered."""
    role = role_of(request)
    if role == Role.FF:
        return queryset
    invoices = Q(producer__in=MONEY_PRODUCERS)
    if role == Role.CF:
        return queryset.exclude(invoices & ~Q(**{
            f"{thread}__client_company_id__in": assigned_company_ids(request)}))
    return queryset.exclude(invoices)


#: Owner agreements and owner intake (SkyRun only; owner, 2026-11-24): their
#: mail shows only to someone with the matching tick for that company on
#: People and permissions, the practice owner always. A code to see a tax
#: number shows only to the person it went to, and the practice owner.
AGREEMENT_MAIL = ("owner_agreement", "owner_agreement_notice")
INTAKE_MAIL = ("intake_notice",)
CODE_MAIL = ("tax_number_code",)
OWNER_MAIL = AGREEMENT_MAIL + INTAKE_MAIL + CODE_MAIL


def _owner_mail_allowed(request) -> Q:
    """The owner agreement, intake and code mail a requester other than the
    practice owner may see, as a condition on Outbox rows: only what their
    ticks allow, and nothing that can't be traced to a company they are ticked
    for (shut, not open, when in doubt)."""
    from apps.agreements import access
    from apps.agreements.models import OwnerAgreement, Program, StaffAccess
    from apps.crm.models import Company
    from apps.intake.models import Submission

    membership = getattr(request, "membership", None)
    user = getattr(request, "user", None)
    companies = []
    if membership is not None:
        companies = list(Company.all_objects.filter(
            tenant_id=membership.tenant_id, pk__in=StaffAccess.all_objects.filter(
                tenant_id=membership.tenant_id, user_id=membership.user_id)
            .values("company_id")))
    agreements = [c.pk for c in companies if access.may_agreements(membership, c)]
    intake = [c.pk for c in companies if access.may_intake(membership, c)]
    allowed = Q(pk__in=[])
    if agreements:
        allowed |= Q(producer__in=AGREEMENT_MAIL, source_type="owner_agreement",
                     source_id__in=OwnerAgreement.all_objects.filter(
                         company_id__in=agreements).values("pk"))
        allowed |= Q(producer__in=AGREEMENT_MAIL, source_type="owner_agreement_program",
                     source_id__in=Program.all_objects.filter(
                         company_id__in=agreements).values("pk"))
    if intake:
        allowed |= Q(producer__in=INTAKE_MAIL, source_type="intake_submission",
                     source_id__in=Submission.all_objects.filter(
                         company_id__in=intake).values("pk"))
    email = (getattr(user, "email", "") or "").strip()
    if email:
        allowed |= Q(producer__in=CODE_MAIL, to_address__iexact=email)
    return allowed


def without_owner_mail(request, queryset):
    """An Outbox queryset without the owner agreement, intake and code mail
    the requester may not see (see `OWNER_MAIL`)."""
    if role_of(request) == Role.FF:
        return queryset
    return queryset.filter(~Q(producer__in=OWNER_MAIL) | _owner_mail_allowed(request))


def threads_without_owner_mail(request, queryset):
    """The same rule for mail threads: every message the Outbox sends is on a
    thread, so a thread holding owner agreement, intake or code mail the
    requester may not see is not theirs to read (nor any reply to it)."""
    if role_of(request) == Role.FF:
        return queryset
    from apps.crm.models import OutboxMessage

    membership = getattr(request, "membership", None)
    mine = OutboxMessage.all_objects.filter(
        tenant_id=getattr(membership, "tenant_id", None), producer__in=OWNER_MAIL)
    hidden = mine.exclude(pk__in=mine.filter(_owner_mail_allowed(request)).values("pk")) \
        .filter(thread__isnull=False).values("thread_id")
    return queryset.exclude(pk__in=hidden)


def threads_without_money(request, queryset):
    """The same rule for threads: a financial thread holds an invoice and the
    replies to it, and is not part of the history an assistant shares."""
    role = role_of(request)
    if role == Role.FF:
        return queryset
    if role == Role.CF:
        return queryset.exclude(Q(is_financial=True) & ~Q(
            client_company_id__in=assigned_company_ids(request)))
    return queryset.exclude(is_financial=True)


def outbox_queryset_for(request, queryset):
    """Matrix 5.1 — CF sees messages to contacts on assigned companies.
    Matrix 13.4a — and nobody sees an invoice they may not (`without_money`).
    Owner agreements and intake — nor that mail without the tick for its
    company, nor someone else's tax number code (`without_owner_mail`)."""
    role = role_of(request)
    if role in (Role.FF, Role.VA):
        return without_owner_mail(request, without_money(request, queryset))
    if role == Role.CF:
        return without_owner_mail(request, without_money(request, queryset.filter(
            to_contact__company_id__in=assigned_company_ids(request))))
    return queryset.none()
