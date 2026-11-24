"""The owner's side of an agreement: one personal link, no account, the
intake form's look (white label). The token reaches one agreement and is the
whole of the authentication. Every request is counted against the token and
the address, like the intake form's.

GET    /api/fa/<token>            the agreement, as blocks, and the owner's details
PATCH  /api/fa/<token>/details    the owner's section, saved as they go
POST   /api/fa/<token>/sign       {method, typed|drawn, agreed}
POST   /api/fa/<token>/onboarding {choice: now|later} -> {link}
GET    /api/fa/<token>/pdf        the owner's copy (awaiting, or final)
"""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared
from apps.tenancy.context import tenant_context

from . import access, consent, links, render, services, texts

PER_TOKEN = RateLimit(limit=1200, window_seconds=3600, prefix="agreement-token")
PER_ADDRESS = RateLimit(limit=3000, window_seconds=3600, prefix="agreement-ip")
BAD_TOKENS = RateLimit(limit=30, window_seconds=3600, prefix="agreement-bad")
SIGN_TRIES = RateLimit(limit=20, window_seconds=3600, prefix="agreement-sign")
SLOW_DOWN = {"detail": "Too many tries. Please wait a few minutes and try again."}
GONE = {"state": "gone", "detail": "This link isn't valid. Please check the link you were sent."}


def _body(request) -> dict:
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve(request, token):
    ip = client_ip(request)
    if too_many_shared(PER_ADDRESS, ip) or too_many_shared(PER_TOKEN, token):
        return None, JsonResponse(SLOW_DOWN, status=429)
    agreement = links.resolve(token)
    if agreement is None:
        if too_many_shared(BAD_TOKENS, ip):
            return None, JsonResponse(SLOW_DOWN, status=429)
        return None, JsonResponse(GONE, status=404)
    form = getattr(request, "intake_form", None)
    if form is not None and form.company_id != agreement.company_id:
        return None, JsonResponse(GONE, status=404)
    if agreement.voided_at is not None or not access.is_on(agreement.company):
        return None, JsonResponse(GONE, status=404)
    return agreement, None


def _error(exc: services.Refused):
    return JsonResponse({"detail": str(exc)}, status=exc.status)


def page(agreement) -> dict:
    """Everything the owner's pages show. Nothing names the product, the
    practice or anyone in it; SkyRun's side shows only the signer's name."""
    from apps.intake.services import form_for

    from .models import AgreementSignature

    form = form_for(agreement.company)
    terms = services.terms_for(agreement)
    sigs = {s.role: s for s in AgreementSignature.all_objects.filter(agreement=agreement)}
    tpl = texts.get(agreement.template_key)
    details = agreement.details or {}
    version = services.current(agreement)
    staff_address = (version.terms or {}).get("property_address") or {}
    state = ("complete" if agreement.countersigned_at else
             "signed" if agreement.owner_signed_at else "open")
    return {
        "state": state,
        "number": agreement.number,
        "title": tpl.title, "brand_name": form.brand_name,
        "first_name": details.get("first_name") or agreement.owner_name.split(" ")[0],
        "blocks": render.document(agreement.template_key, terms, details,
                                  agreement_date=agreement.agreement_date),
        "terms": {"owner_percent": terms.get("owner_percent"),
                  "manager_percent": terms.get("manager_percent"),
                  "section_30": render.section_30(terms),
                  "property_address": render.one_line(terms.get("property_address"))},
        "staff_address": staff_address,
        "details": details,
        "prefill": {"name": agreement.owner_name, "email": agreement.owner_email,
                    "phone": agreement.owner_phone},
        "missing": services.missing_details(agreement),
        "consent": consent.owner(company=form.brand_name,
                                 email=details.get("email") or agreement.owner_email or
                                 "the email address you give"),
        "signed_at": sigs["owner"].signed_at.isoformat() if "owner" in sigs else None,
        "countersigned_at": agreement.countersigned_at.isoformat()
        if agreement.countersigned_at else None,
        "onboarding_choice": agreement.onboarding_choice,
        "has_pdf": bool(agreement.final_pdf_id or agreement.owner_pdf_id),
        "signer_name": tpl.signer_name,
    }


@csrf_exempt
@require_http_methods(["GET"])
def agreement_page(request, token):
    agreement, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(agreement.tenant_id):
        services.opened(agreement, ip=client_ip(request),
                        user_agent=request.META.get("HTTP_USER_AGENT", ""))
        return JsonResponse(page(agreement))


@csrf_exempt
@require_http_methods(["PATCH"])
def details(request, token):
    agreement, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(agreement.tenant_id):
        try:
            services.save_details(agreement, _body(request).get("details") or {})
        except services.Refused as exc:
            return _error(exc)
        return JsonResponse({"details": agreement.details,
                             "missing": services.missing_details(agreement),
                             "blocks": render.document(agreement.template_key,
                                                       services.terms_for(agreement),
                                                       agreement.details or {})})


@csrf_exempt
@require_http_methods(["POST"])
def sign(request, token):
    agreement, error = _resolve(request, token)
    if error:
        return error
    if too_many_shared(SIGN_TRIES, token):
        return JsonResponse(SLOW_DOWN, status=429)
    data = _body(request)
    with tenant_context(agreement.tenant_id):
        try:
            services.owner_sign(agreement, method=data.get("method", ""),
                                typed=data.get("typed", ""), drawn=data.get("drawn", ""),
                                agreed=data.get("agreed") is True, ip=client_ip(request),
                                user_agent=request.META.get("HTTP_USER_AGENT", ""))
        except services.Refused as exc:
            return _error(exc)
        agreement.refresh_from_db()
        return JsonResponse(page(agreement))


@csrf_exempt
@require_http_methods(["POST"])
def onboarding(request, token):
    agreement, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(agreement.tenant_id):
        try:
            link = services.choose(agreement, _body(request).get("choice", ""))
        except services.Refused as exc:
            return _error(exc)
        return JsonResponse({"link": link, "choice": agreement.onboarding_choice})


@csrf_exempt
@require_http_methods(["GET"])
def owner_pdf(request, token):
    from apps.tenancy import storage

    agreement, error = _resolve(request, token)
    if error:
        return error
    stored = agreement.final_pdf or agreement.owner_pdf
    if stored is None:
        return JsonResponse({"detail": "Your copy isn't ready yet."}, status=404)
    with tenant_context(agreement.tenant_id):
        content = storage.read(stored)
    name = (f"Rental Management Agreement #{agreement.number}.pdf" if agreement.final_pdf_id
            else f"Rental Management Agreement #{agreement.number} (awaiting signature).pdf")
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response
