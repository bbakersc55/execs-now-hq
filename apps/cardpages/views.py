"""`/csp-report`: where browsers send policy violations from the app's pages
(docs/p16_card_page_scripts.md). Outside /api/, so no gate of the app's
stands in a report's way. Unsigned and unauthenticated by nature: what it is
sent is only ever stored as text, cut short, rate-limited by address."""

from __future__ import annotations

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared

from . import reports

PER_ADDRESS = RateLimit(limit=120, window_seconds=3600, prefix="csp-report")


@csrf_exempt
@require_POST
def csp_report(request):
    if len(request.body or b"") > reports.MOST_BYTES:
        return HttpResponse(status=413)
    if too_many_shared(PER_ADDRESS, client_ip(request)):
        return HttpResponse(status=429)
    agent = request.headers.get("User-Agent", "")
    for report in reports.parse(request.body, request.content_type, agent):
        reports.record(report)
    return HttpResponse(status=204)
