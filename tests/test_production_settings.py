"""Phase 7 — the app configured for Railway, tested without Railway.

Settings are read once, at import, so the production shape is booted in a
subprocess with production-shaped variables. Nothing here reaches a network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PRODUCTION = {
    "PUBLIC_BASE_URL": "https://app.getexecutivesnow.com",
    "DJANGO_SECRET_KEY": "a-real-one-for-this-test",
    "DJANGO_DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": "app.getexecutivesnow.com,healthcheck.railway.app",
    # The laptop's .env sets these; production must not, so they are blanked
    # rather than inherited.
    "DEV_REAL_SEND_ALLOWLIST": "",
    "ANTHROPIC_API_KEY": "",
    "STORAGE_BACKEND": "gcs",
}

PROBE = ("import django, json; django.setup(); from django.conf import settings as s; "
         "print(json.dumps({'proxy': s.SECURE_PROXY_SSL_HEADER, "
         "'csrf': s.CSRF_TRUSTED_ORIGINS, 'redirect': s.SECURE_SSL_REDIRECT, "
         "'exempt': s.SECURE_REDIRECT_EXEMPT, 'debug': s.DEBUG}))")


def _boot(**overrides):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **PRODUCTION,
           **overrides}
    return subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_production_settings_boot_behind_the_proxy():
    done = _boot()
    assert done.returncode == 0, done.stderr[-2000:]
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert got["csrf"] == ["https://app.getexecutivesnow.com"]
    assert got["redirect"] is True
    assert got["exempt"] == ["^healthz$"]
    assert got["debug"] is False


def test_a_staging_origin_can_be_added_for_csrf():
    done = _boot(CSRF_TRUSTED_ORIGINS="https://staging.example.up.railway.app")
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["csrf"] == ["https://app.getexecutivesnow.com",
                           "https://staging.example.up.railway.app"]


def test_production_refuses_the_development_secret_key():
    done = _boot(DJANGO_SECRET_KEY="dev-only-insecure-key")
    assert done.returncode != 0
    assert "DJANGO_SECRET_KEY is the development default" in done.stderr


def test_production_refuses_debug():
    done = _boot(DJANGO_DEBUG="True")
    assert done.returncode != 0
    assert "DJANGO_DEBUG is on outside localhost" in done.stderr


def test_production_still_refuses_the_dev_allowlist_and_env_key():
    """The two refusals that already existed, still in force on the new shape."""
    assert "localhost-only mechanism" in _boot(
        DEV_REAL_SEND_ALLOWLIST="bryan.baker@getexecutivesnow.com").stderr
    assert "local-only dev fallback" in _boot(ANTHROPIC_API_KEY="sk-ant-x").stderr


def test_the_proxy_header_is_not_trusted_on_localhost(settings):
    """On the laptop there is no proxy, so a client could send the header."""
    assert settings.IS_LOCAL
    assert not hasattr(settings, "SECURE_PROXY_SSL_HEADER") or \
        settings.SECURE_PROXY_SSL_HEADER is None


# ------------------------------------------------------------ the app shell

@pytest.mark.django_db
def test_healthz_answers_without_a_session(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.django_db
def test_an_app_route_gets_the_built_index(client, settings, tmp_path):
    from config import spa

    (tmp_path / "index.html").write_text('<script src="/static/assets/app.js"></script>')
    settings.STATIC_ROOT = tmp_path
    spa._index.cache_clear()
    try:
        for path in ("/", "/contacts/abc", "/cadence/some-token", "/precall/xyz"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert b"/static/assets/app.js" in response.content
    finally:
        spa._index.cache_clear()


@pytest.mark.django_db
def test_an_unknown_api_path_is_a_404_not_the_app(client):
    response = client.get("/api/no-such-thing/")
    assert response.status_code == 404
    assert b"<script" not in response.content


# ----------------------------------------------- the key from a variable

def _a_service_account_key() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return json.dumps({
        "type": "service_account", "project_id": "execs-now-hq",
        "private_key_id": "test", "private_key": pem,
        "client_email": "sa-app@execs-now-hq.iam.gserviceaccount.com",
        "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"})


def test_the_json_variable_is_used_and_wins_over_the_file(settings):
    from apps.tenancy import google_credentials

    settings.GOOGLE_SA_APP_JSON = _a_service_account_key()
    settings.GOOGLE_APPLICATION_CREDENTIALS = "/nonexistent/sa-app.json"
    made = google_credentials.credentials(("https://www.googleapis.com/auth/cloud-platform",))
    assert made.service_account_email == "sa-app@execs-now-hq.iam.gserviceaccount.com"


def test_a_malformed_variable_is_named_and_never_echoed(settings):
    from apps.tenancy import google_credentials

    settings.GOOGLE_SA_APP_JSON = "not json -----BEGIN PRIVATE KEY----- secret"
    with pytest.raises(google_credentials.NoServiceAccountKey) as exc:
        google_credentials.credentials(("scope",))
    assert "GOOGLE_SA_APP_JSON is set but is not valid JSON" in str(exc.value)
    assert "secret" not in str(exc.value)


def test_with_neither_the_error_says_where_it_looked(settings):
    from apps.tenancy import google_credentials

    settings.GOOGLE_SA_APP_JSON = ""
    settings.GOOGLE_APPLICATION_CREDENTIALS = "/nonexistent/sa-app.json"
    with pytest.raises(google_credentials.NoServiceAccountKey,
                       match="No service-account key at GOOGLE_APPLICATION_CREDENTIALS"):
        google_credentials.credentials(("scope",))
