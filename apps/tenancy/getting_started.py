"""Getting started (P2, §5): the practice owner's checklist, computed from the
practice's own data on every request. Nothing is stored, so an item can never
claim something that is not true, and an item undone (a disconnected Gmail)
shows as open again.

The one thing kept is a person's own choice to put the dashboard's card away
(owner, 2026-10-10): for today, or for good. That hides the card and nothing
else. Whatever is still undone is listed at the top of Settings until it is
done, whatever was dismissed."""

from __future__ import annotations


def items(tenant) -> list[dict]:
    from apps.tenancy.demo import visitors

    t = tenant.pk
    # A demo visitor's copy connects no Gmail and takes no key (2026-10-17).
    skip = {"gmail", "anthropic"} if visitors.is_copy(tenant) else set()
    return [item for item in _all(tenant, t) if item["key"] not in skip]


def _all(tenant, t) -> list[dict]:
    from apps.crm.models import Company, Contact, GmailConnection, ImportBatch
    from apps.strategy.models import StrategyTemplate
    from apps.tenancy import words
    from apps.tenancy.models import Membership, TenantSecret

    return [
        {"key": "branding", "label": "Set your branding", "to": "/settings/branding",
         "done": tenant.branding_updated_at is not None},
        # W2 (2026-10-15): Branding's Wording section; done once any of the four words is not the default.
        {"key": "words", "label": "Choose your wording for goals, projects, tasks and steps",
         "to": "/settings/branding#wording", "done": words.of(tenant) != words.DEFAULT},
        {"key": "gmail", "label": "Choose your practice address and connect Gmail",
         "to": "/settings/email",
         "done": GmailConnection.all_objects.filter(
             tenant_id=t, send_as_verified_at__isnull=False).exists()},
        {"key": "anthropic", "label": "Add your Anthropic key", "to": "/ai-usage",
         "done": TenantSecret.all_objects.filter(tenant_id=t,
                                                 kind="anthropic_api_key").exists()},
        # D5: a committed import, or any contact at all.
        {"key": "contacts", "label": "Import your contacts", "to": "/import",
         "done": ImportBatch.all_objects.filter(tenant_id=t, status="committed").exists()
         or Contact.all_objects.filter(tenant_id=t).exists()},
        {"key": "staff", "label": "Invite your team", "to": "/staff",
         "done": Membership.all_objects.filter(tenant_id=t, role__in=("CF", "VA"),
                                               revoked_at__isnull=True).exists()},
        {"key": "client", "label": "Add your first client", "to": "/companies",
         "done": Company.all_objects.filter(tenant_id=t, is_client_company=True).exists()},
        {"key": "template", "label": "Build your first strategy template",
         "to": "/strategy/template",
         "done": StrategyTemplate.all_objects.filter(tenant_id=t).exists()},
    ]


def _today(tenant):
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    return timezone.localdate(timezone=ZoneInfo(tenant.timezone))


def card(tenant, user) -> dict:
    """Whether this person's dashboard shows the card, and why not."""
    from apps.tenancy.models import GettingStartedDismissal

    row = GettingStartedDismissal.all_objects.filter(tenant=tenant, user=user).first()
    later = bool(row and row.hidden_until and row.hidden_until >= _today(tenant))
    never = bool(row and row.never)
    return {"hidden": later or never, "never": never,
            "hidden_until": row.hidden_until.isoformat() if later else None}


def dismiss(tenant, user, how: str) -> dict:
    """`later`: hidden for the rest of today, back tomorrow. `never`: not
    shown again. `show`: back now."""
    from apps.tenancy.models import GettingStartedDismissal

    if how not in ("later", "never", "show"):
        raise ValueError("how is later, never or show.")
    row, _ = GettingStartedDismissal.all_objects.get_or_create(tenant=tenant, user=user)
    if how == "later":
        row.hidden_until = _today(tenant)
    elif how == "never":
        row.never = True
    else:
        row.hidden_until, row.never = None, False
    row.save()
    return card(tenant, user)
