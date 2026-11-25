"""Policy violations reported by browsers (docs/p16_card_page_scripts.md).

A page's policy names `/csp-report`; every browser that blocks (or, in
report-only, would block) something sends a report there. Both shapes are
read: the older `application/csp-report` (`report-uri`) and the Reporting
API's `application/reports+json` (`report-to`). Each kind of violation is one
row, counted; a new kind alerts the platform owner, at most `MOST_A_DAY`
alerts a day. What a browser extension caused is kept and never alerted.

Nothing that identifies the payer is kept: the page's path with tokens and
ids masked, no query string anywhere, no IP address.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

log = logging.getLogger(__name__)

MOST_A_DAY = 20
MOST_BYTES = 16 * 1024
#: What a browser extension or the browser itself does to a page.
NOISE_SCHEMES = ("chrome-extension", "moz-extension", "safari-extension",
                 "safari-web-extension", "webkit-masked-url", "edge-extension", "about")
#: Blocks the inventory expects (docs/card_page_scripts.md): Collect.js adds
#: Apple's Apple Pay script every time it starts, whatever its settings
#: (2026-11-25, its constructor); the card policy blocks it, Apple Pay isn't
#: offered, and the card fields work without it (scripts/card_pages_proof.py).
EXPECTED = {("https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js", "/token/Collect.js")}
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DIGITS = re.compile(r"^\d+$")


def _mask_path(path: str) -> str:
    parts = []
    for part in (path or "/").split("/"):
        if _UUID.match(part) or _DIGITS.match(part):
            parts.append(":id")
        elif _TOKEN.match(part):
            parts.append(":token")
        else:
            parts.append(part)
    return "/".join(parts)[:300] or "/"


def masked(url: str, *, keep_host=True) -> str:
    """An address without its query or fragment, tokens and ids masked.
    Words a browser uses in place of an address ("inline", "eval") stay."""
    url = (url or "").strip()
    if url.lower().startswith(("data:", "blob:")):
        return url[:url.index(":") + 1].lower()
    if not url or ("://" not in url and not url.startswith("/")):
        return url[:60]
    parts = urlsplit(url)
    path = _mask_path(parts.path)
    if not keep_host or not parts.netloc:
        return path
    return f"{parts.scheme}://{parts.netloc}{path}"[:300]


def _from_extension(url: str) -> bool:
    """An extension's address, or the bare word a browser uses for one
    ("chrome-extension")."""
    return (url or "").strip().lower().startswith(NOISE_SCHEMES)


def parse(body: bytes, content_type: str, user_agent: str = "") -> list[dict]:
    """The reports in a request's body, each as one plain dict."""
    try:
        data = json.loads(body.decode("utf-8", "replace") or "null")
    except ValueError:
        return []
    out = []
    if isinstance(data, dict) and isinstance(data.get("csp-report"), dict):
        r = data["csp-report"]
        out.append({
            "document": r.get("document-uri", ""),
            "directive": r.get("effective-directive") or r.get("violated-directive", ""),
            "blocked": r.get("blocked-uri", ""), "source": r.get("source-file", ""),
            "line": r.get("line-number"), "disposition": r.get("disposition", ""),
            "sample": r.get("script-sample", ""), "policy": r.get("original-policy", ""),
            "user_agent": user_agent})
    elif isinstance(data, list):
        for item in data[:20]:
            if not isinstance(item, dict) or item.get("type") != "csp-violation":
                continue
            b = item.get("body") if isinstance(item.get("body"), dict) else {}
            out.append({
                "document": b.get("documentURL") or item.get("url", ""),
                "directive": b.get("effectiveDirective", ""), "blocked": b.get("blockedURL", ""),
                "source": b.get("sourceFile", ""), "line": b.get("lineNumber"),
                "disposition": b.get("disposition", ""), "sample": b.get("sample", ""),
                "policy": b.get("originalPolicy", ""),
                "user_agent": item.get("user_agent") or user_agent})
    return out


def clean(report: dict) -> dict:
    """What is kept of one report."""
    from .policy import BANK, CARD, PLAID_SCRIPT

    blocked, source = str(report.get("blocked") or ""), str(report.get("source") or "")
    line = report.get("line")
    return {
        "document": masked(str(report.get("document") or ""), keep_host=False),
        "directive": str(report.get("directive") or "")[:60],
        "blocked": masked(blocked), "source": masked(source),
        "line": int(line) if isinstance(line, int) or str(line).isdigit() else None,
        "disposition": str(report.get("disposition") or "")[:8],
        "sample": str(report.get("sample") or "")[:80],
        "policy": (BANK if PLAID_SCRIPT in str(report.get("policy") or "") else CARD)
        if report.get("policy") else "",
        "user_agent": str(report.get("user_agent") or "")[:200],
        "noise": (_from_extension(blocked) or _from_extension(source)
                  or any(blocked.split("?")[0] == b and source.split("?")[0].endswith(s)
                         for b, s in EXPECTED)),
    }


def fingerprint(row: dict) -> str:
    key = "|".join(str(row[k]) for k in ("policy", "disposition", "document", "directive",
                                         "blocked", "source"))
    return hashlib.sha256(key.encode()).hexdigest()[:64]


def record(report: dict):
    """Count one report; alert the platform owner if it is a new kind.
    Returns the row."""
    from .models import Violation

    row = clean(report)
    if not row["directive"]:
        return None
    key = fingerprint(row)
    try:
        with transaction.atomic():
            violation = Violation.objects.create(fingerprint=key, **row)
    except IntegrityError:
        Violation.objects.filter(fingerprint=key).update(count=F("count") + 1,
                                                         last_seen=timezone.now())
        return Violation.objects.filter(fingerprint=key).first()
    log.warning("card pages: new policy violation %s blocked %s on %s", violation.directive,
                violation.blocked, violation.document)
    if not violation.noise and _alerts_today() < MOST_A_DAY:
        _alert(violation)
    return violation


def _alerts_today() -> int:
    from .models import Violation

    return Violation.objects.filter(alerted_at__gte=timezone.now() - timedelta(days=1)).count()


def _alert(violation) -> None:
    from . import alerts
    from .models import Violation

    what = violation.blocked or "an inline script"
    enforced = violation.disposition != "report"
    text = (f"A browser {'blocked' if enforced else 'would have blocked (report-only)'} "
            f"{what} ({violation.directive}) on {violation.document}"
            + (f", from {violation.source}" + (f" line {violation.line}" if violation.line
                                               else "") if violation.source else "")
            + f". Page policy: {violation.policy or 'unknown'}. "
            "If it isn't one of the scripts in docs/card_page_scripts.md, something tried "
            "to run on a card page. Details: manage.py card_pages status.")
    alerts.tell(key=f"violation:{violation.fingerprint}",
                title="A card page blocked a script" if enforced
                else "A card page reported a script", text=text)
    Violation.objects.filter(pk=violation.pk).update(alerted_at=timezone.now())
