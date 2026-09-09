"""Invite-only Google sign-in (assumption C1).

`SOCIALACCOUNT_AUTO_SIGNUP = False` on its own is NOT invite-only: allauth
sends an unrecognised account to a signup form, which would let a stranger
create an account. `CLAUDE.md` says there is no self-serve signup in Beta, so
sign-in must *fail* for an address with no pre-existing Membership.
"""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """No self-serve signup by any route, social or otherwise."""

    def is_open_for_signup(self, request):
        return False


class InviteOnlySocialAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return False

    def pre_social_login(self, request, sociallogin):
        """Refuse before any user or SocialAccount row is created.

        Runs on every Google callback, including the first. An address with no
        live Membership is turned away here rather than being offered a form.
        """
        from apps.tenancy.models import Membership

        email = (sociallogin.user.email or "").strip().lower()
        has_invite = (
            Membership.all_objects.filter(
                user__email__iexact=email, revoked_at__isnull=True
            ).exists()
            if email
            else False
        )
        if has_invite:
            return

        messages.error(
            request,
            "That account has no access to this workspace. Execs NOW HQ is "
            "invite-only; ask the practice owner to invite you.",
        )
        raise ImmediateHttpResponse(redirect(reverse("login-refused")))
