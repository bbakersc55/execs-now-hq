"""The signing page behind the emailed link (`/sign/<token>`): no sign-in.

The token is the whole of the authentication, and it reaches one document:
its title, the practice's name, the signer's name and email, the consent
wording, and its PDF. Nothing else is in any answer here. A wrong token, a
used one (signed or declined), a voided document's or an expired one is the
same 404. Every request is counted against the token and the address.

GET   /api/sign/<token>           the page; the first one makes it Viewed
POST  /api/sign/<token>           {agreed, method, typed | drawn}: sign
GET   /api/sign/<token>/pdf       the PDF as sent
POST  /api/sign/<token>/decline   {reason}
"""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.accounts.ratelimit import RateLimit, client_ip, too_many
from apps.esign import links, services
from apps.tenancy.context import tenant_context

NOT_FOUND = {"detail": "This signing link is not valid any more. It may have been used, "
                       "or the document withdrawn or expired. Ask the practice that sent it "
                       "for a new one."}
SLOW_DOWN = {"detail": "Too many tries. Please wait a few minutes and try again."}

_VIEWS_PER_LINK = RateLimit(limit=60, window_seconds=3600, prefix="sign-link")
_ACTS_PER_LINK = RateLimit(limit=10, window_seconds=3600, prefix="sign-link-act")
_PER_ADDRESS = RateLimit(limit=120, window_seconds=3600, prefix="sign-ip")


def _limited(request, token, *, acting=False) -> bool:
    ip = client_ip(request)
    return (too_many(_PER_ADDRESS, ip) or too_many(_VIEWS_PER_LINK, token)
            or (acting and too_many(_ACTS_PER_LINK, token)))


def _agent(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:500]


def _body(request) -> dict:
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@csrf_exempt
@require_http_methods(["GET", "POST"])
def sign_page(request, token: str):
    if _limited(request, token, acting=request.method == "POST"):
        return JsonResponse(SLOW_DOWN, status=429)
    document = links.document_for(token)
    if document is None:
        return JsonResponse(NOT_FOUND, status=404)
    ip = client_ip(request)
    with tenant_context(document.tenant_id):
        if request.method == "GET":
            document = services.viewed(document, ip=ip, user_agent=_agent(request))
            return JsonResponse(services.page_for(document))
        data = _body(request)
        try:
            document = services.sign(document, method=data.get("method", ""),
                                     typed=data.get("typed", ""), drawn=data.get("drawn", ""),
                                     agreed=data.get("agreed") is True, ip=ip,
                                     user_agent=_agent(request))
        except services.DocumentRefused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"state": document.state,
                             "detail": f"Signed. {document.tenant.name} will countersign it "
                                       f"and email the signed copy to {document.signer_email}."})


@require_http_methods(["GET"])
def sign_pdf(request, token: str):
    from apps.tenancy import storage

    if _limited(request, token):
        return JsonResponse(SLOW_DOWN, status=429)
    document = links.document_for(token)
    if document is None:
        return JsonResponse(NOT_FOUND, status=404)
    with tenant_context(document.tenant_id):
        try:
            content = storage.read(document.pdf)
        except storage.StorageError:
            return JsonResponse({"detail": "The document could not be read just now. Try "
                                           "again in a minute."}, status=503)
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{services._filename(document.title)}"'
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["POST"])
def sign_decline(request, token: str):
    if _limited(request, token, acting=True):
        return JsonResponse(SLOW_DOWN, status=429)
    document = links.document_for(token)
    if document is None:
        return JsonResponse(NOT_FOUND, status=404)
    with tenant_context(document.tenant_id):
        try:
            document = services.decline(document, reason=_body(request).get("reason", ""),
                                        ip=client_ip(request), user_agent=_agent(request))
        except services.DocumentRefused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
    return JsonResponse({"state": document.state,
                         "detail": f"Declined. {document.tenant.name} has been told why."})
