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
    alias = tenant.from_address
    connection = GmailConnection.all_objects.filter(tenant=tenant, user=user).first()
    own = ""
    if connection is not None and connection.send_as_verified_at is not None:
        own = connection.email_address
    return alias, own


def resolve_from(tenant, user, producer, *, override=""):
    """The address a message should be sent from.

    `override` is the per-draft choice made in Review & edit ("alias" | "self" |
    a literal address). It wins over the stored per-producer default, because
    the person looking at the draft has more context than a setting does.
    """
    alias, own = verified_addresses(tenant, user)
    choice = override
    if choice not in (MailPreference.Sender.ALIAS, MailPreference.Sender.SELF, ""):
        # A literal address: honoured only if it is one of the two verified ones.
        return choice if choice in (alias, own) and choice else alias
    if not choice:
        preference = preference_for(tenant, user)
        choice = preference.sender_for(producer) if preference else \
            MailPreference.DEFAULTS.get(producer, MailPreference.Sender.ALIAS)
    if choice == MailPreference.Sender.SELF and own:
        return own
    return alias


def signature(tenant, user):
    """(text, html). Defaults to the user's full name over the practice name —
    a bare practice name signing a personal touch reads as a form letter."""
    preference = preference_for(tenant, user) if user is not None else None
    if preference is not None and preference.signature_text.strip():
        return preference.signature_text, preference.signature_html
    full_name = (getattr(user, "full_name", "") or "").strip()
    text = f"{full_name}\n{tenant.name}" if full_name else tenant.name
    html = (
        f"<p>{full_name}<br>{tenant.name}</p>" if full_name else f"<p>{tenant.name}</p>"
    )
    return text, html
