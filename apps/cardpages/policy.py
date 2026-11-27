"""The content security policy of the app's pages (docs/p16_card_page_scripts.md).

The React app is one document per page load: moving around inside it never
asks the server again. So the policy can't be put on the card routes alone.
Every page of the app gets the **card policy**: scripts from ENHQ's own
origin and the gateway's Collect.js, nothing else. The three bank pages
(where "Connect a bank" opens Plaid) get the **bank policy**: the same, plus
Plaid's one script. A card form never shows on a bank page, and moving
between the two kinds reloads the page (`frontend/src/lib/pagePolicy.ts`), so
whatever way someone reaches a card screen, the page around it has the card
policy and no script from anywhere else.

`SCRIPTS` is the inventory: every script source either policy allows, with
why. docs/card_page_scripts.md lists the same, and
tests/test_card_pages_inventory.py fails if the two part.
"""

from __future__ import annotations

import re

from django.conf import settings

CARD, BANK = "card", "bank"

#: The bank pages, as the app's routes (frontend/src/lib/pagePolicy.ts has
#: the same list; tests/test_card_pages_inventory.py compares them).
BANK_PATHS = ("/finance/import", "/finance/personal/import", "/settings/finance")

PLAID_SCRIPT = "https://cdn.plaid.com/link/v2/stable/link-initialize.js"
PLAID_FRAMES = "https://cdn.plaid.com"

#: Every script source a page may load, where, and why. "when" says when the
#: source is part of this server's policy.
SCRIPTS = (
    {"source": "'self'", "pages": (CARD, BANK), "when": "always",
     "what": "ENHQ's own scripts: the app's bundle from /static/assets/, including NMI's "
             "Payment Component (npm @nmipayments/nmi-pay, pinned), which is built into it"},
    {"source": "https://secure.vaultixpay.com/token/Collect.js", "pages": (CARD, BANK),
     "when": "NMI_API_HOST is secure.vaultixpay.com",
     "what": "Collect.js, the gateway's card fields, from the processor's white-label host"},
    {"source": "https://secure.nmi.com/token/Collect.js", "pages": (CARD, BANK),
     "when": "NMI_SANDBOX_CARD_FORM_HOST is secure.nmi.com (laptop only)",
     "what": "Collect.js from NMI's own host, for the laptop's sandbox proof of that form"},
    {"source": PLAID_SCRIPT, "pages": (BANK,), "when": "always (bank pages only)",
     "what": "Plaid Link, which connects a bank account; Plaid requires its own script"},
)


def kind_for(path: str) -> str:
    """The policy a page at `path` is served with."""
    clean = "/" + path.strip("/")
    return BANK if clean in BANK_PATHS else CARD


def gateway_scripts() -> list[str]:
    """The Collect.js addresses this server's settings can put on a page:
    the live white-label host's, and on the laptop the sandbox's chosen one.
    NMI's Payment Component is part of ENHQ's own bundle and needs none."""
    from apps.billing import gateway as gw

    out = []
    for environment in ("live", "sandbox"):
        form = gw.card_form(environment)
        if form.get("kind") == "collect" and form["script_url"] not in out:
            out.append(form["script_url"])
    return out


def gateway_frames() -> list[str]:
    """The gateway's hosts whose frames hold the card fields: NMI's own (the
    Payment Component's fields) and each Collect.js host in use."""
    from apps.billing import gateway as gw

    hosts = [f"https://{gw.COMPONENT_HOST}"]
    for url in gateway_scripts():
        origin = re.match(r"https://[^/]+", url).group(0)
        if origin not in hosts:
            hosts.append(origin)
    return hosts


def directives(kind: str, report_url: str) -> list[tuple[str, list[str]]]:
    scripts = ["'self'", "'report-sample'", *gateway_scripts()]
    frames = ["'self'", "blob:", *gateway_frames()]
    if kind == BANK:
        scripts.append(PLAID_SCRIPT)
        frames.append(PLAID_FRAMES)
    return [
        ("script-src", scripts),
        ("frame-src", frames),
        ("worker-src", ["'self'"]),
        ("object-src", ["'none'"]),
        ("base-uri", ["'self'"]),
        ("frame-ancestors", ["'none'"]),
        ("report-uri", [report_url]),
        ("report-to", ["card-pages"]),
    ]


def value(kind: str, report_url: str) -> str:
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in
                     directives(kind, report_url))


def mode() -> str:
    """"enforce" or "report-only" (`card_pages mode`), enforce when unset."""
    from .models import Mode, Setting

    row = Setting.objects.filter(pk=1).only("mode").first()
    return row.mode if row is not None else Mode.ENFORCE


def headers(kind: str, report_url: str, current_mode: str | None = None) -> dict[str, str]:
    """The response headers for a page of the app served with `kind`."""
    from .models import Mode

    name = ("Content-Security-Policy-Report-Only"
            if (current_mode or mode()) == Mode.REPORT_ONLY else "Content-Security-Policy")
    return {name: value(kind, report_url),
            "Reporting-Endpoints": f'card-pages="{report_url}"'}


MARKER = '<meta name="enhq-page-policy" content="{kind}" />'


def mark(html: str, kind: str) -> str:
    """The page tells the app which policy it was served with."""
    return html.replace("<head>", "<head>" + MARKER.format(kind=kind), 1)


def report_url(request) -> str:
    return request.build_absolute_uri("/csp-report")


def apply(response, request, path: str) -> None:
    """Put the page's policy on an app page's response."""
    kind = kind_for(path)
    for name, text in headers(kind, report_url(request)).items():
        response[name] = text


def public_report_url() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/") + "/csp-report"
