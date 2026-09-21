"""Who sees and changes what in the task engine. Source: `03_access_matrix.md` §7.

Scopes, per the matrix:

- **FF, VA** — everything in the tenant.
- **CF** — `assigned` client companies, **plus `own-work`**: anything they own
  or are assigned, whatever company it sits on, the practice's internal work
  included. A task reaches them by a fourth path as well — the contact it hangs
  off, if that contact is in their FR-1.9c universe. (Matrix 7.1 said
  `assigned` alone until 2026-09-17; the owner ruled the code right and the row
  wrong. A CF's own work is theirs: work assigned to someone who cannot see it
  is a bug, not a scope.)
- **FCC, ECC** — their own company only, and for tasks only client-visible
  ones (FR-3.13). Out of scope is 404, never 403.

FR-3.9a is one rule, written once, in `client_may_edit`.
"""

from __future__ import annotations

from django.db.models import Q

from apps.crm import permissions as crm_perms
from apps.tenancy.models import CLIENT_ROLES, Membership, Role


def _membership(request):
    return getattr(request, "membership", None)


def is_client(request) -> bool:
    membership = _membership(request)
    return membership is not None and membership.role in CLIENT_ROLES


def _company_scope(request, queryset, company_field="client_company_id"):
    role = crm_perms.role_of(request)
    membership = _membership(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        return queryset.filter(
            Q(**{f"{company_field}__in": crm_perms.assigned_company_ids(request)})
            | Q(owner_id=membership.user_id)
        )
    if role in CLIENT_ROLES:
        return queryset.filter(**{company_field: membership.client_company_id})
    return queryset.none()


def goal_queryset_for(request, queryset):
    return _company_scope(request, queryset)


def project_queryset_for(request, queryset):
    return _company_scope(request, queryset)


def task_queryset_for(request, queryset):
    """A task reaches a CF by four paths, not one: the company is assigned, the
    contact it hangs off is theirs (Phase 1 stage-rule tasks), they own it, or
    it is assigned to them. The last two hold regardless of company — matrix
    7.1's `own-work`."""
    role = crm_perms.role_of(request)
    membership = _membership(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        from apps.crm.models import Contact

        visible_contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.all()
        ).values("pk")
        return queryset.filter(
            Q(client_company_id__in=crm_perms.assigned_company_ids(request))
            | Q(contact_id__in=visible_contacts)
            | Q(owner_id=membership.user_id)
            | Q(assignee_id=membership.user_id)
        )
    if role in CLIENT_ROLES:
        # FR-3.13 — own company, client-visible only.
        return queryset.filter(client_company_id=membership.client_company_id,
                               is_client_visible=True)
    return queryset.none()


def comment_queryset_for(request, queryset):
    """AC-3.4 — an internal comment must be ABSENT from a client's response,
    not merely hidden in the UI."""
    from apps.work.models import Comment

    if is_client(request):
        return queryset.filter(visibility=Comment.Visibility.SHARED)
    return queryset


def is_client_side_user(tenant_id, user_id, company_id) -> bool:
    if user_id is None:
        return False
    return Membership.all_objects.filter(
        tenant_id=tenant_id, user_id=user_id, role__in=CLIENT_ROLES,
        client_company_id=company_id, revoked_at__isnull=True,
    ).exists()


def client_may_edit(request, task) -> bool:
    """FR-3.9a, the whole rule:

    > A client user may edit, change the status of, and reassign any task that
    > is client-visible, in their own company, and either assigned to a
    > client-side user or created by a client user.

    So a task assigned to a fractional is read-only to the client apart from
    shared comments: if the fractional owns the work, the client asks.
    """
    membership = _membership(request)
    if membership is None or membership.role not in CLIENT_ROLES:
        return False
    if not task.is_client_visible or task.client_company_id != membership.client_company_id:
        return False
    if task.created_by_client:
        return True
    return is_client_side_user(task.tenant_id, task.assignee_id,
                               membership.client_company_id)


def client_may_delete(request, task) -> bool:
    """FR-3.9a.3 — narrower than editing: only tasks they created themselves.
    Deleting work a fractional assigned is not a client's call."""
    from apps.work.services import creator_of

    membership = _membership(request)
    if not client_may_edit(request, task) or not task.created_by_client:
        return False
    creator = creator_of(task)
    return creator is not None and creator.pk == membership.user_id


def client_may_assign_to(request, user_id) -> bool:
    """FR-3.9a.2 — a client hands work to a colleague, never to a fractional
    and never outside the company."""
    membership = _membership(request)
    if user_id is None:
        return True
    return is_client_side_user(membership.tenant_id, user_id,
                               membership.client_company_id)


def may_write(request, task) -> bool:
    """Tenant staff by role scope; client users by FR-3.9a."""
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.CF, Role.VA):
        return True
    return client_may_edit(request, task)


# ------------------------------------------------ Module 4B — the value report
#
# Matrix §10A draws one line: **judging the client relationship is
# FF-and-assigned-CF; administering it is a VA's too.** Recording a reading and
# exporting a PDF are administration. Resolving a goal, accepting a narrative
# and writing the outcome statement are judgements — a VA who could do them
# could publish a verdict on the engagement that the fractional never reached.

def may_judge(request, company_id) -> bool:
    """Matrix 10A.6, 10A.10, 10A.13 — FF, or a CF assigned to that company."""
    role = crm_perms.role_of(request)
    if role == Role.FF:
        return True
    if role == Role.CF:
        return company_id is not None and company_id in set(
            crm_perms.assigned_company_ids(request))
    return False


def may_administer(request) -> bool:
    """Matrix 10A.4, 10A.7, 10A.15 — any tenant role, never a client. Scope is
    the queryset's job; this is only about the verb."""
    return crm_perms.role_of(request) in (Role.FF, Role.CF, Role.VA)
