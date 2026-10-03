"""The beta agreement (P2, owner 2026-10-02).

A practice owner accepts the current version before using the app; the
acceptance records the SHA-256 of the exact text shown. A new version asks
again (D3). The platform owner is exempt (their own practice).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from django.conf import settings

VERSION = "v1"
PATH = settings.BASE_DIR / "docs" / "legal" / f"beta_agreement_{VERSION}.md"


@lru_cache(maxsize=1)
def current() -> dict:
    text = PATH.read_text()
    return {"version": VERSION, "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def required(request) -> bool:
    from apps.platform.models import AgreementAcceptance

    if not settings.BETA_AGREEMENT_REQUIRED:
        return False
    membership = getattr(request, "membership", None)
    if membership is None or membership.role != "FF":
        return False
    if getattr(request, "acting_as", None) is not None:
        return False                   # the real person is staff acting as someone
    if request.user.is_platform_owner:
        return False
    return not AgreementAcceptance.all_objects.filter(
        user=request.user, version=VERSION).exists()


def accept(request, *, version: str, sha256: str) -> None:
    from apps.platform.models import AgreementAcceptance

    terms = current()
    if version != terms["version"] or sha256 != terms["sha256"]:
        raise ValueError("The agreement changed while you were reading it. Read it again.")
    AgreementAcceptance.all_objects.get_or_create(
        user=request.user, version=version,
        defaults={"tenant": request.membership.tenant, "text_sha256": sha256,
                  "ip": request.META.get("REMOTE_ADDR")})
