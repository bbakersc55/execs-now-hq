"""The sensitive values: the tax id, every access code, the Wi-Fi password.

Encrypted at rest with the environment's key (`crm.services.secrets`). On
screen: the tax id shows its last four; a code or the Wi-Fi password shows no
character at all unless a reviewer reveals it, and every reveal is recorded
(who, which, when). The owner's link never shows any of them again once saved.
Deleted the moment Track confirms it holds one, last four included; for a
submission never sent, 90 days after its last change, or at once on discard.
"""

from __future__ import annotations

import re

from django.utils import timezone

from apps.crm.services import secrets as cipher

from .models import SECRET_LIFETIME, Submission, SubmissionEvent, SubmissionSecret

Kind = SubmissionSecret.Kind


class Refused(ValueError):
    """A value this form won't keep, said for the person typing it."""


_SSN_SHAPE = re.compile(r"^\d{3}-\d{2}-\d{4}$")


def normalise(kind: str, value: str) -> str:
    value = (value or "").strip()
    if kind == Kind.TAX_ID:
        if _SSN_SHAPE.match(value):
            raise Refused("That looks like a Social Security number. Please don't enter it "
                          "here: you'll add it yourself in your owner portal.")
        digits = re.sub(r"\D", "", value)
        if len(digits) != 9:
            raise Refused("A business Tax ID (EIN) has 9 digits, like 12-3456789.")
        return f"{digits[:2]}-{digits[2:]}"
    if not value:
        raise Refused("Enter a value, or leave it out.")
    if kind == Kind.CODE and len(value) > 40:
        raise Refused("A code can be up to 40 characters.")
    if kind == Kind.WIFI_PASSWORD and len(value) > 120:
        raise Refused("A Wi-Fi password can be up to 120 characters.")
    return value


def put(submission: Submission, kind: str, slot: str, value: str) -> SubmissionSecret:
    if kind not in Kind.values:
        raise Refused("Unknown kind of value.")
    value = normalise(kind, value)
    row, _ = SubmissionSecret.all_objects.update_or_create(
        submission=submission, kind=kind, slot=slot or "",
        defaults={"tenant_id": submission.tenant_id, "ciphertext": cipher.encrypt(value),
                  "last4": value[-4:] if kind == Kind.TAX_ID else ""})
    return row


def clear(submission, kind, slot=""):
    SubmissionSecret.all_objects.filter(submission=submission, kind=kind, slot=slot or "").delete()


def masked(submission) -> dict:
    """What a screen may show: whether each is set; the tax id's last four."""
    out = {"tax_id": None, "wifi_password": False, "codes": {}}
    for row in SubmissionSecret.all_objects.filter(submission=submission):
        if row.kind == Kind.TAX_ID:
            out["tax_id"] = {"last4": row.last4}
        elif row.kind == Kind.WIFI_PASSWORD:
            out["wifi_password"] = True
        else:
            out["codes"][row.slot] = True
    return out


def held_names(submission) -> set[str]:
    """What is held, by name: "tax_id", "wifi_password", "code:<slot>"."""
    out = set()
    for kind, slot in SubmissionSecret.all_objects.filter(submission=submission) \
            .values_list("kind", "slot"):
        out.add(f"code:{slot}" if kind == Kind.CODE else kind)
    return out


def _row(submission, name):
    """The row for "tax_id", "wifi_password" or "code:<slot>"."""
    kind, _, slot = name.partition(":")
    if kind not in Kind.values:
        return None
    return SubmissionSecret.all_objects.filter(submission=submission, kind=kind,
                                               slot=slot).first()


def value(submission, name):
    """The plain value, for the moment it is sent; None if not held."""
    row = _row(submission, name)
    return cipher.decrypt(row.ciphertext) or None if row else None


def describe(name: str) -> str:
    kind, _, slot = name.partition(":")
    if kind == Kind.TAX_ID:
        return "the Tax ID"
    if kind == Kind.WIFI_PASSWORD:
        return "the Wi-Fi password"
    return f"the {slot.replace('_', ' ').replace('-', ' ')} code"


def reveal(submission, name, actor):
    """The plain value for a reviewer, recorded as revealed by them, now."""
    found = value(submission, name)
    if found is None:
        return None
    SubmissionEvent.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                       kind=SubmissionEvent.Kind.REVEALED, actor=actor,
                                       detail=f"Revealed {describe(name)}")
    return found


def confirmed(submission, name):
    """Track holds it now: ENHQ keeps nothing of it."""
    row = _row(submission, name)
    if row is not None:
        row.delete()
        SubmissionEvent.all_objects.create(
            tenant_id=submission.tenant_id, submission=submission,
            kind=SubmissionEvent.Kind.SECRETS_DELETED,
            detail=f"Deleted {describe(name)}: Track confirmed it has it")


def delete_all(submission, why: str):
    count, _ = SubmissionSecret.all_objects.filter(submission=submission).delete()
    if count:
        SubmissionEvent.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                           kind=SubmissionEvent.Kind.SECRETS_DELETED,
                                           detail=f"Deleted {count} sensitive value(s): {why}")
    return count


def purge_stale(tenant_id) -> int:
    """Secrets of submissions never sent, 90 days after their last change."""
    cutoff = timezone.now() - SECRET_LIFETIME
    stale = Submission.all_objects.filter(
        tenant_id=tenant_id, last_changed_at__lt=cutoff,
        secrets__isnull=False).exclude(status=Submission.Status.SENT).distinct()
    return sum(delete_all(s, "90 days after the last change, never sent") for s in stale)
