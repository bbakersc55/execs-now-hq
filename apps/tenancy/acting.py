"""Acting as another user — FR-3.42, matrix 9.6–9.10.

Who may act as whom is one function, `refusal`, used when a session starts and
again on every request while it lasts. The request side lives in
TenantMiddleware; this module holds the rule, the session key, and the two
save-time receivers that make attribution and email suppression impossible to
forget on any write path.

- (a) An FF, or a CF on a company they are assigned, may act as any live
  client user at a client company — exactly the companies they may grant
  portal access to (FR-3.33c).
- (b) An FCC may act as any other live user in their own company.
- Nobody else, never across a company or tenant, never as tenant staff, never
  as themselves, and never nested.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .context import get_acting

SESSION_KEY = "act_as_membership"
STAMPED = {"tenancy.AuditEvent", "work.TaskUpdate", "work.Comment"}
NOT_FOUND = (404, "Not found.")


def refusal(real, target):
    """None when `real` may act as `target`; otherwise `(status, detail)`.

    Out of scope is 404, role-forbidden is 403 (matrix §1).
    """
    from .models import CLIENT_ROLES, ClientAssignment, Role

    if real is None or real.revoked_at is not None or \
            real.role not in (Role.FF, Role.CF, Role.FCC):
        return 403, "Acting as someone else is not available to you."
    if target is None or target.tenant_id != real.tenant_id or target.pk == real.pk \
            or target.revoked_at is not None or target.role not in CLIENT_ROLES:
        return NOT_FOUND
    if real.role == Role.FCC:
        if target.client_company_id != real.client_company_id:
            return NOT_FOUND
        return None
    company = target.client_company
    if company is None or not company.is_client_company or company.deleted_at is not None:
        return NOT_FOUND
    if real.role == Role.CF and not ClientAssignment.all_objects.filter(
            tenant_id=real.tenant_id, user_id=real.user_id, company_id=company.pk,
            removed_at__isnull=True).exists():
        return NOT_FOUND
    return None


def load_target(tenant_id, membership_id):
    from .models import Membership

    try:
        uuid.UUID(str(membership_id))
    except (TypeError, ValueError):
        return None
    return (Membership.all_objects.select_related("user", "client_company")
            .filter(tenant_id=tenant_id, pk=membership_id).first())


def resolve(request, real):
    """The membership this request acts as, or None.

    A session whose target is no longer permitted — revoked, reassigned, a
    company no longer a client — is ended here and audited, so acting never
    outlives the permission it started with.
    """
    from .models import AuditEvent

    session = getattr(request, "session", None)
    target_id = session.get(SESSION_KEY) if session is not None else None
    if not target_id:
        return None
    target = load_target(real.tenant_id, target_id)
    if refusal(real, target) is None:
        return target
    session.pop(SESSION_KEY, None)
    AuditEvent.all_objects.create(
        tenant_id=real.tenant_id, actor_id=real.user_id, verb="act_as.ended",
        target_type="membership", target_id=target.pk if target else None,
        payload={"reason": "no longer permitted", "acting_role": real.role},
    )
    return None


def describe(real_user, real_role, target) -> dict:
    return {
        "real_name": real_user.full_name or real_user.email,
        "real_email": real_user.email,
        "real_role": real_role,
        "as_membership": str(target.pk),
        "as_name": target.user.full_name or target.user.email,
        "as_email": target.user.email,
        "as_role": target.role,
        "company": str(target.client_company_id),
        "company_name": target.client_company.name if target.client_company else "",
    }


# ----------------------------------------------------------- the receivers

@receiver(user_logged_out, dispatch_uid="tenancy.act_as_ended_on_sign_out")
def end_on_sign_out(sender, request=None, user=None, **kwargs):
    """Signing out ends acting as, and is logged like any other end (owner,
    2026-09-15). Django sends this before it flushes the session, so the
    middleware's attributes still name both people."""
    target = getattr(request, "acting_as", None)
    real = getattr(request, "real_membership", None)
    if target is None or real is None:
        return
    from .models import AuditEvent

    AuditEvent.all_objects.create(
        tenant_id=real.tenant_id, actor_id=real.user_id, verb="act_as.ended",
        target_type="membership", target_id=target.pk,
        payload={"reason": "signed out", "acting_role": real.role,
                 "acted_as": target.user.email, "acted_as_role": target.role,
                 "company": str(target.client_company_id)},
    )


@receiver(pre_save, dispatch_uid="tenancy.stamp_acting")
def stamp_acting(sender, instance, raw=False, **kwargs):
    """Every task_update, comment and audit_event written while acting as
    carries the real person and the acted-as user."""
    if raw or sender._meta.label not in STAMPED or not instance._state.adding:
        return
    acting = get_acting()
    if acting is None:
        return
    if instance.acting_user_id is None:
        instance.acting_user_id = acting[0]
    if instance.acted_as_user_id is None:
        instance.acted_as_user_id = acting[1]


@receiver(post_save, dispatch_uid="tenancy.log_suppressed_notices")
def log_suppressed_notices(sender, instance, created, raw=False, **kwargs):
    """An update written while acting never reaches a digest or a
    client-activity notice (both exclude it). Recorded as suppressed at the
    moment it is written, rather than silently skipped later."""
    if raw or not created or sender._meta.label != "work.TaskUpdate" \
            or instance.acting_user_id is None:
        return
    from .models import AuditEvent

    AuditEvent.all_objects.create(
        tenant_id=instance.tenant_id, actor_id=instance.actor_id, verb="email.suppressed",
        target_type="task_update", target_id=instance.pk,
        payload={"reason": "written while acting as",
                 "suppressed": ["digest", "client_activity_notice"]},
    )
