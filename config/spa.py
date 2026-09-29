"""Production serving of the React app (Phase 7), and the health check.

In development the app is the Vite dev server on 5200 and none of this is
reached. In production Django serves the built bundle: WhiteNoise serves
`/static/…` (Vite builds with that base), and every other path that is not an
API or auth route gets `index.html`, so a deep link — a magic link's landing
page, a pre-call form — opens the app at that route.
"""

from __future__ import annotations

import functools
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
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
    html = _index()
    if html is None:
        return HttpResponseNotFound(
            "The app has not been built. Run `npm run build` in frontend/, then "
            "`manage.py collectstatic`.", content_type="text/plain")
    return HttpResponse(html)


@never_cache
def healthz(request):
    """For Railway's health check: the process answers and the database does.
    Nothing about the tenant, the queue or the mail — a health check that
    fails for a reason a restart cannot fix just restarts the app in a loop."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"ok": True})
