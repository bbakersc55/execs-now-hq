"""allauth's pages, only those our sign-in uses (2026-11-27, the security
updates, docs/p17_security_updates.md).

Before this, `config/urls.py` mounted all of `allauth.urls`, so pages no one
uses answered in production: a password reset form, password change and set,
email management, re-authentication, login by code, social connections. Each
is an entry point with nothing behind it in this app (no account has a
password, docs/00_assumptions.md C4), and a future allauth release could add
more. Now the list is ours, and it is short:

- **Kept**: Google's Workspace sign-in (allauth's provider pages, whose
  callback is the address registered at Google), allauth's "cancelled" and
  "error" pages after Google, and sign-out.
- **allauth's own login page** sends people to our sign-in page.
- **Closed**: everything else answers "not found". Each closed page keeps its
  name, so allauth code that builds a link to one never breaks, and the link
  leads to a 404. "Inactive" goes to our refusal page instead, as a refused
  sign-in always does.

Our own sign-in routes (Google start, the External client, Microsoft, the
Gmail and Outlook connections, the email link) are in config/urls.py.
"""
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect
from django.urls import path, re_path

from allauth.account.views import logout
from allauth.socialaccount import views as social_views
from allauth.socialaccount.providers.google import views as google_views

from apps.accounts import views as account_views


def closed(request, *args, **kwargs):
    """A page allauth offers and this app doesn't: not found."""
    raise Http404("This page is not part of the app.")


def to_sign_in(request, *args, **kwargs):
    return redirect(settings.APP_ROOT_URL)


#: (path, name) of every allauth page that answers "not found".
CLOSED = [
    ("signup/", "account_signup"),
    ("3rdparty/signup/", "socialaccount_signup"),
    ("3rdparty/", "socialaccount_connections"),
    ("password/change/", "account_change_password"),
    ("password/set/", "account_set_password"),
    ("password/reset/", "account_reset_password"),
    ("password/reset/done/", "account_reset_password_done"),
    ("password/reset/key/done/", "account_reset_password_from_key_done"),
    ("email/", "account_email"),
    ("confirm-email/", "account_email_verification_sent"),
    ("reauthenticate/", "account_reauthenticate"),
    ("reauthenticate/code/", "account_request_reauthentication_code"),
    ("reauthenticate/code/confirm/", "account_confirm_reauthentication_code"),
    ("login/code/confirm/", "account_confirm_login_code"),
    ("google/login/token/", "google_login_by_token"),
]

urlpatterns = [
    # Kept: what the sign-in uses.
    path("google/login/", google_views.oauth2_login, name="google_login"),
    path("google/login/callback/", google_views.oauth2_callback, name="google_callback"),
    path("3rdparty/login/cancelled/", social_views.login_cancelled,
         name="socialaccount_login_cancelled"),
    path("3rdparty/login/error/", social_views.login_error, name="socialaccount_login_error"),
    path("logout/", logout, name="account_logout"),
    # allauth's own login page can't sign anyone in here: to ours.
    path("login/", to_sign_in, name="account_login"),
    path("inactive/", account_views.login_refused, name="account_inactive"),
    # Closed, with their names kept.
    *[path(route, closed, name=name) for route, name in CLOSED],
    re_path(r"^confirm-email/(?P<key>[-:\w]+)/$", closed, name="account_confirm_email"),
    re_path(r"^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$", closed,
            name="account_reset_password_from_key"),
]
