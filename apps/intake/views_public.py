"""The owner's side: the form behind a personal link, with no account.

The token is the whole of the authentication, and it reaches one submission.
Answers are saved as they go. Nothing here names the practice, the product or
anyone in the practice (white label, owner 2026-11-19): only the form's own
brand and contact line. Every request is counted against the token and the
address; an address that keeps guessing tokens is stopped quickly.

GET    /api/f/<token>                the form, the owner's answers so far
PATCH  /api/f/<token>/answers        {section, value}
POST   /api/f/<token>/secret         {kind, slot, value}; DELETE {kind, slot}
POST   /api/f/<token>/files          multipart "file"; DELETE /files/<id>
POST   /api/f/<token>/submit
POST   /api/f/<token>/another        "Add another property", after submitting
GET    /api/forms/<slug>/logo|icon   the form's images
"""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared
from apps.tenancy.context import tenant_context

from . import derive, hosts, links, schema, services, tracklists, vault

PER_TOKEN = RateLimit(limit=2400, window_seconds=3600, prefix="intake-token")
PER_ADDRESS = RateLimit(limit=3000, window_seconds=3600, prefix="intake-ip")
BAD_TOKENS = RateLimit(limit=30, window_seconds=3600, prefix="intake-bad")
SLOW_DOWN = {"detail": "Too many tries. Please wait a few minutes and try again."}
GONE = {"state": "gone", "detail": "This link isn't valid. Please check the link you were sent."}


def _limited(request, token) -> bool:
    ip = client_ip(request)
    return too_many_shared(PER_ADDRESS, ip) or too_many_shared(PER_TOKEN, token)


def _body(request) -> dict:
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve(request, token):
    """(submission, error response). Expired links say so; unknown ones 404."""
    if _limited(request, token):
        return None, JsonResponse(SLOW_DOWN, status=429)
    submission = links.resolve(token)
    if submission is None:
        if too_many_shared(BAD_TOKENS, client_ip(request)):
            return None, JsonResponse(SLOW_DOWN, status=429)
        return None, JsonResponse(GONE, status=404)
    form = getattr(request, "intake_form", None)
    if form is not None and form.pk != submission.form_id:
        return None, JsonResponse(GONE, status=404)
    # Switched off (or the company gone): as if the link never existed.
    if submission.discarded_at is not None or not hosts.company_on(submission.company):
        return None, JsonResponse(GONE, status=404)
    if not submission.link_open:
        brand = submission.form.brand_name
        return None, JsonResponse({"state": "expired",
                                   "detail": f"This link has expired. Please ask {brand} for a "
                                             "new one."}, status=410)
    return submission, None


def _bed_types(lists, settings):
    out = []
    for bed in lists.get("bed_types") or []:
        if not bed.get("isActive", True):
            continue
        row = (settings.get("sleeps") or {}).get(str(bed["id"])) or {}
        out.append({"id": bed["id"], "label": row.get("label") or bed["name"],
                    "sleeps": row.get("sleeps", 2), "other_places": bool(row.get("other_places"))})
    return out


def owner_form(submission) -> dict:
    """What the owner's form is drawn from: the form's choices, read from the
    last copy of Track's lists, and the owner-facing settings."""
    form = submission.form
    lists, _ = tracklists.stored(submission.company)
    settings = services.settings_of(form, lists)
    hidden = set(settings.get("hidden_groups") or [])
    groups = {}
    for amenity in lists.get("amenities") or []:
        if amenity.get("group") in hidden:
            continue
        groups.setdefault(amenity.get("group") or "Other", []).append(
            {"id": amenity["id"], "name": amenity["name"]})
    offered_lodging = set(settings.get("lodging_type_ids") or [])
    offered_codes = set(settings.get("code_type_ids") or [])
    states = settings.get("custom_fields") or {}
    owner_fields = []
    for field in lists.get("custom_fields") or []:
        state = states.get(field.get("reference")) or {}
        if state.get("state") != "owner" or field["reference"] in schema.BUILTIN_FIELDS:
            continue
        owner_fields.append({"reference": field["reference"],
                             "label": state.get("label") or field["name"],
                             "help": state.get("help") or "", "type": field.get("type"),
                             "section": state.get("section") or "home",
                             "options": [{"value": v["handle"], "label": v["name"]}
                                         for v in field.get("values") or []]})
    trash_days = derive.field_def(lists, "pms_units_trash_pickup_day") or {}
    return {
        "sections": [{"key": k, "title": t} for k, t in schema.SECTIONS],
        "options": {k: [{"value": a, "label": b} for a, b in v]
                    for k, v in schema.OPTIONS.items()},
        "builtin": {ref: (states.get(ref) or {}).get("state", "off") == "owner"
                    for ref in schema.BUILTIN_FIELDS},
        "bed_types": _bed_types(lists, settings),
        "bathroom_fixtures": [{"id": f["id"], "name": f["name"],
                               "kind": derive.fixture_kind(f["name"])}
                              for f in lists.get("bathroom_amenities") or []
                              if f.get("isActive", True)],
        "common_amenities": [{"key": c["key"], "label": c["label"]}
                             for c in settings.get("common_amenities") or []],
        "amenity_groups": [{"name": g, "amenities": sorted(a, key=lambda x: x["name"])}
                           for g, a in sorted(groups.items())],
        "lodging_types": [{"id": t["id"], "name": t["name"]}
                          for t in lists.get("lodging_types") or [] if t["id"] in offered_lodging],
        "code_types": [{"id": c["id"], "name": c["name"]}
                       for c in lists.get("code_types") or [] if c["id"] in offered_codes],
        "trash_days": [{"value": v["handle"], "label": v["name"]}
                       for v in trash_days.get("values") or []],
        "custom_fields": owner_fields,
    }


def owner_secrets(submission) -> dict:
    """On the owner's link: the tax id's last four; a code or the Wi-Fi password
    only as "saved", never a character of it."""
    return vault.masked(submission)


def owner_payload(submission) -> dict:
    state = "open" if submission.owner_may_edit else "submitted"
    return {
        "state": state, "number": submission.number,
        "form": owner_form(submission) if state == "open" else None,
        "answers": submission.answers or {} if state == "open" else {},
        "secrets": owner_secrets(submission) if state == "open" else {},
        "files": [{"id": str(f.pk), "name": f.name, "size": f.byte_size}
                  for f in submission.files.all()] if state == "open" else [],
        "missing": services.missing_for_submit(submission) if state == "open" else [],
        "first_name": (submission.answers or {}).get("about", {}).get("first_name")
        or submission.invite_first_name,
    }


@csrf_exempt
@require_http_methods(["GET"])
def form_page(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(submission.tenant_id):
        services.touch(submission)
        return JsonResponse(owner_payload(submission))


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
def answers(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    data = _body(request)
    with tenant_context(submission.tenant_id):
        try:
            services.save_section(submission, str(data.get("section", "")), data.get("value"),
                                  by_owner=True)
        except services.Refused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"ok": True, "missing": services.missing_for_submit(submission),
                             "answers": {data.get("section"):
                                         submission.answers.get(data.get("section"))}})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def secret(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    if not submission.owner_may_edit:
        return JsonResponse({"detail": "This form was already submitted. Thank you!"},
                            status=409)
    data = _body(request)
    kind, slot = str(data.get("kind", "")), str(data.get("slot", ""))[:24]
    with tenant_context(submission.tenant_id):
        if request.method == "DELETE":
            vault.clear(submission, kind, slot)
        else:
            try:
                vault.put(submission, kind, slot, str(data.get("value", "")))
            except vault.Refused as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
        services.touch(submission)
        return JsonResponse({"secrets": owner_secrets(submission)})


@csrf_exempt
@require_http_methods(["POST"])
def files(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    if not submission.owner_may_edit:
        return JsonResponse({"detail": "This form was already submitted. Thank you!"},
                            status=409)
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"detail": "Choose a file to upload."}, status=400)
    with tenant_context(submission.tenant_id):
        try:
            row = services.add_file(submission, upload, by_owner=True)
        except services.Refused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"id": str(row.pk), "name": row.name, "size": row.byte_size},
                            status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def file_delete(request, token, file_id):
    submission, error = _resolve(request, token)
    if error:
        return error
    if not submission.owner_may_edit:
        return JsonResponse({"detail": "This form was already submitted. Thank you!"},
                            status=409)
    with tenant_context(submission.tenant_id):
        try:
            services.remove_file(submission, file_id)
        except services.Refused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def submit(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(submission.tenant_id):
        try:
            services.submit(submission)
        except services.Refused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"state": "submitted"})


@csrf_exempt
@require_http_methods(["POST"])
def another(request, token):
    submission, error = _resolve(request, token)
    if error:
        return error
    with tenant_context(submission.tenant_id):
        try:
            new = services.add_another(submission)
        except services.Refused as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        return JsonResponse({"link": links.url_for(new)}, status=201)


@require_http_methods(["GET"])
def form_image(request, slug, which):
    """The form's logo or tab icon. On a form domain only that form's."""
    from apps.tenancy import storage

    from .models import IntakeForm

    form = IntakeForm.all_objects.select_related("company").filter(slug=slug).first()
    form = form if form is not None and hosts.is_on(form) else None
    host_form = getattr(request, "intake_form", None)
    if form is None or (host_form is not None and host_form.pk != form.pk):
        return hosts.not_found(host_form) if host_form else HttpResponse(status=404)
    stored = form.logo if which == "logo" else form.icon
    if stored is None:
        return HttpResponse(status=404)
    try:
        content = storage.read(stored)
    except storage.StorageError:
        return HttpResponse(status=503)
    response = HttpResponse(content, content_type=stored.content_type or "image/png")
    response["Cache-Control"] = "public, max-age=3600"
    # An SVG logo is shown through <img>, and if opened on its own runs nothing.
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response["X-Content-Type-Options"] = "nosniff"
    return response
