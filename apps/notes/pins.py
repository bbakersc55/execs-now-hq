"""Note PINs (FR-2.8–2.13). A privacy screen, not a vault.

The body is not encrypted. A PIN keeps a note off other users' screens; it
does not protect it from the FF (who can reset), a database dump, or a backup
(FR-2.13). Everything here is written so that nothing ever reveals a PIN:
it is hashed on the way in and a reset CLEARS it (FR-2.12).
"""

from __future__ import annotations

import re

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent

PIN_PATTERN = re.compile(r"^\d{4,6}$")
MAX_ATTEMPTS = 5
LOCKOUT = timezone.timedelta(minutes=15)
UNLOCK_FOR = timezone.timedelta(minutes=30)


class PinError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _audit(note, actor, verb, **payload):
    AuditEvent.all_objects.create(
        tenant=note.tenant, actor=actor, verb=verb,
        target_type="note", target_id=note.pk, payload=payload,
    )


def _grant_unlock(note, request):
    from apps.notes.models import NotePinUnlock

    if not request.session.session_key:
        request.session.save()
    now = timezone.now()
    NotePinUnlock.all_objects.create(
        tenant=note.tenant, note=note, user=request.user,
        session_key=request.session.session_key,
        unlocked_at=now, expires_at=now + UNLOCK_FOR,
    )


@transaction.atomic
def set_pin(note, pin, *, request, unlocked: bool):
    """Set or change. Changing needs the note unlocked in this session:
    otherwise anyone who can see the stub could re-PIN a note and shut its
    author out.

    FR-2.11a (a typed title first) is enforced by the dialog, not here — AC-2.3
    requires the API path to succeed, and FR-2.11b is what keeps it safe.
    """
    if not PIN_PATTERN.match(pin or ""):
        raise PinError("A PIN is 4 to 6 digits.")
    changing = note.is_locked
    if changing and not unlocked:
        raise PinError("Unlock the note before changing its PIN.", status=403)
    note.pin_hash = make_password(pin)
    note.pin_set_at = timezone.now()
    note.failed_pin_attempts = 0
    note.pin_locked_until = None
    note.save(update_fields=["pin_hash", "pin_set_at", "failed_pin_attempts",
                             "pin_locked_until", "updated_at"])
    # The setter keeps seeing what they just protected. Every other open
    # unlock predates pin_set_at and is now void.
    _grant_unlock(note, request)
    _audit(note, request.user, "note.pin_changed" if changing else "note.pin_set",
           title_is_auto=note.title_is_auto)


@transaction.atomic
def remove_pin(note, *, request, unlocked: bool):
    if not note.is_locked:
        return
    if not unlocked:
        raise PinError("Unlock the note before removing its PIN.", status=403)
    _clear(note)
    _audit(note, request.user, "note.pin_removed")


def _clear(note):
    note.pin_hash = None
    note.pin_set_at = None
    note.failed_pin_attempts = 0
    note.pin_locked_until = None
    note.save(update_fields=["pin_hash", "pin_set_at", "failed_pin_attempts",
                             "pin_locked_until", "updated_at"])


def unlock(note, pin, *, request):
    """FR-2.9/2.10. Five consecutive wrong PINs lock the note for 15 minutes.

    The counter is per note, not per user: the note is what is being guessed
    at, and five people trying one PIN each is the same attack as one person
    trying five.
    """
    from apps.notes.models import Note

    with transaction.atomic():
        note = Note.all_objects.select_for_update().get(pk=note.pk)
        if not note.is_locked:
            return note
        now = timezone.now()
        if note.pin_locked_until and note.pin_locked_until > now:
            minutes = max(1, int((note.pin_locked_until - now).total_seconds() // 60) + 1)
            raise PinError(
                f"Too many wrong PINs. This note is locked for {minutes} more "
                f"minute{'s' if minutes != 1 else ''}.",
                status=423, locked_until=note.pin_locked_until.isoformat(),
            )
        if check_password(pin or "", note.pin_hash):
            note.failed_pin_attempts = 0
            note.pin_locked_until = None
            note.save(update_fields=["failed_pin_attempts", "pin_locked_until", "updated_at"])
            _grant_unlock(note, request)
            _audit(note, request.user, "note.unlocked")
            return note

        note.failed_pin_attempts += 1
        attempt = note.failed_pin_attempts
        _audit(note, request.user, "note.pin_failed", attempt=attempt)
        if attempt >= MAX_ATTEMPTS:
            note.pin_locked_until = now + LOCKOUT
            note.failed_pin_attempts = 0
            _audit(note, request.user, "note.pin_lockout", attempts=attempt,
                   locked_until=note.pin_locked_until.isoformat())
        note.save(update_fields=["failed_pin_attempts", "pin_locked_until", "updated_at"])

    if note.pin_locked_until and note.pin_locked_until > timezone.now():
        raise PinError(
            "Too many wrong PINs. This note is locked for 15 minutes, and the "
            "attempts have been recorded.",
            status=423, locked_until=note.pin_locked_until.isoformat(),
        )
    left = MAX_ATTEMPTS - attempt
    raise PinError(
        f"Wrong PIN. {left} attempt{'s' if left != 1 else ''} left before a "
        f"15-minute lockout.",
        attempts_left=left,
    )


def lock_now(note, *, request):
    from apps.notes.models import NotePinUnlock

    NotePinUnlock.all_objects.filter(
        note=note, user=request.user, session_key=request.session.session_key,
    ).delete()


# --------------------------------------------------------------- reset (FF)
# The link is a MagicLinkToken with purpose `pin_reset` (assumption C3): stored
# only as a hash, single-use, 20 minutes, tenant-scoped — so a token from
# another tenant resolves to nothing here. `redirect_to` carries the note id.

def request_reset(note, *, request):
    """FR-2.12 — email the FF a link. The email carries no PIN and no body.

    Sent synchronously like a magic link (assumption A2a): a reset queued
    behind a transcription would look broken.
    """
    from django.conf import settings

    from apps.accounts.mailer import send_now
    from apps.accounts.models import MagicLinkPurpose, MagicLinkToken
    from apps.notes.access import display_title

    if not note.is_locked:
        raise PinError("That note has no PIN.")
    _, raw = MagicLinkToken.issue(
        tenant=note.tenant, user=request.user, purpose=MagicLinkPurpose.PIN_RESET,
        redirect_to=f"note:{note.pk}", requested_ip=request.META.get("REMOTE_ADDR"),
    )
    # APP_ROOT_URL is the Vite origin in development and a bare "/" in
    # production, where the SPA is served from PUBLIC_BASE_URL.
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    url = f"{root.rstrip('/')}/notes/pin-reset/{raw}"
    send_now(
        tenant=note.tenant,
        to_address=request.user.email,
        subject="Clear a note's PIN",
        body_text=(
            f"You asked to reset the PIN on the note \"{display_title(note)}\".\n\n"
            f"This link CLEARS the PIN. It does not tell you what the PIN was. "
            f"Once cleared, the note is readable by everyone who can normally see "
            f"it, until someone sets a new PIN.\n\n{url}\n\n"
            f"The link works once and expires in 20 minutes. If you did not ask for "
            f"this, ignore this email; nothing changes."
        ),
        producer="note_pin_reset",
        actor=request.user,
    )
    _audit(note, request.user, "note.pin_reset_requested")


def _resolve(raw: str, *, user):
    from apps.accounts.models import MagicLinkPurpose, MagicLinkToken
    from apps.notes.models import Note

    token = MagicLinkToken.resolve(raw or "", purpose=MagicLinkPurpose.PIN_RESET)
    if token is None or token.tenant_id != user.membership.tenant_id:
        raise PinError("This reset link is not valid, has expired, or has been used.")
    if token.user_id != user.pk:
        raise PinError("This reset link was issued to someone else.", status=403)
    note_id = token.redirect_to.removeprefix("note:")
    note = Note.objects.filter(pk=note_id, deleted_at__isnull=True).first()
    if note is None:
        raise PinError("That note no longer exists.", status=404)
    # Issued for the PIN in force at the time: a PIN set or changed since then
    # is not what the FF asked to clear.
    if not note.is_locked or note.pin_set_at > token.created_at:
        raise PinError("The PIN on this note has changed since the link was sent. "
                       "Request a new one if it still needs clearing.")
    return token, note


def reset_target(raw: str, *, user):
    """The note a link would reset, or a PinError. Changes nothing."""
    return _resolve(raw, user=user)[1]


@transaction.atomic
def confirm_reset(raw: str, *, request):
    token, note = _resolve(raw, user=request.user)
    token.consume()
    _clear(note)
    _audit(note, request.user, "note.pin_reset")
    return note
