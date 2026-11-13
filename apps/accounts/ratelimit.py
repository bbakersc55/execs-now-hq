"""Minimal fixed-window rate limiting (no Redis — A2).

`too_many` counts in Django's cache, which with no CACHES setting is each
process's own memory: a limit of 5 is 5 per gunicorn worker. `too_many_shared`
counts in the database (`rate_count`), so every worker sees the same count;
it is for limits that must hold exactly, such as the website's lead form.
"""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int
    prefix: str


def too_many(rule: RateLimit, key: str | None) -> bool:
    if not key:
        return False
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    cache_key = f"rl:{rule.prefix}:{digest}"
    count = cache.get_or_set(cache_key, 0, rule.window_seconds)
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, rule.window_seconds)
        count = 1
    return count > rule.limit


_UPSERT = """
    INSERT INTO rate_count (id, prefix, key_digest, window_start, count, updated_at)
    VALUES (%s, %s, %s, %s, 1, NOW())
    ON CONFLICT (prefix, key_digest, window_start)
    DO UPDATE SET count = rate_count.count + 1, updated_at = NOW()
    RETURNING count
"""


def _window(rule: RateLimit) -> datetime:
    start = int(timezone.now().timestamp()) // rule.window_seconds * rule.window_seconds
    return datetime.fromtimestamp(start, tz=dt_timezone.utc)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def too_many_shared(rule: RateLimit, key: str | None, *,
                    prune: tuple[str, ...] = ()) -> bool:
    """Count this request against `rule` in the database and say whether it is
    over. One statement, so two workers counting at once both land: Postgres
    serialises the upsert on the window's row.

    When the count opens a new window, the finished windows of this rule, and
    of the rules named in `prune` (same window length), are deleted."""
    if not key:
        return False
    window_start = _window(rule)
    with connection.cursor() as cursor:
        cursor.execute(_UPSERT, [uuid.uuid4(), rule.prefix, _digest(key), window_start])
        count = cursor.fetchone()[0]
    if count == 1:
        # A new window: the old ones of this rule are history.
        from apps.accounts.models import RateCount

        RateCount.objects.filter(
            prefix__in=(rule.prefix, *prune),
            window_start__lt=window_start - timedelta(seconds=rule.window_seconds),
        ).delete()
    return count > rule.limit


def shared_count(rule: RateLimit, key: str | None) -> int:
    """This window's count for `key`, without counting a request."""
    if not key:
        return 0
    from apps.accounts.models import RateCount

    row = RateCount.objects.filter(prefix=rule.prefix, key_digest=_digest(key),
                                   window_start=_window(rule)).values_list("count", flat=True)
    return next(iter(row), 0)


def client_ip(request) -> str | None:
    """The visitor's address. Behind `TRUSTED_PROXY_HOPS` proxies it is the
    entry the outermost trusted one appended to X-Forwarded-For; anything
    left of it was written by the client and is not believed."""
    hops = settings.TRUSTED_PROXY_HOPS
    remote = request.META.get("REMOTE_ADDR")
    if hops <= 0:
        return remote
    chain = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
             if part.strip()]
    if len(chain) < hops:
        return remote
    candidate = chain[-hops]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return remote
    return candidate
