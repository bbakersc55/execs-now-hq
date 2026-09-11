"""Who sees which notes, and how much of each (matrix §6, FR-2.9–2.11b).

Two independent gates, and they must stay independent:

- **Scope** is a role rule: FF and VA see every note; a CF sees notes on
  records in their scope, plus notes they wrote. Out of scope is a 404.
- **The PIN** is not a role (matrix 6.4). A locked note is a stub for
  everyone — the FF included — until *this user* unlocks it in *this browser
  session*. Nothing above the stub is decided by role.
"""

from __future__ import annotations

from django.db.models import F, Q
from django.utils import timezone

from apps.crm import permissions as crm_perms
from apps.tenancy.models import Role

LOCKED_TITLE = "Locked note"
UNTITLED = "Untitled note"
TITLE_MAX = 80


def derive_title(body: str) -> str:
    """FR-2.1 — the first non-empty line of the body, without markdown marks."""
    for line in (body or "").splitlines():
        text = line.strip().lstrip("#>*-+ ").strip()
        if text:
            return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"
    return ""


def display_title(note) -> str:
    """FR-2.11b — the invariant, whatever path produced the note.

    A locked note never shows an auto-derived title: that title IS the first
    line of the body the PIN exists to hide.
    """
    if note.is_locked and note.title_is_auto:
        return LOCKED_TITLE
    return note.title or UNTITLED


def note_queryset_for(request, queryset):
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role == Role.CF:
        from apps.crm.models import Contact

        visible_contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.all()
        ).values("pk")
        return queryset.filter(
            Q(created_by_id=request.user.pk)
            | Q(contact_id__in=visible_contacts)
            | Q(company_id__in=crm_perms.assigned_company_ids(request))
            | Q(task__contact_id__in=visible_contacts)
        )
    return queryset.none()


def unlocked_note_ids(request, notes) -> set:
    """Notes this user has unlocked in this session, still in force.

    `unlocked_at >= pin_set_at` is what makes a PIN change or reset revoke
    every open unlock without touching the unlock rows.
    """
    from apps.notes.models import NotePinUnlock

    session_key = getattr(request.session, "session_key", None)
    locked = [n.pk for n in notes if n.is_locked]
    if not session_key or not locked:
        return set()
    return set(
        NotePinUnlock.objects.filter(
            note_id__in=locked, user_id=request.user.pk, session_key=session_key,
            expires_at__gt=timezone.now(), unlocked_at__gte=F("note__pin_set_at"),
        ).values_list("note_id", flat=True)
    )


def can_read(request, note) -> bool:
    return not note.is_locked or note.pk in unlocked_note_ids(request, [note])
