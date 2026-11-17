"""Two-factor sign-in by authenticator app (2026-11-17, `docs/p9_people_hris.md`).

- **Anyone may turn it on** under Profile: a QR code and the same key to type,
  confirmed with a code from the app; then ten single-use backup codes, shown
  once and replaceable. No text messages.
- **After any sign-in** (Google, Microsoft, an emailed link), a person who has
  it on is asked for a code before anything else answers
  (`middleware.TwoFactorGate`). A backup code works there too, once.
- **Required for anyone holding an HR permission**: they enroll before any
  People screen opens, and can't turn it off while they hold one.
- **People screens ask again** when this session's last code is more than
  four hours old (`recheck_due`).
- **A lost phone**: a practice owner resets it for their team and their
  clients' users, a client owner for their own people, the platform owner
  for a practice owner. Each reset is logged and the person told by email.
- **Codes are rate limited**: five tries in five minutes per person (the
  enrolling one included), and twenty per address.
- **The demo** lets visitors set it up and try it, and never asks for it: no
  sign-in, People screen or re-check waits on a code there (`waived`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts import totp
from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared

#: When this session's last code was entered (seconds since the epoch).
SESSION_VERIFIED = "two_factor_at"
#: People screens ask again after this.
RECHECK_SECONDS = 4 * 60 * 60
BACKUP_COUNT = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"          # no 0/o, 1/l/i
PER_PERSON = RateLimit(limit=5, window_seconds=300, prefix="2fa-person")
PER_ADDRESS = RateLimit(limit=20, window_seconds=300, prefix="2fa-address")

TOO_MANY = "Too many codes tried. Wait five minutes and try again."
WRONG = "That code is not right. Enter the six digits your authenticator app shows now."


class TwoFactorRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- reading

def device(user):
    """The person's confirmed authenticator, or None."""
    from apps.accounts.models import TwoFactor

    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).first()


def enabled(user) -> bool:
    return device(user) is not None


def waived() -> bool:
    """The demo: set up and tried, never asked for."""
    return bool(getattr(settings, "IS_DEMO", False))


def required(user) -> bool:
    """Holds an HR permission in a practice that has People on."""
    from apps.people import access

    return access.holds_hr_permission(user)


def verified_at(request) -> float | None:
    value = request.session.get(SESSION_VERIFIED)
    return float(value) if value else None


def pending(request) -> bool:
    """Signed in, with two-factor on, and no code entered in this session."""
    if waived():
        return False
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and enabled(user)
                and verified_at(request) is None)


def recheck_due(request) -> bool:
    """A People screen asks again: the last code is over four hours old."""
    if waived() or not enabled(request.user):
        return False
    last = verified_at(request)
    return last is None or time.time() - last > RECHECK_SECONDS


def state(request) -> dict:
    from apps.accounts.models import BackupCode

    user = request.user
    found = device(user)
    return {
        "enabled": found is not None,
        "since": found.confirmed_at.isoformat() if found else None,
        "backup_codes_left": BackupCode.objects.filter(user=user, used_at__isnull=True).count()
        if found else 0,
        "required": required(user),
        "demo": waived(),
    }


# ---------------------------------------------------------- the person's acts

def _hash(code: str) -> str:
    plain = "".join(ch for ch in str(code or "").lower() if ch.isalnum())
    return hmac.new(settings.SECRET_KEY.encode(), plain.encode(), hashlib.sha256).hexdigest()


def _limited(request, user) -> None:
    if too_many_shared(PER_PERSON, str(user.pk)) or \
            too_many_shared(PER_ADDRESS, client_ip(request) or ""):
        raise TwoFactorRefused(TOO_MANY, 429)


def start(user) -> dict:
    """Begin enrolling: a new key, as a QR code and as text to type."""
    from apps.accounts.models import TwoFactor
    from apps.crm.services.secrets import encrypt
    from config.branding import PRODUCT_NAME

    if enabled(user):
        raise TwoFactorRefused("Two-factor sign-in is already on.", 409)
    secret = totp.new_secret()
    TwoFactor.objects.filter(user=user).delete()
    TwoFactor.objects.create(user=user, secret_ciphertext=encrypt(secret))
    uri = totp.provisioning_uri(secret, account=user.email, issuer=PRODUCT_NAME)
    return {"key": totp.grouped(secret), "uri": uri, "qr_svg": totp.qr_svg(uri)}


def _secret(row) -> str:
    from apps.crm.services.secrets import decrypt

    return decrypt(bytes(row.secret_ciphertext))


def new_backup_codes(user) -> list[str]:
    """Ten new codes, the old ones gone. Shown once: only hashes are kept."""
    from apps.accounts.models import BackupCode

    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(8)) for _ in range(BACKUP_COUNT)]
    codes = [f"{c[:4]}-{c[4:]}" for c in codes]
    with transaction.atomic():
        BackupCode.objects.filter(user=user).delete()
        BackupCode.objects.bulk_create([BackupCode(user=user, code_hash=_hash(c))
                                        for c in codes])
    return codes


def _check(user, code, *, backup: bool) -> str:
    """"totp" or "backup" for a right code (a backup code then spent); ""."""
    from apps.accounts.models import BackupCode, TwoFactor

    row = TwoFactor.objects.select_for_update().filter(user=user).first()
    if row is None:
        return ""
    step = totp.matching_step(_secret(row), code, after=row.last_step)
    if step is not None:
        row.last_step = step
        row.save(update_fields=["last_step", "updated_at"])
        return "totp"
    if backup and row.confirmed_at is not None:
        spent = BackupCode.objects.filter(user=user, code_hash=_hash(code),
                                          used_at__isnull=True).update(used_at=timezone.now())
        if spent:
            return "backup"
    return ""


def _mark(request) -> None:
    if request is not None:
        request.session[SESSION_VERIFIED] = time.time()


def confirm(user, code, *, request=None) -> list[str]:
    """Finish enrolling with a code from the app: on, and ten backup codes.
    The try is counted first, outside the transaction, so a refused code
    still counts against the limit."""
    from apps.accounts.models import TwoFactor

    if request is not None:
        _limited(request, user)
    with transaction.atomic():
        row = TwoFactor.objects.select_for_update().filter(user=user).first()
        if row is None:
            raise TwoFactorRefused("Start setting it up first.", 409)
        if row.confirmed_at is not None:
            raise TwoFactorRefused("Two-factor sign-in is already on.", 409)
        if _check(user, code, backup=False) != "totp":
            raise TwoFactorRefused(WRONG)
        TwoFactor.objects.filter(pk=row.pk).update(confirmed_at=timezone.now())
        _mark(request)
        _audit(user, "two_factor.enabled", actor=user)
        return new_backup_codes(user)


def verify(request, code) -> str:
    """A code at sign-in or on a People screen: this session is verified.
    Returns "totp" or "backup". Counted first, outside the transaction."""
    user = request.user
    _limited(request, user)
    if not enabled(user):
        raise TwoFactorRefused("Two-factor sign-in is not on.", 409)
    with transaction.atomic():
        kind = _check(user, code, backup=True)
    if not kind:
        raise TwoFactorRefused(WRONG)
    _mark(request)
    if kind == "backup":
        _audit(user, "two_factor.backup_code_used", actor=user)
    return kind


def replace_backup_codes(request, code) -> list[str]:
    verify(request, code)
    _audit(request.user, "two_factor.backup_codes_replaced", actor=request.user)
    return new_backup_codes(request.user)


def turn_off(request, code) -> None:
    from apps.accounts.models import BackupCode, TwoFactor

    if required(request.user):
        raise TwoFactorRefused("Two-factor sign-in is required while you hold an HR "
                               "permission.", 409)
    verify(request, code)
    TwoFactor.objects.filter(user=request.user).delete()
    BackupCode.objects.filter(user=request.user).delete()
    request.session.pop(SESSION_VERIFIED, None)
    _audit(request.user, "two_factor.disabled", actor=request.user)


# ------------------------------------------------------------- resets

def may_reset(actor_membership, target_membership) -> bool:
    """A practice owner: their own team and their clients' users. A client
    owner: their own company's people. Never someone else's practice."""
    from apps.tenancy.models import CLIENT_ROLES, Role

    if actor_membership is None or target_membership is None:
        return False
    if target_membership.tenant_id != actor_membership.tenant_id:
        return False
    if target_membership.user_id == actor_membership.user_id:
        return False
    if actor_membership.role == Role.FF:
        return True
    if actor_membership.role == Role.FCC:
        return (target_membership.role in CLIENT_ROLES
                and target_membership.client_company_id == actor_membership.client_company_id)
    return False


@transaction.atomic
def reset(target_user, *, actor, tenant=None, by_platform=False) -> None:
    """Two-factor off for someone who lost their phone: logged, and the
    person told by email. They set it up again under Profile."""
    from apps.accounts.models import BackupCode, TwoFactor

    if not TwoFactor.objects.filter(user=target_user).exists():
        raise TwoFactorRefused(f"{target_user.full_name or target_user.email} has no "
                               "two-factor sign-in to reset.", 404)
    TwoFactor.objects.filter(user=target_user).delete()
    BackupCode.objects.filter(user=target_user).delete()
    who = actor.full_name or actor.email
    _audit(target_user, "two_factor.reset", actor=actor, tenant=tenant,
           by=who, platform=by_platform)
    transaction.on_commit(lambda: _tell_reset(target_user, who, tenant, by_platform))


def _tell_reset(user, who, tenant, by_platform) -> None:
    import logging

    from apps.crm.models import OutboxMessage
    from config.branding import PRODUCT_NAME

    lines = [f"{who} reset two-factor sign-in on your {PRODUCT_NAME} account.",
             "Next time you sign in, no code is asked for. Set it up again under Profile "
             "with your authenticator app. If you did not ask for this, tell "
             f"{who} at once."]
    subject = "Your two-factor sign-in was reset"
    try:
        if by_platform or tenant is None:
            from apps.platform.mail import send_platform_mail

            send_platform_mail(to=user.email, subject=subject, paragraphs=lines,
                               producer=OutboxMessage.Producer.MAGIC_LINK)
            return
        from apps.crm.services import email_layout, outbox
        from apps.tenancy.context import tenant_context

        with tenant_context(tenant.pk):
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.MAGIC_LINK,
                to_address=user.email, subject=subject, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    tenant, subject=subject, preheader=lines[0],
                    content_html="".join(f"<p>{line}</p>" for line in lines)),
                force_direct=True)
    except Exception as exc:  # noqa: BLE001 — the reset stands; the log says so
        logging.getLogger(__name__).warning("two-factor reset notice for %s not sent (%s)",
                                            user.pk, type(exc).__name__)


def _audit(user, verb, *, actor, tenant=None, **payload) -> None:
    """In the practice it happened in: the one given, or the person's own."""
    from apps.tenancy.models import AuditEvent, Membership

    if tenant is None:
        membership = (Membership.all_objects.filter(user=user, revoked_at__isnull=True)
                      .order_by("created_at").first())
        tenant_id = membership.tenant_id if membership else None
    else:
        tenant_id = tenant.pk
    if tenant_id is None:
        return
    AuditEvent.all_objects.create(tenant_id=tenant_id, actor=actor, verb=verb,
                                  target_type="user", target_id=user.pk,
                                  payload={"email": user.email, **payload})
