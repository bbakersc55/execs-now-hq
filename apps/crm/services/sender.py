"""Who an app-originated email comes from, and how it signs off (FR-1.15c/d).

Before this, everything went out as the practice alias. That is right for a
digest and wrong for a referral touch: a partner being asked for introductions
should hear from a person, not from `info@`.

Two rules govern every choice here:

1. **Only a verified send-as address is ever offered.** Gmail refuses anything
   else, and a silent rejection at send time is worse than not offering it.
2. **The alias is the fallback.** If a user's own address is not verified, the
   send still happens from the alias rather than failing — with the reason
   visible on the row, not swallowed.
"""

from __future__ import annotations

from apps.crm.models import GmailConnection, MailPreference


def preference_for(tenant, user):
    if user is None or not getattr(user, "is_authenticated", True):
        return None
    preference, _ = MailPreference.all_objects.get_or_create(tenant=tenant, user=user)
    return preference


def verified_addresses(tenant, user):
    """(alias, own_address_or_empty).

    `own` is empty unless that user has a Gmail connection whose alias is
    verified — which is the only state in which Gmail will accept either.
    """
    from apps.crm.models import MicrosoftConnection
    from apps.crm.services.transport import is_microsoft

    alias = tenant.from_address
    model = MicrosoftConnection if is_microsoft(tenant) else GmailConnection
    connection = model.all_objects.filter(tenant=tenant, user=user).first()
    own = ""
    if connection is not None and connection.send_as_verified_at is not None:
        own = connection.email_address
    return alias, own


def resolve_from(tenant, user, producer, *, override="", company=None, thread=None):
    """The address a message should be sent from (`choose`, without the
    mailbox)."""
    return choose(tenant, user, producer, override=override, company=company,
                  thread=thread)[1]


def choose(tenant, user, producer, *, override="", company=None, thread=None):
    """`(mailbox, address)`: where a message goes from (2026-10-28).

    In order: the choice made on the draft (`override`: "alias", "self", a
    mailbox as "mailbox:<id>", or a literal address); the mailbox its thread
    is already in; the company's default ("mail about this client goes from
    this mailbox"); the person's own address where their per-producer
    setting says so; their default mailbox; and the practice alias. A
    mailbox that is disconnected is passed over. With no mailbox set
    anywhere, which is every practice with one connection, the address is
    exactly what it always was, and the mailbox the one it always went
    through.
    """
    from apps.crm.services import mailboxes

    if override.startswith("mailbox:"):
        found = mailboxes.usable(tenant, override.split(":", 1)[1])
        if found is not None:
            return found, mailboxes.address_of(found)
        override = ""
    alias, own = verified_addresses(tenant, user)
    choice = override
    if choice not in (MailPreference.Sender.ALIAS, MailPreference.Sender.SELF, ""):
        # A literal address: honoured only if it is one of the two verified ones.
        address = choice if choice in (alias, own) and choice else alias
        return mailboxes.legacy_for(tenant, address), address
    if not choice and not mailboxes._off_mailboxes(tenant):
        for found in (getattr(thread, "mailbox", None), mailboxes.company_default(company)):
            if mailboxes.is_connected(found):
                return found, mailboxes.address_of(found)
    if not choice:
        preference = preference_for(tenant, user)
        choice = preference.sender_for(producer) if preference else \
            MailPreference.DEFAULTS.get(producer, MailPreference.Sender.ALIAS)
        if choice != MailPreference.Sender.SELF or not own:
            found = mailboxes.user_default(tenant, user) \
                if not mailboxes._off_mailboxes(tenant) else None
            if found is not None:
                return found, mailboxes.address_of(found)
    address = own if choice == MailPreference.Sender.SELF and own else alias
    return mailboxes.legacy_for(tenant, address), address


def _default_signature_text(tenant, user):
    full_name = (getattr(user, "full_name", "") or "").strip()
    return f"{full_name}\n{tenant.name}" if full_name else tenant.name


def signature_texts(tenant):
    """Every sign-off a member of the practice's staff adds, longest first.

    How the email layout finds the signature at the end of a draft to set it
    in the branded sign-off block. Read-only: unlike `signature`, it creates no
    preference rows, because rendering an email must write nothing.
    """
    from apps.tenancy.models import Membership, Role

    members = Membership.all_objects.filter(
        tenant=tenant, role__in=[Role.FF, Role.CF, Role.VA], revoked_at__isnull=True,
    ).select_related("user")
    saved = dict(MailPreference.all_objects.filter(tenant=tenant)
                 .values_list("user_id", "signature_text"))
    texts = set()
    for member in members:
        text = (saved.get(member.user_id) or "").strip() \
            or _default_signature_text(tenant, member.user)
        texts.add(text.replace("\r\n", "\n").strip())
    return sorted((t for t in texts if t), key=len, reverse=True)


def signature(tenant, user):
    """(text, html). Defaults to the user's full name over the practice name —
    a bare practice name signing a personal touch reads as a form letter."""
    preference = preference_for(tenant, user) if user is not None else None
    if preference is not None and preference.signature_text.strip():
        return preference.signature_text, preference.signature_html
    full_name = (getattr(user, "full_name", "") or "").strip()
    text = _default_signature_text(tenant, user)
    html = (
        f"<p>{full_name}<br>{tenant.name}</p>" if full_name else f"<p>{tenant.name}</p>"
    )
    return text, html
