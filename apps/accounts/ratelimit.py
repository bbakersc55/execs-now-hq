"""Minimal fixed-window rate limiting on the database (no Redis — A2)."""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache


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
