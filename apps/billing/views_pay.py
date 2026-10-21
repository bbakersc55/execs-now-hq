"""The pay page behind the signed link (P4 part 3): no sign-in, no role.

The token is the whole of the authentication, and it reaches one invoice:
the practice's name, the invoice's number, the amount due, the due date, its
PDF as emailed, and the card form. Nothing else is in any answer here. A
wrong token, a voided invoice's, or one not yet sent is a 404, the same
404 for each. Every request is counted against the token and the address.
"""

from __future__ import annotations

import json

from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.response import Response

from apps.accounts.ratelimit import RateLimit, too_many
from apps.billing import card_payments, pay_links, services
from apps.billing.models import ClientInvoice, PaymentAttempt
from apps.tenancy.context import tenant_context

NOT_FOUND = {"detail": "This payment link is not valid. Ask the practice that sent the "
                       "invoice for a new one."}
SLOW_DOWN = {"detail": "Too many tries. Please wait a few minutes and try again."}

#: A page looked at, or its PDF fetched; and a card tried. Per link, and per
#: address so a run of guessed links is cut off too.
_VIEWS_PER_LINK = RateLimit(limit=60, window_seconds=3600, prefix="pay-link")
_CHARGES_PER_LINK = RateLimit(limit=10, window_seconds=3600, prefix="pay-link-charge")
_PER_ADDRESS = RateLimit(limit=120, window_seconds=3600, prefix="pay-ip")


def _limited(request, token, *, charge=False) -> bool:
    ip = request.META.get("REMOTE_ADDR")
    return (too_many(_PER_ADDRESS, ip) or too_many(_VIEWS_PER_LINK, token)
            or (charge and too_many(_CHARGES_PER_LINK, token)))


def _page(invoice) -> dict:
    via = PaymentAttempt.Via.LINK
    payable = card_payments.can_pay(invoice, via=via)
    config = card_payments.pay_config(invoice, via=via) if payable else {}
    return {
        "practice": services.practice_name(invoice.tenant),
        "number": invoice.number,
        "amount_due_cents": invoice.balance_cents,
        "due_date": invoice.due_date.isoformat(),
        "paid": invoice.status == ClientInvoice.Status.PAID,
        "test_mode": card_payments.is_test_mode(invoice.tenant),
        "public_key": config.get("public_key", ""),
        # Why there is no card form, when there is none and it is not paid.
        "notice": ("" if payable or invoice.status == ClientInvoice.Status.PAID
                   else card_payments._why_not(invoice)),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def pay_page(request, token: str):
    if _limited(request, token, charge=request.method == "POST"):
        return JsonResponse(SLOW_DOWN, status=429)
    invoice = pay_links.invoice_for(token)
    if invoice is None:
        return JsonResponse(NOT_FOUND, status=404)
    with tenant_context(invoice.tenant_id):
        if request.method == "GET":
            return JsonResponse(_page(invoice))
        try:
            body = json.loads(request.body or "{}")
        except ValueError:
            return JsonResponse({"detail": "Unreadable request."}, status=400)
        try:
            attempt, message = card_payments.pay(
                invoice, payer=None, payment_token=body.get("payment_token"),
                via=PaymentAttempt.Via.LINK)
        except card_payments.PaymentRefused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        invoice.refresh_from_db()
        return JsonResponse({"status": attempt.status, "message": message,
                             "balance_cents": invoice.balance_cents,
                             "invoice_status": invoice.status})


@require_http_methods(["GET"])
def pay_pdf(request, token: str):
    from apps.billing.views import pdf_response

    if _limited(request, token):
        return JsonResponse(SLOW_DOWN, status=429)
    invoice = pay_links.invoice_for(token)
    if invoice is None:
        raise Http404
    with tenant_context(invoice.tenant_id):
        response = pdf_response(invoice)
    if isinstance(response, Response):
        # Storage unreadable: DRF's answer, outside a DRF view, as plain JSON.
        return JsonResponse(response.data, status=response.status_code)
    return response
