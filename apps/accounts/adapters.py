"""Invite-only Google sign-in (assumption C1).

Two things have to be true, and an earlier version got the second one wrong:

1. An address with no live Membership must be REFUSED. `SOCIALACCOUNT_AUTO_SIGNUP
   = False` alone does not do this — allauth would send the visitor to a signup
   form (or, with signup closed, allauth's stock "Sign Up Closed" page).

2. An address WITH a live Membership must be CONNECTED to its existing User.
   Simply returning from `pre_social_login` is not enough: allauth's
   `_authenticate` then re-reads `sociallogin.is_existing`, finds a temporary
   unsaved user, and routes to signup — which is closed. So an invited user hits
   the same "Sign Up Closed" page as a stranger. Calling `sociallogin.connect()`
   here binds the Google identity to the existing User, which flips
   `is_existing` to True and routes to the login path instead.

Both branches are decided from the Google-VERIFIED email. An unverified address
is never trusted to match a Membership, because that would let anyone who can
put a string in an OAuth profile inherit someone else's access.
"""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


def _verified_email(sociallogin) -> str | None:
    """The Google-verified address on this login, or None.

    Prefers the EmailAddress records allauth built from the provider response;
    falls back to the raw `email_verified` claim. Never returns an address that
    the provider did not vouch for.
    """
    for address in getattr(sociallogin, "email_addresses", []) or []:
        if address.verified and address.email:
            return address.email.strip().lower()

    extra = getattr(sociallogin.account, "extra_data", {}) or {}
    if extra.get("email_verified") or extra.get("verified_email"):
        email = (extra.get("email") or "").strip().lower()
        return email or None
    return None


def _live_membership_for(email: str):
    from apps.tenancy.models import Membership

    if not email:
        return None
    return (
        Membership.all_objects.select_related("user", "tenant")
        .filter(user__email__iexact=email, revoked_at__isnull=True)
        .first()
    )


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """No self-serve signup by any route (`CLAUDE.md`: Beta has no signup)."""

    def is_open_for_signup(self, request):
        return False


class InviteOnlySocialAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return False

    def pre_social_login(self, request, sociallogin):
        email = _verified_email(sociallogin)
        membership = _live_membership_for(email) if email else None

        if membership is None:
            self._refuse(request)

        # Already linked to a User by a previous sign-in: membership is checked
        # above, so a revoked member is turned away even though the
        # SocialAccount row still exists (FR-0.8c).
        if sociallogin.is_existing:
            return

        user = membership.user
        if user is None or not user.is_active:
            self._refuse(request)

        # THE FIX. Binds this Google identity to the existing User and saves the
        # SocialAccount, so allauth's `_authenticate` sees is_existing == True
        # and logs them in instead of attempting a (closed) signup.
        sociallogin.connect(request, user)

    @staticmethod
    def _refuse(request):
        messages.error(
            request,
            "That account has no access to this workspace. Execs NOW HQ is "
            "invite-only; ask the practice owner to invite you.",
        )
        raise ImmediateHttpResponse(redirect(reverse("login-refused")))
