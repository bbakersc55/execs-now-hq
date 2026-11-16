"""Whether the card processor is in its own Test Mode (2026-11-16).

A merchant account can be switched into Test Mode in the processor's portal:
every sale is then simulated and approved, and no money moves, while the app
would otherwise believe it took real money. So the app asks the processor
itself (the Query API's `report_type=test_mode_status`, read-only) on Test
connection and before each sale, card save and refund, and keeps the last
answer on the account:

- **true**: what is made then is a test (`is_test`): shown with the Test pill,
  worded as a test on the pay page and in receipts, and kept out of the books,
  the totals, the cash forecast and the KPI feeds;
- **false**: as before;
- **unknown** (null): the processor did not answer or did not say. Card
  payments behave exactly as before, and Billing says the setting could not
  be read and why.

The sandbox answers true for every account (proved 2026-11-16).
`NMI_SANDBOX_IGNORE_TEST_MODE` (laptop proofs only) reads a sandbox account's
as false, so a proof can take the books path with real sandbox answers.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.billing import gateway as gw

log = logging.getLogger(__name__)

BANNER = "The card processor is in Test Mode: no money moves."
UNKNOWN = ("Couldn't read whether the card processor is in Test Mode, so card payments "
           "work as before (as if it were not).")


def read(account: gw.Account) -> tuple[bool | None, str]:
    """(True / False / None, why None). Never raises, never charges."""
    if account.environment == "sandbox" and settings.NMI_SANDBOX_IGNORE_TEST_MODE:
        return False, ""
    try:
        return bool(gw.gateway().test_mode(account)), ""
    except gw.CardPaymentsPaused:
        return None, "Real calls to the card processor are off on this server."
    except gw.GatewayError as exc:
        return None, str(exc)[:300] or "The card processor did not answer."


# --------------------------------------------------------------- a practice

def for_practice(tenant, account: gw.Account | None = None) -> bool | None:
    """Read the practice's account now, keep the answer, and return it."""
    from apps.billing import payment_accounts

    if account is None:
        try:
            account = payment_accounts.practice_account(tenant)
        except payment_accounts.PaymentAccountError as exc:
            return _keep_practice(tenant, None, str(exc))
    state, detail = read(account)
    return _keep_practice(tenant, state, detail)


def _keep_practice(tenant, state, detail) -> bool | None:
    from apps.billing.models import PaymentAccount

    PaymentAccount.all_objects.filter(tenant=tenant).update(
        gateway_test_mode=state, gateway_mode_read_at=timezone.now(),
        gateway_mode_detail=detail, updated_at=timezone.now())
    if state is None and detail:
        log.info("test mode for practice %s could not be read", tenant.pk)
    return state


def last_for_practice(tenant) -> bool | None:
    """The last answer kept, without asking again."""
    from apps.billing.models import PaymentAccount

    row = PaymentAccount.all_objects.filter(tenant=tenant).first()
    return row.gateway_test_mode if row else None


def practice_state(tenant) -> dict:
    from apps.billing.models import PaymentAccount

    row = PaymentAccount.all_objects.filter(tenant=tenant).first()
    return _state(row.gateway_test_mode if row else None,
                  row.gateway_mode_read_at if row else None,
                  row.gateway_mode_detail if row else "")


# -------------------------------------------------------------- the platform

def for_platform() -> bool | None:
    """Read the platform account now (the NMI_* keys), keep it, return it."""
    try:
        account = gw.platform_account()
    except gw.GatewayError as exc:
        return _keep_platform(None, str(exc))
    state, detail = read(account)
    return _keep_platform(state, detail)


def _keep_platform(state, detail) -> bool | None:
    from apps.billing.models import PlatformGatewayMode

    row = PlatformGatewayMode.objects.first() or PlatformGatewayMode()
    row.test_mode, row.read_at, row.detail = state, timezone.now(), detail
    row.save()
    return state


def last_for_platform() -> bool | None:
    from apps.billing.models import PlatformGatewayMode

    row = PlatformGatewayMode.objects.first()
    return row.test_mode if row else None


def platform_state() -> dict:
    from apps.billing.models import PlatformGatewayMode

    row = PlatformGatewayMode.objects.first()
    return _state(row.test_mode if row else None, row.read_at if row else None,
                  row.detail if row else "")


def _state(test_mode, read_at, detail) -> dict:
    """What a screen shows: the banner while on; why not, when unreadable."""
    return {
        "test_mode": test_mode,
        "read_at": read_at.isoformat() if read_at else None,
        "banner": BANNER if test_mode else "",
        # Only once a read was tried and failed.
        "unknown": (f"{UNKNOWN} {detail}".strip()
                    if test_mode is None and read_at is not None else ""),
    }
