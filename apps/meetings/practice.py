"""Recognising our own side of the table (FR-5.9e).

**The fractional is in every meeting.** Their own name came back as a
participant proposal on every real note — "is this person new, and what are
they to us?" — with only the five contact types on offer, none of which is
true. The practice is not a prospect, a client, a referral partner, a vendor or
a coworker of itself. The question was wrong, not the answer.

So a participant who **is** somebody on the practice's staff is *recognised*
rather than asked about: shown on the proposal as the practice, given no type,
needing no approval, and recorded on the meeting as having attended. Every
other participant is untouched — this narrows what gets asked, it does not
loosen who gets created.

Matching is **email, then name**, the same order and for the same reason as
`matching.py`: an address is an identity and a name is a coincidence waiting to
happen. A name-only match that could be two different people is not a match at
all — one of the two "Bryan Baker" rows in the owner's own CRM is exactly that
case, and guessing between them would put a meeting on a stranger's timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.tenancy.models import Membership, Role

#: Whose meetings these are. Client roles are deliberately absent: an FCC is a
#: client, is asked about like any other participant, and being recognised as
#: "the practice" would be wrong in a way that matters.
STAFF_ROLES = (Role.FF, Role.CF, Role.VA)

EMAIL = "email"
NAME = "name"


@dataclass
class Practice:
    """One member of staff, and the contact row that stands for them."""

    user_id: str
    name: str
    role: str
    contact: object = None
    matched_on: str = ""
    emails: set = field(default_factory=set)
    names: set = field(default_factory=set)


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def staff(tenant) -> list[Practice]:
    """Everybody on the practice's side, with their addresses and names.

    The contact row is resolved three ways, in order of how sure each is:
    the membership's own link, then an address the user signs in with, then a
    name that matches **exactly one** contact. The owner's membership has no
    linked contact and his address is on a contact row — the second rule is
    what finds him, and the first is what will once a login is attached.
    """
    from apps.crm.models import Contact, ContactEmail

    found = []
    memberships = (Membership.objects.filter(role__in=STAFF_ROLES,
                                             revoked_at__isnull=True)
                   .select_related("user", "contact"))
    for membership in memberships:
        user = membership.user
        full_name = _norm(user.full_name)
        emails = {_norm(user.email)} - {""}
        names = {full_name} - {""}

        contact = membership.contact
        if contact is None and emails:
            row = ContactEmail.objects.filter(
                address__in=list(emails), contact__deleted_at__isnull=True
            ).select_related("contact").first()
            contact = row.contact if row else None
        if contact is None and full_name:
            parts = full_name.split()
            matches = list(Contact.objects.filter(
                deleted_at__isnull=True, first_name__iexact=parts[0],
                last_name__iexact=parts[-1] if len(parts) > 1 else "")[:2])
            # Exactly one, or none. Two people with the practice owner's name
            # is a real thing in a real CRM, and picking either is a guess.
            contact = matches[0] if len(matches) == 1 else None

        if contact is not None:
            emails |= {_norm(a) for a in ContactEmail.objects.filter(
                contact=contact).values_list("address", flat=True)} - {""}
            names |= {_norm(f"{contact.first_name} {contact.last_name}")} - {""}

        found.append(Practice(
            user_id=str(user.pk), name=(user.full_name.strip() or user.email),
            role=membership.role, contact=contact, emails=emails, names=names))
    return found


def recognise(tenant, *, name: str = "", email: str = "",
              roster: list[Practice] | None = None) -> Practice | None:
    """Is this participant one of us? **Email first, then name.**

    Returns a copy carrying `matched_on`, so the screen can say which rule
    recognised them rather than asserting it.
    """
    roster = staff(tenant) if roster is None else roster
    address, person = _norm(email), _norm(name)

    if address:
        for member in roster:
            if address in member.emails:
                return _matched(member, EMAIL)
    if person:
        for member in roster:
            if person in member.names:
                return _matched(member, NAME)
    return None


def _matched(member: Practice, rule: str) -> Practice:
    return Practice(user_id=member.user_id, name=member.name, role=member.role,
                    contact=member.contact, matched_on=rule,
                    emails=member.emails, names=member.names)


def payload_for(member: Practice) -> dict:
    """What the proposal stores instead of a question.

    **No `proposed_contact_type` and no candidates**: there is nothing to
    decide, and offering either would be offering the wrong question in a
    smaller font.
    """
    return {
        "is_practice": True,
        "practice_user_id": member.user_id,
        "practice_name": member.name,
        "practice_role": member.role,
        "matched_on": member.matched_on,
        "contact_id": str(member.contact.pk) if member.contact is not None else None,
    }


def is_practice_item(item, *, tenant=None, roster=None) -> bool:
    """Whether a participant item is the practice — from its payload if the
    parse already knew, and from a live check if it did not.

    The live fallback is what stops a proposal parsed **before** this rule
    existed from sitting at `partially_actioned` forever on a row nobody will
    ever action. There are eight of those in the owner's queue.
    """
    payload = item.payload or {}
    if payload.get("is_practice"):
        return True
    return recognise(tenant or item.tenant,
                     name=payload.get("parsed_name") or "",
                     email=payload.get("parsed_email") or "",
                     roster=roster) is not None
