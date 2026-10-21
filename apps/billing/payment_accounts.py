"""A practice's own NMI account (P4 §1.2, §3.3; matrix 12.1).

The practice owner enters two keys under Settings → Billing: the private API
key, which only this server uses, and the public tokenization key, which a
pay page hands to NMI's card fields at runtime. Both are kept encrypted in
`tenant_secret` and never returned; a screen sees their last four.

**Nothing is saved that NMI has not accepted.** New keys, or a new
environment, are tested first with one authenticated read; on a refusal
nothing changes, as with the Anthropic key. That read proves the private key
only: the public key is proved the first time a card form loads with it.

The platform's own account is `gateway.platform_account()`, read from the
environment. Nothing here reads it, and it never reads a `tenant_secret`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.billing import gateway as gw
from apps.billing.models import PaymentAccount
from apps.tenancy.models import SecretKind, TenantSecret

KINDS = {"private": SecretKind.NMI_PRIVATE_KEY, "public": SecretKind.NMI_PUBLIC_KEY}


class PaymentAccountError(ValueError):
    """Shown to the practice owner as it is. Never contains a key."""


def live_allowed() -> bool:
    """Live keys belong only in production: never the laptop, never the demo."""
    return settings.APP_ENVIRONMENT == "production"


def _secrets(tenant) -> dict:
    rows = TenantSecret.all_objects.filter(tenant=tenant, user__isnull=True,
                                           kind__in=KINDS.values())
    by_kind = {row.kind: row for row in rows}
    return {name: by_kind.get(kind) for name, kind in KINDS.items()}


def _row(tenant) -> PaymentAccount | None:
    return PaymentAccount.all_objects.filter(tenant=tenant).first()


def is_ready(tenant) -> bool:
    """Both keys stored, and the last test of them passed."""
    row, secrets = _row(tenant), _secrets(tenant)
    return bool(row and row.check_ok and secrets["private"] and secrets["public"])


def practice_account(tenant) -> gw.Account:
    """The practice's account for a charge. Raises unless it is ready."""
    from apps.crm.services.secrets import read_secret

    row, secrets = _row(tenant), _secrets(tenant)
    if row is None or not secrets["private"] or not secrets["public"]:
        raise PaymentAccountError("This practice has not connected its NMI account.")
    private, public = read_secret(secrets["private"]), read_secret(secrets["public"])
    if not private or not public:
        raise PaymentAccountError("The practice's NMI keys can no longer be read. Enter them "
                                  "again under Settings → Billing.")
    return gw.Account(environment=row.environment, private_key=private, public_key=public,
                      label=str(tenant.pk))


def state(tenant) -> dict:
    row, secrets = _row(tenant), _secrets(tenant)
    return {
        "environment": row.environment if row else PaymentAccount.Environment.SANDBOX,
        "private_key_last4": secrets["private"].last4 if secrets["private"] else "",
        "public_key_last4": secrets["public"].last4 if secrets["public"] else "",
        "checked_at": row.checked_at if row else None,
        "check_ok": row.check_ok if row else None,
        "check_detail": row.check_detail if row else "",
        "ready": is_ready(tenant),
        "live_allowed": live_allowed(),
        # Whether anything reaches NMI from this server at all.
        "gateway": gw.mode(),
        "pricing_program": tenant.pricing_program,
        "pricing_program_label": tenant.get_pricing_program_display() if tenant.pricing_program
        else "",
    }


def connect(tenant, *, environment: str, private_key: str = "", public_key: str = "",
            actor) -> dict:
    """Save keys and/or an environment, only once NMI accepts them.

    A key left blank keeps the stored one, unless the environment changes:
    sandbox and live keys are different keys, so a switch needs both anew.
    """
    from apps.crm.services.secrets import read_secret, write_secret
    from apps.tenancy.models import AuditEvent

    environment = (environment or "").strip().lower()
    private_key, public_key = (private_key or "").strip(), (public_key or "").strip()
    if environment not in PaymentAccount.Environment.values:
        raise PaymentAccountError("Choose sandbox or live.")
    if environment == PaymentAccount.Environment.LIVE and not live_allowed():
        raise PaymentAccountError("Live keys are accepted only on the production app. Use "
                                  "sandbox keys here.")
    row, stored = _row(tenant), _secrets(tenant)
    switching = row is not None and row.environment != environment
    if switching and not (private_key and public_key):
        raise PaymentAccountError("Switching between sandbox and live takes both of that "
                                  "environment's keys.")
    if not private_key and not public_key and not switching and row is not None:
        raise PaymentAccountError("Enter a key to change, or use Test connection.")
    candidate_private = private_key or read_secret(stored["private"])
    candidate_public = public_key or read_secret(stored["public"])
    if not candidate_private or not candidate_public:
        raise PaymentAccountError("Enter both keys: the private API key and the public "
                                  "tokenization key.")
    if candidate_private == candidate_public:
        raise PaymentAccountError("The two keys are the same. The private API key and the "
                                  "public tokenization key are different keys in NMI.")

    account = gw.Account(environment=environment, private_key=candidate_private,
                         public_key=candidate_public, label=str(tenant.pk))
    try:
        result = gw.gateway().check_connection(account)
    except gw.GatewayError as exc:
        raise PaymentAccountError(f"{exc} Nothing was changed.") from None
    if not result.ok:
        raise PaymentAccountError(f"{result.detail} Nothing was changed.")

    with transaction.atomic():
        written = {}
        if private_key:
            written["private"] = write_secret(tenant=tenant, kind=KINDS["private"],
                                              value=private_key).last4
        if public_key:
            written["public"] = write_secret(tenant=tenant, kind=KINDS["public"],
                                             value=public_key).last4
        row, created = PaymentAccount.all_objects.get_or_create(tenant=tenant)
        row.environment = environment
        row.checked_at, row.check_ok = timezone.now(), True
        row.check_detail, row.checked_by = result.detail, actor
        row.save()
        AuditEvent.all_objects.create(
            tenant=tenant, actor=actor,
            verb="payments.account_connected" if created else "payments.account_changed",
            target_type="payment_account", target_id=row.pk,
            payload={"environment": environment,
                     **{f"{name}_key_last4": last4 for name, last4 in written.items()}})
    return state(tenant)


def retest(tenant, *, actor) -> dict:
    """Test the stored keys again and record what NMI said, pass or fail."""
    from apps.tenancy.models import AuditEvent

    row = _row(tenant)
    if row is None:
        raise PaymentAccountError("Enter the account's keys first.")
    account = practice_account(tenant)
    try:
        result = gw.gateway().check_connection(account)
    except gw.GatewayError as exc:
        result = gw.ConnectionResult(False, str(exc))
    row.checked_at, row.check_ok = timezone.now(), result.ok
    row.check_detail, row.checked_by = result.detail, actor
    row.save(update_fields=["checked_at", "check_ok", "check_detail", "checked_by",
                            "updated_at"])
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="payments.connection_tested",
        target_type="payment_account", target_id=row.pk,
        payload={"ok": result.ok, "environment": row.environment})
    return state(tenant)
