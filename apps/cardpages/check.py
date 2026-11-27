"""The card pages' change and tamper check (docs/p16_card_page_scripts.md).

`observe` loads each card route the way a browser gets it (the page, its
security headers, then every script it loads: ENHQ's entry script, each part
the bundle loads later, found by following its imports, and the gateway's
Collect.js the policy names) and hashes each script's content. `compare`
sets that beside the approved state. `run` does both, records the check, and
alerts the platform owner on a difference that is new, and weekly while one
stands unapproved. `approve` records what is live now as approved: the
deliberate step after a release (`manage.py card_pages approve`).

Reading the page does not run it: a script added only by another script's
code, at run time, is not seen here. That is what the policy blocks and what
browsers report (`reports.py`).
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.utils import timezone

#: The card screens' routes: the pay link (any token: the page is the same),
#: the client's Invoices (in-app payment, the card on file, automatic
#: billing's card) and the practice owner's Billing settings (the
#: subscription card).
PAGES = ("/pay/card-page-check", "/invoices", "/settings/billing")
#: The security headers compared, by lower-case name.
HEADERS = ("content-security-policy", "content-security-policy-report-only",
           "reporting-endpoints", "x-frame-options", "x-content-type-options",
           "referrer-policy", "strict-transport-security", "permissions-policy",
           "cross-origin-opener-policy")
MOST_SCRIPTS = 400
TIMEOUT = 20
AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/131.0 Safari/537.36 ENHQ-card-page-check")
REMIND_AFTER = timedelta(days=7)

_SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.I)
_PRELOAD_TAG = re.compile(r"<link\b[^>]*rel=[\"']?modulepreload[^>]*>", re.I)
_ATTR = re.compile(r"""\b(src|href|integrity)\s*=\s*["']([^"']*)["']""", re.I)
_INLINE = re.compile(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.I | re.S)
_JS_REF = re.compile(r"""["'`]((?:\.{1,2}/|/static/)[A-Za-z0-9_./-]+\.js)["'`]""")
_MAPDEPS = re.compile(r"""["'`](assets/[A-Za-z0-9_.-]+\.js)["'`]""")


class Unreadable(Exception):
    pass


def fetch(url: str, *, accept: str) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, headers={
        "User-Agent": AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return (response.status, {k.lower(): v for k, v in response.headers.items()},
                    response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Unreadable(f"{url} could not be read: {exc}") from None


def _tags(html: str):
    """(src, integrity) of each script and module preload in a page."""
    out = []
    for tag in _SCRIPT_TAG.findall(html) + _PRELOAD_TAG.findall(html):
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        src = attrs.get("src") or attrs.get("href")
        if src:
            out.append((src, attrs.get("integrity", "")))
    return out


def _imports(url: str, text: str, static_base: str) -> list[str]:
    found = [urljoin(url, ref) for ref in _JS_REF.findall(text)]
    found += [urljoin(static_base, ref) for ref in _MAPDEPS.findall(text)]
    return found


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def observe(base_url: str, *, fetcher=None) -> dict:
    """What a browser gets on the card pages now."""
    from .policy import gateway_scripts

    fetcher = fetcher or fetch
    base = base_url.rstrip("/")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    static_base = urljoin(origin + "/", settings.STATIC_URL.lstrip("/"))
    pages, queue = {}, []
    for path in PAGES:
        status, headers, body = fetcher(base + path, accept="text/html,application/xhtml+xml")
        html = body.decode("utf-8", "replace")
        tags = _tags(html)
        pages[path] = {
            "status": status,
            "headers": {name: headers.get(name, "") for name in HEADERS},
            "scripts": [urljoin(base + path, src) for src, _ in tags],
            "integrity": {urljoin(base + path, src): sri for src, sri in tags if sri},
            "inline_scripts": [_sha(text.encode()) for text in _INLINE.findall(html)
                               if text.strip()],
        }
        queue += pages[path]["scripts"]
    queue += gateway_scripts()
    scripts, seen = {}, set()
    while queue and len(scripts) < MOST_SCRIPTS:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        status, headers, body = fetcher(url, accept="*/*")
        ours = url.startswith(origin + "/")
        scripts[url] = {"status": status, "sha256": _sha(body), "bytes": len(body),
                        "ours": ours}
        if ours and status == 200:
            queue += _imports(url, body.decode("utf-8", "replace"), static_base)
    return {"base_url": base, "pages": pages, "scripts": scripts}


def compare(approved: dict, now: dict) -> list[str]:
    """The differences, each a sentence."""
    out = []
    for path in sorted(set(approved.get("pages", {})) | set(now.get("pages", {}))):
        a, b = approved.get("pages", {}).get(path), now.get("pages", {}).get(path)
        if a is None or b is None:
            out.append(f"{path}: {'new page' if a is None else 'no longer checked'}")
            continue
        if a["status"] != b["status"]:
            out.append(f"{path}: answered {b['status']}, approved {a['status']}")
        for name in HEADERS:
            if a["headers"].get(name, "") != b["headers"].get(name, ""):
                out.append(f"{path}: header {name} is now "
                           f"{json.dumps(b['headers'].get(name, '') or '(none)')}, approved "
                           f"{json.dumps(a['headers'].get(name, '') or '(none)')}")
        if sorted(a["scripts"]) != sorted(b["scripts"]):
            out.append(f"{path}: loads {', '.join(sorted(b['scripts'])) or 'no script'}; "
                       f"approved {', '.join(sorted(a['scripts'])) or 'no script'}")
        if a.get("integrity", {}) != b.get("integrity", {}):
            out.append(f"{path}: the scripts' integrity hashes changed")
        if sorted(a.get("inline_scripts", [])) != sorted(b.get("inline_scripts", [])):
            out.append(f"{path}: its inline scripts changed")
    sa, sb = approved.get("scripts", {}), now.get("scripts", {})
    for url in sorted(set(sb) - set(sa)):
        out.append(f"new script {url} (sha256 {sb[url]['sha256'][:16]}…)")
    for url in sorted(set(sa) - set(sb)):
        out.append(f"script no longer loaded: {url}")
    for url in sorted(set(sa) & set(sb)):
        if sa[url]["sha256"] != sb[url]["sha256"] or sa[url]["status"] != sb[url]["status"]:
            out.append(f"script changed: {url} (sha256 now {sb[url]['sha256'][:16]}…, approved "
                       f"{sa[url]['sha256'][:16]}…; status {sb[url]['status']})")
    return out


def release_files(state: dict) -> dict:
    """For each of ENHQ's own scripts that differs: whether this server's own
    release has a file with exactly that content (a deploy not yet approved),
    or not (changed somewhere else). Empty where the files aren't here."""
    root = Path(settings.STATIC_ROOT)
    if not root.is_dir():
        return {}
    prefix = "/" + settings.STATIC_URL.strip("/") + "/"
    out = {}
    for url, row in state.get("scripts", {}).items():
        if not row.get("ours"):
            continue
        path = urlsplit(url).path
        if not path.startswith(prefix):
            continue
        local = root / path[len(prefix):]
        out[url] = local.is_file() and _sha(local.read_bytes()) == row["sha256"]
    return out


def _fingerprint(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def current_baseline():
    from .models import Baseline

    return Baseline.objects.order_by("-approved_at", "-pk").first()


def run(*, base_url: str | None = None, fetcher=None, alert=True):
    """One check: read, compare, record, and alert when it is due."""
    from .models import Check

    base_url = (base_url or settings.PUBLIC_BASE_URL).rstrip("/")
    baseline = current_baseline()
    try:
        state = observe(base_url, fetcher=fetcher)
    except Unreadable as exc:
        check = Check.objects.create(base_url=base_url, outcome=Check.Outcome.ERROR,
                                     baseline=baseline, error=str(exc)[:2000],
                                     fingerprint=_fingerprint([f"error {timezone.localdate()}"]))
        _maybe_alert(check, alert, [str(exc)])
        return check
    if baseline is None:
        check = Check.objects.create(base_url=base_url, outcome=Check.Outcome.NO_BASELINE,
                                     state=state, fingerprint=_fingerprint(["no baseline"]))
        _maybe_alert(check, alert, ["Nothing has been approved yet. Look at what the pages "
                                    "load now (card_pages check) and approve it "
                                    "(card_pages approve)."])
        return check
    lines = compare(baseline.state, state)
    if not lines:
        return Check.objects.create(base_url=base_url, outcome=Check.Outcome.SAME,
                                    baseline=baseline, state=state)
    mine = release_files(state)
    changed_ours = [url for url in mine if any(url in line for line in lines)]
    if changed_ours:
        if all(mine[url] for url in changed_ours):
            lines.append("ENHQ's changed scripts are exactly the files of the release now "
                         "running: a deploy not yet approved.")
        else:
            lines.append("Some of ENHQ's scripts as served match no file of the release now "
                         "running: " + ", ".join(u for u in changed_ours if not mine[u]))
    check = Check.objects.create(base_url=base_url, outcome=Check.Outcome.CHANGED,
                                 baseline=baseline, state=state, differences=lines,
                                 fingerprint=_fingerprint(lines))
    _maybe_alert(check, alert, lines)
    return check


def _maybe_alert(check, alert: bool, lines: list[str]) -> None:
    """Alert when this finding is new, or a week has passed since it was
    last alerted."""
    from . import alerts
    from .models import Check

    if not alert:
        return
    last = (Check.objects.filter(fingerprint=check.fingerprint, alerted=True)
            .exclude(pk=check.pk).order_by("-ran_at").first())
    if last is not None and check.ran_at - last.ran_at < REMIND_AFTER:
        return
    titles = {Check.Outcome.ERROR: "The card page check could not read the pages",
              Check.Outcome.NO_BASELINE: "The card pages have no approved state",
              Check.Outcome.CHANGED: "The card pages changed"}
    shown = lines[:12] + ([f"…and {len(lines) - 12} more"] if len(lines) > 12 else [])
    text = (" · ".join(shown))[:430] + (
        " Approve after a release: card_pages approve." if check.outcome
        == Check.Outcome.CHANGED else "")
    alerts.tell(key=f"check:{check.fingerprint}:{check.ran_at:%Y-%m-%d}",
                title=titles[check.outcome], text=text)
    Check.objects.filter(pk=check.pk).update(alerted=True)
    check.alerted = True


def approve(*, note: str, by: str, base_url: str | None = None, fetcher=None):
    """What is live now, recorded as approved. Returns (baseline, the
    differences from the one before)."""
    from .models import Baseline

    base_url = (base_url or settings.PUBLIC_BASE_URL).rstrip("/")
    state = observe(base_url, fetcher=fetcher)
    before = current_baseline()
    lines = compare(before.state, state) if before is not None else ["(the first approval)"]
    row = Baseline.objects.create(base_url=base_url, state=state, note=note[:300],
                                  approved_by=by[:120])
    return row, lines
