"""Read and write encrypted tenant secrets (assumption E1).

The Fernet key lives in the environment, never in the database, so a dump —
including the nightly GCS backup — contains no usable credential.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _cipher():
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. Stored credentials cannot be read."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return _cipher().encrypt(value.encode())


def write_secret(*, tenant, kind, value, user=None):
    from apps.tenancy.models import TenantSecret

    secret, _ = TenantSecret.all_objects.update_or_create(
        tenant=tenant, kind=kind, user=user,
        defaults={"ciphertext": encrypt(value), "last4": value[-4:]},
    )
    return secret


def read_secret(secret) -> str:
    """Returns '' rather than raising on a secret encrypted under a lost key —
    the caller turns that into a 'reconnect' message, which is the useful
    outcome."""
    if secret is None:
        return ""
    try:
        raw = bytes(secret.ciphertext)
        return _cipher().decrypt(raw).decode()
    except (InvalidToken, ValueError, TypeError):
        return ""
