"""Minimal fixed-window rate limiting on the database (no Redis — A2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

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
