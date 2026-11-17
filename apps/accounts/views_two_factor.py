"""Two-factor sign-in's routes (2026-11-17, `apps/accounts/two_factor.py`).

Under `/api/me/two-factor`: the person's own, from Profile and the code
prompt after sign-in. Under `/api/two-factor/`: a practice owner's or a client
owner's resets; under `/api/platform/two-factor/`: the platform owner's, for
practice owners. Nobody sets up or turns off two-factor for someone else, and
nobody does anything here while acting as someone else.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from apps.accounts import two_factor as tf


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _signed_in(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    if getattr(request, "acting_as", None) is not None:
        return JsonResponse({"detail": "You are acting as someone else. Their sign-in is "
                                       "theirs."}, status=403)
    return None


def _refused(exc: tf.TwoFactorRefused):
    return JsonResponse({"detail": str(exc)}, status=exc.status)


@csrf_protect
@require_http_methods(["GET"])
def state(request):
    if (refused := _signed_in(request)):
        return refused
    return JsonResponse(tf.state(request))


@csrf_protect
@require_http_methods(["POST"])
def start(request):
    if (refused := _signed_in(request)):
        return refused
    try:
        return JsonResponse(tf.start(request.user))
    except tf.TwoFactorRefused as exc:
        return _refused(exc)


@csrf_protect
@require_http_methods(["POST"])
def confirm(request):
    if (refused := _signed_in(request)):
        return refused
    try:
        codes = tf.confirm(request.user, _body(request).get("code"), request=request)
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse({**tf.state(request), "backup_codes": codes})


@csrf_protect
@require_http_methods(["POST"])
def verify(request):
    """The code asked for after sign-in, and again on a People screen."""
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    try:
        kind = tf.verify(request, _body(request).get("code"))
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse({"verified": True, "kind": kind,
                         **({"backup_codes_left": tf.state(request)["backup_codes_left"]}
                            if kind == "backup" else {})})


@csrf_protect
@require_http_methods(["POST"])
def backup_codes(request):
    if (refused := _signed_in(request)):
        return refused
    try:
        codes = tf.replace_backup_codes(request, _body(request).get("code"))
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse({**tf.state(request), "backup_codes": codes})


@csrf_protect
@require_http_methods(["POST"])
def turn_off(request):
    if (refused := _signed_in(request)):
        return refused
    try:
        tf.turn_off(request, _body(request).get("code"))
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse(tf.state(request))


# ------------------------------------------------------------- resets

def _person(membership) -> dict:
    from apps.tenancy.roles import role_label

    company = membership.client_company if membership.client_company_id else None
    return {"membership": str(membership.pk),
            "name": membership.user.full_name or membership.user.email,
            "email": membership.user.email, "role_label": role_label(membership.role),
            "company": company.name if company else ""}


def _resettable(actor):
    from apps.accounts.models import TwoFactor
    from apps.tenancy.models import Membership

    enrolled = set(TwoFactor.objects.filter(confirmed_at__isnull=False)
                   .values_list("user_id", flat=True))
    rows = (Membership.all_objects.filter(tenant_id=actor.tenant_id, revoked_at__isnull=True,
                                          user_id__in=enrolled)
            .select_related("user", "client_company").order_by("user__full_name"))
    return [m for m in rows if tf.may_reset(actor, m)]


@csrf_protect
@require_http_methods(["GET", "POST"])
def resets(request):
    """GET: who this person may reset (with two-factor on); POST
    {membership}: reset it. A practice owner: their team and their clients'
    users; a client owner: their own people."""
    from apps.tenancy.models import Membership

    if (refused := _signed_in(request)):
        return refused
    actor = getattr(request, "membership", None)
    if actor is None or actor.role not in ("FF", "FCC"):
        return JsonResponse({"detail": "Not found."}, status=404)
    if request.method == "GET":
        return JsonResponse({"people": [_person(m) for m in _resettable(actor)]})
    target = Membership.all_objects.filter(pk=_body(request).get("membership"),
                                           revoked_at__isnull=True).select_related(
        "user").first() if _uuid(_body(request).get("membership")) else None
    if target is None or not tf.may_reset(actor, target):
        return JsonResponse({"detail": "Not found."}, status=404)
    try:
        tf.reset(target.user, actor=request.user, tenant=actor.tenant)
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse({"reset": True, "people": [_person(m) for m in _resettable(actor)]})


@csrf_protect
@require_http_methods(["GET", "POST"])
def platform_resets(request):
    """The platform owner, in the Practices area: practice owners only."""
    from apps.accounts.models import TwoFactor
    from apps.tenancy.models import Membership

    if (refused := _signed_in(request)):
        return refused
    if not request.user.is_platform_owner or getattr(request, "area", "") != "platform":
        return JsonResponse({"detail": "Not found."}, status=404)
    enrolled = set(TwoFactor.objects.filter(confirmed_at__isnull=False)
                   .values_list("user_id", flat=True))
    owners = (Membership.all_objects.filter(role="FF", revoked_at__isnull=True,
                                            user_id__in=enrolled)
              .exclude(user=request.user).select_related("user", "tenant"))
    if request.method == "GET":
        return JsonResponse({"people": [
            {**_person(m), "practice": m.tenant.name} for m in owners]})
    target = owners.filter(pk=_body(request).get("membership")).first() \
        if _uuid(_body(request).get("membership")) else None
    if target is None:
        return JsonResponse({"detail": "Not found."}, status=404)
    try:
        tf.reset(target.user, actor=request.user, tenant=target.tenant, by_platform=True)
    except tf.TwoFactorRefused as exc:
        return _refused(exc)
    return JsonResponse({"reset": True})


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
