"""Authenticator-app codes (RFC 6238, TOTP), for two-factor sign-in (2026-11-17).

Six digits, a 30-second step, HMAC-SHA1: what every authenticator app (Google
Authenticator, Microsoft Authenticator, 1Password, Authy …) shows for a key
scanned from a QR code or typed in. A code is accepted for the step it was
made in and one step either side (a minute and a half in all), and never
twice: the step a code was used in is kept, and an earlier or equal one is
refused. No text messages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP = 30
DIGITS = 6
#: Steps either side of now that are still accepted (clock drift).
WINDOW = 1


def new_secret() -> str:
    """A fresh key: 160 random bits, in base32 without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    clean = secret.replace(" ", "").upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def step_of(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def code_at(secret: str, step: int) -> str:
    """The code for one step (RFC 4226's HOTP on the step number)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** DIGITS)).zfill(DIGITS)


def code_now(secret: str, now: float | None = None) -> str:
    return code_at(secret, step_of(now))


def matching_step(secret: str, code: str, *, after: int | None = None,
                  now: float | None = None) -> int | None:
    """The step a typed code belongs to, within the window and later than
    `after` (the step last used); None if it matches none."""
    typed = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(typed) != DIGITS:
        return None
    current = step_of(now)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if after is not None and step <= after:
            continue
        if hmac.compare_digest(code_at(secret, step), typed):
            return step
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """What the QR code holds (the Key URI format authenticator apps read)."""
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                       "digits": DIGITS, "period": STEP})
    return f"otpauth://totp/{label}?{query}"


def grouped(secret: str) -> str:
    """The key as typed into an app: groups of four."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def qr_svg(uri: str) -> str:
    """The QR code, as an SVG drawing (no file, no network)."""
    import io

    import segno

    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=5, border=2, xmldecl=False,
                                    svgns=True, title="Scan this with your authenticator app")
    return out.getvalue().decode()
