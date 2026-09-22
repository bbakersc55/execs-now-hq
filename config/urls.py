from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views
from apps.crm import views_gmail
from apps.strategy import views_precall as strategy_precall
from apps.work import views_cadence as work_cadence

urlpatterns = [
    path("admin/", admin.site.urls),
    # There is no signup in Beta. These two overrides come BEFORE the allauth
    # include so allauth's signup routes and its "Sign Up Closed" template are
    # unreachable: a refused visitor always lands on our own 403 page.
    path("accounts/signup/", account_views.login_refused, name="account_signup"),
    path("accounts/3rdparty/signup/", account_views.login_refused,
         name="socialaccount_signup"),
    # Tier 1 Gmail connect (FR-6.3b). A separate consent from sign-in (C2),
    # so a separate callback — registered on the OAuth client alongside
    # allauth's. Declared BEFORE the allauth include so the path is ours.
    path("accounts/gmail/callback", views_gmail.gmail_callback,
         name="gmail-callback"),
    path("accounts/", include("allauth.urls")),
    path("api/branding", account_views.branding, name="branding"),
    # The practice's logo for client-facing pages: no id in the URL, so it can
    # only ever serve the requesting tenant's own (white-label).
    path("api/branding/logo", account_views.branding_logo, name="branding-logo"),
    path("api/me", account_views.me, name="me"),
    path("api/", include("apps.crm.urls")),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.notes.urls")),
    path("api/", include("apps.work.urls")),
    path("api/", include("apps.strategy.urls")),
    path("api/", include("apps.meetings.urls")),
    # FR-3.33a — the cadence link from a digest footer. No session: the signed
    # token IS the authentication, and it grants that one capability. Under
    # /api/ so the app's own page can render it (the dev proxy forwards /api);
    # the link in the email points at the app route that calls this.
    path("api/cadence/<str:token>", work_cadence.cadence_link, name="cadence-link"),
    # FR-4.6 / matrix 10.13 — the pre-call form. A public page authenticated by
    # one token, which can read and answer nothing but its own session's
    # pre-call questions.
    path("api/strategy/precall/<str:token>", strategy_precall.precall_form,
         name="precall-form"),
    path("api/strategy/precall/<str:token>/complete", strategy_precall.precall_complete,
         name="precall-complete"),
    path("accounts/refused", account_views.login_refused, name="login-refused"),
    path("auth/magic/request", account_views.request_magic_link, name="magic-request"),
    # C3.3: GET renders a confirmation page; only POST consumes the token.
    path("auth/magic/<str:token>", account_views.magic_link_landing, name="magic-landing"),
]
