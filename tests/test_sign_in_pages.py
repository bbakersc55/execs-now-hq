"""The sign-in pages no one uses answer "not found" (2026-11-27,
docs/p17_security_updates.md): Django's admin outside the laptop, and
allauth's password, sign-up and account pages everywhere. Google sign-in and
the email sign-in link keep working (tests/test_google_signin.py and
tests/test_magic_link.py go through them end to end; the checks here are
that their routes are still the ones in use)."""
import importlib

import pytest
from django.urls import NoReverseMatch, clear_url_caches, resolve, reverse

from apps.accounts import urls_allauth


def _reload_urls():
    import config.urls

    importlib.reload(config.urls)
    clear_url_caches()


@pytest.fixture
def admin_off(settings):
    """The URL list as production and the demo build it."""
    was = settings.ADMIN_ENABLED
    settings.ADMIN_ENABLED = False
    _reload_urls()
    yield
    settings.ADMIN_ENABLED = was
    _reload_urls()


@pytest.fixture
def admin_on(settings):
    was = settings.ADMIN_ENABLED
    settings.ADMIN_ENABLED = True
    _reload_urls()
    yield
    settings.ADMIN_ENABLED = was
    _reload_urls()


def test_admin_is_off_outside_the_laptop(settings):
    """ADMIN_ENABLED follows IS_LOCAL: on in development, off in production."""
    from config import settings as project

    assert project.ADMIN_ENABLED == project.IS_LOCAL


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/admin/", "/admin/login/", "/admin/auth/user/"])
def test_the_admin_answers_not_found_in_production(admin_off, client, path):
    assert client.get(path).status_code == 404
    assert client.post(path, {"username": "x", "password": "y"}).status_code == 404


@pytest.mark.django_db
def test_the_admin_still_answers_on_the_laptop(admin_on, client):
    assert client.get("/admin/login/").status_code == 200


CLOSED_PATHS = [
    "/accounts/password/reset/",
    "/accounts/password/reset/done/",
    "/accounts/password/reset/key/1-abc/",
    "/accounts/password/reset/key/done/",
    "/accounts/password/change/",
    "/accounts/password/set/",
    "/accounts/signup/",
    "/accounts/3rdparty/signup/",
    "/accounts/3rdparty/",
    "/accounts/email/",
    "/accounts/confirm-email/",
    "/accounts/confirm-email/abc:def/",
    "/accounts/reauthenticate/",
    "/accounts/login/code/confirm/",
    "/accounts/google/login/token/",
    "/accounts/social/signup/",
    "/accounts/social/connections/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("path", CLOSED_PATHS)
def test_each_unused_page_answers_not_found(client, path):
    assert client.get(path).status_code == 404, path
    assert client.post(path, {"email": "someone@example.invalid"}).status_code == 404, path


@pytest.mark.django_db
def test_a_password_reset_request_sends_nothing(client, mailoutbox):
    client.post("/accounts/password/reset/", {"email": "someone@example.invalid"})
    assert mailoutbox == []


@pytest.mark.django_db
def test_allauths_own_login_page_sends_people_to_ours(client, settings):
    response = client.get("/accounts/login/")
    assert response.status_code == 302 and response["Location"] == settings.APP_ROOT_URL


def test_every_name_allauth_links_to_still_builds_a_link():
    """allauth's code reverses its own names (a link in a template, a
    redirect for an inactive user); none may raise. Every closed one leads
    to a 404."""
    from allauth.account import urls as account_urls
    from allauth.socialaccount import urls as social_urls
    from allauth.socialaccount.providers.google import urls as google_urls

    kwargs = {"account_confirm_email": {"key": "abc"},
              "account_reset_password_from_key": {"uidb36": "1", "key": "abc"}}
    names = {p.name for mod in (account_urls, social_urls, google_urls)
             for p in mod.urlpatterns if getattr(p, "name", None)}
    assert names, "allauth's url modules changed shape"
    closed = {name for _, name in urls_allauth.CLOSED} | {
        "account_confirm_email", "account_reset_password_from_key"}
    for name in sorted(names):
        try:
            url = reverse(name, kwargs=kwargs.get(name))
        except NoReverseMatch:
            pytest.fail(f"allauth's {name!r} no longer builds a link")
        if name in closed:
            assert resolve(url).func is urls_allauth.closed, name


def test_google_sign_in_keeps_the_callback_registered_at_google():
    from allauth.socialaccount.providers.google import views as google_views

    assert reverse("google_callback") == "/accounts/google/login/callback/"
    assert resolve("/accounts/google/login/callback/").func is google_views.oauth2_callback
    assert resolve("/accounts/google/start").url_name == "google-start"
    assert resolve("/accounts/google/external/callback").url_name == "google-external-callback"
    assert resolve("/accounts/microsoft/start").url_name == "microsoft-start"


def test_the_email_sign_in_link_routes_are_unchanged():
    assert resolve("/auth/magic/request").url_name == "magic-request"
    assert resolve("/auth/magic/abc").url_name == "magic-landing"
    assert resolve("/accounts/refused").url_name == "login-refused"
