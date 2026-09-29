"""The app's own Google identity (assumption A7), from one of two places.

- **On the laptop**, a key file: `GOOGLE_APPLICATION_CREDENTIALS`, a path.
- **On Railway**, the key itself: `GOOGLE_SA_APP_JSON`, the file's contents as
  a secret variable (Phase 7). Railway has no file to point at, and writing
  the secret to the container's disk to make one would put it somewhere
  nothing else needs it.

The JSON wins when both are set. **Never gcloud ADC**: that works on the
laptop, bills the wrong project, and fails on Railway.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from django.conf import settings


class NoServiceAccountKey(Exception):
    """Neither the variable nor the file gives a key."""


def describe() -> str:
    """Where the key would come from, for an error message. Never the key."""
    if getattr(settings, "GOOGLE_SA_APP_JSON", ""):
        return "GOOGLE_SA_APP_JSON"
    return f"GOOGLE_APPLICATION_CREDENTIALS={settings.GOOGLE_APPLICATION_CREDENTIALS!r}"


def credentials(scopes: tuple[str, ...]):
    """Service-account credentials for these scopes, or `NoServiceAccountKey`."""
    info = getattr(settings, "GOOGLE_SA_APP_JSON", "")
    if info:
        return _from_info(info, tuple(scopes))
    path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not path or not Path(path).is_file():
        raise NoServiceAccountKey(f"No service-account key at {describe()}.")
    return _from_file(path, tuple(scopes))


@functools.cache
def _from_info(info: str, scopes: tuple[str, ...]):
    from google.oauth2 import service_account

    try:
        parsed = json.loads(info)
    except ValueError as exc:
        # Never echo the value: it is a private key.
        raise NoServiceAccountKey("GOOGLE_SA_APP_JSON is set but is not valid JSON.") from exc
    return service_account.Credentials.from_service_account_info(parsed, scopes=list(scopes))


@functools.cache
def _from_file(path: str, scopes: tuple[str, ...]):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(path, scopes=list(scopes))
