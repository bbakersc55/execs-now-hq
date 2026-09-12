from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views
from apps.crm import views_gmail
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
    path("api/me", account_views.me, name="me"),
    path("api/", include("apps.crm.urls")),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.notes.urls")),
    path("api/", include("apps.work.urls")),
    # FR-3.33a — the cadence link from a digest footer. No session: the signed
    # token IS the authentication, and it grants that one capability. Under
    # /api/ so the app's own page can render it (the dev proxy forwards /api);
    # the link in the email points at the app route that calls this.
    path("api/cadence/<str:token>", work_cadence.cadence_link, name="cadence-link"),
    path("accounts/refused", account_views.login_refused, name="login-refused"),
    path("auth/magic/request", account_views.request_magic_link, name="magic-request"),
    # C3.3: GET renders a confirmation page; only POST consumes the token.
    path("auth/magic/<str:token>", account_views.magic_link_landing, name="magic-landing"),
]
