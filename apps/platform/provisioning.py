"""Creating and archiving a practice (P2, owner 2026-10-02).

`provision_practice` gives a new practice its structure and none of anybody
else's data: default pipelines and stages, digests held, no stage rules, no
strategy template, the AI budget and cap the owner chose, P1's neutral brand,
and never Executives Now's addresses.
"""

from __future__ import annotations

import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

#: Owner, 2026-10-02.
DEFAULT_AI_MONTHLY_BUDGET_USD = Decimal("50.00")
DEFAULT_AI_DAILY_CAP_USD = Decimal("5.00")
#: Practices on this domain sign in through the Internal Workspace client;
#: every other domain through the External one (P2 D1).
INTERNAL_DOMAIN = "getexecutivesnow.com"

_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ProvisioningRefused(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def provision_practice(*, legal_name: str, display_name: str, domain: str,
                       owner_email: str, actor):
    """One transaction: the practice, its structure, its owner. The invitation
    email is sent separately, after commit, and only when asked."""
    from apps.accounts.models import User
    from apps.crm.seed import seed_tenant
    from apps.tenancy.models import AuditEvent, Membership, Role, Tenant
    from apps.tenancy.management.commands.ensure_schedules import ensure_for

    legal_name, display_name = legal_name.strip(), display_name.strip()
    domain = domain.strip().lower().removeprefix("www.")
    owner_email = owner_email.strip().lower()
    errors = {}
    if not legal_name:
        errors["legal_name"] = "Give the practice's legal name."
    if not display_name:
        errors["display_name"] = "Give the name clients will see."
    elif len(display_name) > 80:
        errors["display_name"] = "The display name is at most 80 characters."
    if not _DOMAIN.match(domain):
        errors["domain"] = "Give the practice's domain, like blueskybizconsulting.com."
    if not _EMAIL.match(owner_email):
        errors["owner_email"] = "Give the practice owner's email address."
    else:
        existing = Membership.all_objects.filter(user__email__iexact=owner_email,
                                                 revoked_at__isnull=True).first()
        if existing is not None:
            # One membership per user in Beta (B4).
            errors["owner_email"] = "That address already belongs to a practice."
    if errors:
        raise ProvisioningRefused(errors)

    with transaction.atomic():
        tenant = Tenant.objects.create(
            name=display_name, legal_name=legal_name, email_display_name=display_name,
            domain=domain, slug=_unique_slug(display_name), status=Tenant.Status.INVITED,
            created_by=actor,
            oauth_client=(Tenant.OAuthClient.INTERNAL if domain == INTERNAL_DOMAIN
                          else Tenant.OAuthClient.EXTERNAL),
            hold_all_digests=True,
            ai_monthly_budget_usd=DEFAULT_AI_MONTHLY_BUDGET_USD,
            ai_unattended_daily_cap_usd=DEFAULT_AI_DAILY_CAP_USD,
            # Never Executives Now's addresses (they are the column defaults).
            from_address=f"info@{domain}", inbound_domain="",
        )
        seed_tenant(tenant)
        user = User.objects.filter(email__iexact=owner_email).first() \
            or User.objects.create_user(email=owner_email)
        Membership.all_objects.create(tenant=tenant, user=user, role=Role.FF,
                                      invited_by=actor, invited_at=timezone.now())
        AuditEvent.all_objects.create(
            tenant=tenant, actor=actor, verb="practice.created",
            target_type="tenant", target_id=tenant.pk,
            payload={"display_name": display_name, "domain": domain,
                     "owner_email": owner_email, "by": "platform owner"})
        ensure_for(tenant)
    return tenant


def archive(tenant, *, actor) -> None:
    """Nobody signs in, nothing runs or sends, every row is kept (P2 D4)."""
    from apps.tenancy.management.commands.ensure_schedules import remove_for
    from apps.tenancy.models import AuditEvent, Tenant

    with transaction.atomic():
        tenant.status, tenant.archived_at = Tenant.Status.ARCHIVED, timezone.now()
        tenant.save(update_fields=["status", "archived_at", "updated_at"])
        remove_for(tenant)
        AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb="practice.archived",
                                      target_type="tenant", target_id=tenant.pk, payload={})


def unarchive(tenant, *, actor) -> None:
    from apps.tenancy.management.commands.ensure_schedules import ensure_for
    from apps.tenancy.models import AuditEvent, Membership, Tenant

    with transaction.atomic():
        signed_in = Membership.all_objects.filter(
            tenant=tenant, role="FF", user__last_login__isnull=False).exists() or \
            Membership.all_objects.filter(tenant=tenant, role="FF",
                                          user__last_login_at__isnull=False).exists()
        tenant.status = Tenant.Status.ACTIVE if signed_in else Tenant.Status.INVITED
        tenant.archived_at = None
        tenant.save(update_fields=["status", "archived_at", "updated_at"])
        ensure_for(tenant)
        AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb="practice.unarchived",
                                      target_type="tenant", target_id=tenant.pk, payload={})


def update_identity(tenant, *, legal_name=None, display_name=None, domain=None) -> None:
    """The platform's own record of a practice: its names and domain."""
    errors = {}
    if legal_name is not None:
        tenant.legal_name = legal_name.strip()
    if display_name is not None:
        if not display_name.strip() or len(display_name.strip()) > 80:
            errors["display_name"] = "Give a display name of at most 80 characters."
        else:
            tenant.email_display_name = display_name.strip()
    if domain is not None:
        domain = domain.strip().lower().removeprefix("www.")
        if domain and not _DOMAIN.match(domain):
            errors["domain"] = "Give the practice's domain, like blueskybizconsulting.com."
        tenant.domain = domain
    if errors:
        raise ProvisioningRefused(errors)
    tenant.save()


def _unique_slug(name: str) -> str:
    from apps.tenancy.models import Tenant

    base = slugify(name)[:40] or "practice"
    slug, n = base, 2
    while Tenant.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug
