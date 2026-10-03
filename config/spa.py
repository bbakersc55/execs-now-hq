"""Production serving of the React app (Phase 7), and the health check.

In development the app is the Vite dev server on 5200 and none of this is
reached. In production Django serves the built bundle: WhiteNoise serves
`/static/…` (Vite builds with that base), and every other path that is not an
API or auth route gets `index.html`, so a deep link — a magic link's landing
page, a pre-call form — opens the app at that route.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from django.utils.html import escape

from django.conf import settings
from django.db import connection
from django.http import (
    HttpResponse, HttpResponseNotFound, HttpResponseRedirect, JsonResponse,
)
from django.views.decorators.cache import never_cache


@functools.cache
def _index() -> str | None:
    for base in (Path(settings.STATIC_ROOT), settings.BASE_DIR / "frontend" / "dist"):
        path = base / "index.html"
        if path.is_file():
            return path.read_text()
    return None


@never_cache
def app_shell(request, *args, **kwargs):
    # On the laptop the app is the Vite dev server, always current. A build
    # left in frontend/dist is a snapshot of whenever it was last built, and
    # serving it here showed the owner a two-screens-old page (2026-09-29). So
    # in development every app route goes to the same path on the dev server.
    root = settings.APP_ROOT_URL
    if settings.IS_LOCAL and root.startswith("http"):
        return HttpResponseRedirect(root.rstrip("/") + request.get_full_path())
    html = _index()
    if html is None:
        return HttpResponseNotFound(
            "The app has not been built. Run `npm run build` in frontend/, then "
            "`manage.py collectstatic`.", content_type="text/plain")
    return HttpResponse(with_identity(html, request))


_TITLE = re.compile(r"<title>.*?</title>", re.S)
_ICON = re.compile(r'<link rel="icon"[^>]*>')


def with_identity(html: str, request) -> str:
    """The tab's title and icon for whoever is asking (P1).

    Staff: the product's name and icon. Anyone else — a client user, or a
    visitor who is not signed in — the practice's display name and its mark
    (or its initials), never the product's, from the first byte.
    """
    from config.branding import PRODUCT_NAME

    from apps.accounts.views import STAFF_ROLES, _branding_tenant, tenant_branding

    membership = getattr(request, "membership", None)
    if membership is not None and membership.role in STAFF_ROLES:
        title = PRODUCT_NAME
        static = settings.STATIC_URL if settings.STATIC_URL.startswith("/") \
            else "/" + settings.STATIC_URL
        icons = (f'<link rel="icon" href="{static}brand/favicon.ico" sizes="any" />'
                 f'<link rel="icon" type="image/png" href="{static}brand/favicon-32.png" />'
                 f'<link rel="apple-touch-icon" href="{static}brand/apple-touch-icon.png" />')
    else:
        tenant = _branding_tenant(request)
        title = tenant_branding(tenant)["display_name"] or "Portal"
        icons = '<link rel="icon" href="/api/branding/mark" />'
    html = _TITLE.sub(f"<title>{escape(title)}</title>", html, count=1)
    return _ICON.sub(icons, html, count=1)


@never_cache
def healthz(request):
    """For Railway's health check: the process answers and the database does.
    Nothing about the tenant, the queue or the mail — a health check that
    fails for a reason a restart cannot fix just restarts the app in a loop."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"ok": True})
