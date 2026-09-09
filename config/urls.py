from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/branding", account_views.branding, name="branding"),
    path("api/me", account_views.me, name="me"),
    path("accounts/refused", account_views.login_refused, name="login-refused"),
    path("auth/magic/request", account_views.request_magic_link, name="magic-request"),
    # C3.3: GET renders a confirmation page; only POST consumes the token.
    path("auth/magic/<str:token>", account_views.magic_link_landing, name="magic-landing"),
]
