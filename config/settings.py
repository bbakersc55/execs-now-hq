"""Execs NOW HQ settings. Secrets come from .env only (assumption E2)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    Q_CLUSTER_WORKERS=(int, 4),
    DEV_REAL_SEND_ALLOWLIST=(list, []),
    BACKUP_RETENTION_DAYS=(int, 30),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8100")
IS_LOCAL = PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1"))
# local | demo | production (config/environment.py). Defaults from the host:
# the demo must say so, because it runs off localhost like production.
APP_ENVIRONMENT = env("APP_ENVIRONMENT", default="local" if IS_LOCAL else "production")
if APP_ENVIRONMENT not in ("local", "demo", "production"):
    raise RuntimeError(f"APP_ENVIRONMENT must be local, demo or production, not "
                       f"{APP_ENVIRONMENT!r}.")
if APP_ENVIRONMENT == "local" and not IS_LOCAL:
    raise RuntimeError("APP_ENVIRONMENT is local but PUBLIC_BASE_URL is not localhost.")
if APP_ENVIRONMENT == "production" and IS_LOCAL:
    raise RuntimeError("APP_ENVIRONMENT is production but PUBLIC_BASE_URL is localhost.")
IS_DEMO = APP_ENVIRONMENT == "demo"

# Off localhost, the laptop's conveniences are refused rather than trusted to
# have been changed (Phase 7): the dev key signs every session and magic link,
# and DEBUG shows a stack trace, settings included, to anyone who finds an error.
if not IS_LOCAL and SECRET_KEY == "dev-only-insecure-key":
    raise RuntimeError("DJANGO_SECRET_KEY is the development default. Set a real one.")
if not IS_LOCAL and DEBUG:
    raise RuntimeError("DJANGO_DEBUG is on outside localhost. Turn it off.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "rest_framework",
    "django_q",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "apps.tenancy",
    "apps.accounts",
    "apps.crm",
    "apps.notes",
    "apps.work",
    "apps.strategy",
    "apps.meetings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    # Binds the tenant. Must come after authentication (assumption B1).
    "apps.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# Postgres from day one, locally too. No SQLite, ever (CLAUDE.md).
DATABASES = {"default": env.db(
    "DATABASE_URL", default="postgres://localhost:5432/execsnowhq_dev"
)}
# Django-Q2 runs on the ORM broker; idle workers must not pin connections (A2).
DATABASES["default"]["CONN_MAX_AGE"] = 0

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SITE_ID = 1

# C1: invite-only. AUTO_SIGNUP=False alone only redirects to a signup FORM —
# the adapters below are what actually refuse an uninvited account.
SOCIALACCOUNT_AUTO_SIGNUP = False
ACCOUNT_ADAPTER = "apps.accounts.adapters.NoSignupAccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.InviteOnlySocialAdapter"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
# Our User has no `username` field (C4: email is the identifier). Without this,
# allauth's user_display() raises AttributeError while rendering any template
# that shows a user — including the account-connected notification sent during
# a successful Google sign-in.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        # Credentials come from .env, not a SocialApp database row (E2:
        # secrets in .env only, nothing secret committed — and nothing secret
        # in the nightly pg_dump either).
        "APP": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "key": "",
        },
        # 5a: identity only. `gmail.send` is a separate consent flow (C2).
        "SCOPE": ["openid", "email", "profile"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

# Where a successful sign-in lands. Without this, Django's default
# LOGIN_REDIRECT_URL is "/accounts/profile/", which this app does not serve —
# a successful Google sign-in ended on a 404.
#
# In development the app root is the Vite dev server on 5200; in production
# Django serves the built bundle at "/". Overridable per environment.
APP_ROOT_URL = env(
    "APP_ROOT_URL", default="http://localhost:5200/" if IS_LOCAL else "/"
)
LOGIN_REDIRECT_URL = APP_ROOT_URL
LOGOUT_REDIRECT_URL = APP_ROOT_URL
ACCOUNT_LOGOUT_REDIRECT_URL = APP_ROOT_URL
ACCOUNT_SIGNUP_REDIRECT_URL = APP_ROOT_URL
LOGIN_URL = "/accounts/google/login/"

# C3.5: 12-hour idle for tenant users; client sessions are extended on login.
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not IS_LOCAL
CSRF_COOKIE_SECURE = not IS_LOCAL
SECURE_SSL_REDIRECT = not IS_LOCAL
# Behind Railway's proxy (Phase 7). TLS ends at the proxy, so without this
# every request looks like plain http: SECURE_SSL_REDIRECT loops forever, and
# Google sign-in builds an http:// callback that Google refuses. Trusted only
# off localhost, where the proxy is the only way in.
if not IS_LOCAL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Railway's health check calls over plain http inside its network.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
# The public origin, and any others named (a staging host), for CSRF on
# HTTPS POSTs. Localhost needs none: Django checks same-origin itself.
CSRF_TRUSTED_ORIGINS = ([] if IS_LOCAL else [PUBLIC_BASE_URL.rstrip("/")]) + env.list(
    "CSRF_TRUSTED_ORIGINS", default=[])
CLIENT_SESSION_AGE = 60 * 60 * 24 * 30

REST_FRAMEWORK = {
    # G2: session cookies, CSRF enforced. No JWT.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --- Background jobs: ORM broker, no Redis (assumption A2) ---
Q_CLUSTER = {
    "name": "execsnowhq",
    "workers": env("Q_CLUSTER_WORKERS"),
    "recycle": 500,
    "timeout": 60 * 55,
    "retry": 60 * 60,
    "queue_limit": 50,
    "bulk": 5,
    "orm": "default",
    # OFF, which is what "a missed schedule fires once on next start" actually
    # takes. ON means the opposite: Django-Q replays EVERY missed occurrence,
    # one per scheduler pass, so a one-minute job left behind by a laptop that
    # slept overnight fires every ~30 s for hours instead of resuming cadence.
    # OFF advances next_run past now and fires once, so a missed daily job is
    # still owed its run and a heartbeat simply picks up where it left off.
    "catch_up": False,
}

# --- Email ---
DEFAULT_FROM_ADDRESS = env("DEFAULT_FROM_ADDRESS", default="info@getexecutivesnow.com")
INBOUND_DOMAIN = env("INBOUND_DOMAIN", default="inbound.getexecutivesnow.com")
# Beta sends ALL app-originated mail through the tenant's connected Gmail with
# From set to their send-as alias. Postmark becomes a per-tenant transport
# option in V1, not a Beta dependency (owner decision).
APP_MAIL_TRANSPORT = env("APP_MAIL_TRANSPORT", default="gmail")
if APP_MAIL_TRANSPORT not in ("gmail", "postmark"):
    raise RuntimeError(
        f"APP_MAIL_TRANSPORT must be 'gmail' or 'postmark', got {APP_MAIL_TRANSPORT!r}."
    )

# Optional in Beta — only needed if APP_MAIL_TRANSPORT=postmark.
POSTMARK_SERVER_TOKEN = env("POSTMARK_SERVER_TOKEN", default="")
POSTMARK_INBOUND_WEBHOOK_SECRET = env("POSTMARK_INBOUND_WEBHOOK_SECRET", default="")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
if IS_DEMO:
    # The demo sends nothing: every message goes to the dev transport
    # (apps/crm/services/outbox.py), and this backend discards it.
    EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)

# FR-0.7 / assumption H6. Exact addresses only — a domain wildcard would put
# every colleague and client at that domain back in range.
DEV_REAL_SEND_ALLOWLIST = [a.strip().lower() for a in env("DEV_REAL_SEND_ALLOWLIST") if a.strip()]
if not IS_LOCAL and DEV_REAL_SEND_ALLOWLIST:
    raise RuntimeError(
        "DEV_REAL_SEND_ALLOWLIST is a localhost-only mechanism and must not "
        "exist in production. Remove it from the environment."
    )
for _entry in DEV_REAL_SEND_ALLOWLIST:
    if _entry.startswith("@") or "*" in _entry or "@" not in _entry:
        raise RuntimeError(
            f"DEV_REAL_SEND_ALLOWLIST entry {_entry!r} is not an exact address. "
            "Wildcards and bare domains are rejected: one entry would put every "
            "colleague and client at that domain back in range (assumption H6)."
        )

# --- AI ---
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", default="claude-opus-5")
if ANTHROPIC_API_KEY and not IS_LOCAL:
    raise RuntimeError(
        "ANTHROPIC_API_KEY in the environment is a local-only dev fallback "
        "(assumption E1.6). In production each tenant supplies its own key."
    )

# --- Secrets (assumption E1) ---
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

# --- Google ---
GOOGLE_CLOUD_PROJECT = env("GOOGLE_CLOUD_PROJECT", default="execs-now-hq")
GCS_BUCKET_MEDIA = env("GCS_BUCKET_MEDIA", default="execs-now-hq-media")
# Speech-to-Text language for recordings (FR-2.16). BCP-47.
GOOGLE_STT_LANGUAGE = env("GOOGLE_STT_LANGUAGE", default="en-US")

# The app's own Google identity (05_dev_environment.md §5b). Expanded here
# because the Google libraries open this path verbatim, and `~` in .env would
# otherwise be a file-not-found that reads like a bad key. Loaded explicitly by
# apps/tenancy/storage.py — never via ADC (assumption A7).
_credentials_path = env("GOOGLE_APPLICATION_CREDENTIALS", default="")
GOOGLE_APPLICATION_CREDENTIALS = str(Path(_credentials_path).expanduser()) if _credentials_path else ""
# On Railway the key arrives as the file's contents, not a path (Phase 7);
# apps/tenancy/google_credentials.py prefers it when set.
GOOGLE_SA_APP_JSON = env("GOOGLE_SA_APP_JSON", default="")

# Where `stored_file` content lives. `gcs` (gs://<bucket>/<object_key>) since
# Phase 2: a recording exists nowhere else, so it cannot wait for a nightly
# sync. `local` (MEDIA_ROOT/<bucket>/<object_key>, the same shape) is for the
# test suite, the restore drill, and the laptop since B7 (its scrubbed copy of
# production must never reach production's bucket).
STORAGE_BACKEND = env("STORAGE_BACKEND", default="gcs")
if STORAGE_BACKEND not in ("gcs", "local"):
    raise RuntimeError(f"STORAGE_BACKEND must be 'gcs' or 'local', not {STORAGE_BACKEND!r}.")
if STORAGE_BACKEND == "local" and not IS_LOCAL:
    raise RuntimeError(
        "STORAGE_BACKEND=local outside localhost would write client files to a "
        "container disk that is discarded on every deploy. Use gcs."
    )
if IS_DEMO and GCS_BUCKET_MEDIA == "execs-now-hq-media":
    raise RuntimeError("The demo must not write to the production media bucket. Set "
                       "GCS_BUCKET_MEDIA to the demo's own bucket.")
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
MEDIA_URL = "/media/"

# --- Errors: production only (assumption A5) ---
SENTRY_DSN = env("SENTRY_DSN", default="")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # stored UTC; rendered in the recipient's zone (D4)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"] if (BASE_DIR / "frontend" / "dist").exists() else []
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
