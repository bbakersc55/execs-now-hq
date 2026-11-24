"""The staff side of intake forms: the company's managers and above, and the
practice owner (`access.py`). Everyone else gets a 404. Switching intake forms
on or off for a company is not here: `manage.py intake_forms` (SkyRun only).

GET   /api/intake/companies                          companies whose intakes I run
GET   /api/intake/companies/<id>/form                settings; PUT to change them
POST  /api/intake/companies/<id>/form/image          multipart {which: logo|icon, file}
POST  /api/intake/companies/<id>/refresh             Track's lists, now
GET   /api/intake/companies/<id>/submissions         the list; POST {first_name, last_name, email}
GET   /api/intake/submissions/<id>                   the review screen's whole payload
PATCH /api/intake/submissions/<id>/answers           {section, value}
POST  /api/intake/submissions/<id>/secret            {kind, slot, value}; DELETE {kind, slot}
POST  /api/intake/submissions/<id>/reveal            {name}: one value, recorded
PATCH /api/intake/submissions/<id>/staff             the reviewer's choices
POST  /api/intake/submissions/<id>/check             look in Track for duplicates
POST  /api/intake/submissions/<id>/link              {action: link|message|email, reminder}
POST  /api/intake/submissions/<id>/reopen | discard | send
GET   /api/intake/submissions/<id>/run               the latest send, step by step
POST  /api/intake/submissions/<id>/files             staff upload; GET|DELETE /files/<fid>
POST  /api/intake/submissions/<id>/dates/place       "Place owner dates now"
POST  /api/intake/submissions/<id>/dates/<did>/cancel
"""

from __future__ import annotations

import re

from django.conf import settings as dj_settings
from django.http import Http404, HttpResponse
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import AuditEvent

from . import access, defaults, derive, hosts, links, plan, schema, services, tracklists, vault
from .models import IntakeForm, SendRun, Submission

IMAGE_TYPES = {"image/png": b"\x89PNG", "image/jpeg": b"\xff\xd8\xff"}
MOST_IMAGE_BYTES = 500 * 1024


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def handle_exception(self, exc):
        from apps.agreements.services import Refused as AgreementsRefused

        if isinstance(exc, (services.Refused, AgreementsRefused)):
            return Response({"detail": str(exc)}, status=exc.status)
        return super().handle_exception(exc)


def _submission(request, submission_id) -> Submission:
    membership = getattr(request, "membership", None)
    if membership is None or not access._uuid(submission_id):
        raise Http404
    sub = (Submission.all_objects.select_related("form", "company")
           .filter(pk=submission_id, tenant_id=membership.tenant_id).first())
    if sub is None or not access.is_manager(membership, sub.company) \
            or not sub.company.intake_forms_enabled:
        raise Http404
    return sub


def _user_name(user) -> str:
    return (getattr(user, "full_name", "") or user.email) if user else ""


# ------------------------------------------------------------ companies

class CompaniesView(Base):
    def get(self, request):
        rows = [{"id": str(c.pk), "name": c.name}
                for c in access.companies_for(getattr(request, "membership", None))
                .order_by("name")]
        return Response({"companies": rows})


def _form_payload(form, lists, status, membership=None) -> dict:
    from apps.agreements import access as people

    settings = services.settings_of(form, lists)
    domain_live = not form.domain or form.domain.lower() in hosts.live_hosts()
    return {
        "id": str(form.pk), "title": form.title, "brand_name": form.brand_name,
        "slug": form.slug, "domain": form.domain, "colors": form.colors or {},
        "contact_phone": form.contact_phone, "contact_email": form.contact_email,
        "has_logo": form.logo_id is not None, "has_icon": form.icon_id is not None,
        "base": links.form_base(form),
        "warning": ("" if form.domain and domain_live else
                    "Owners would see getexecutivesnow.com in the link. Set the form's own "
                    "domain to hide it." if not form.domain else
                    f"{form.domain} isn't live yet: it needs adding in Railway and DNS (see the "
                    "intake forms guide). Until then links use it but won't open."),
        "settings": settings, "lists": lists, "lists_status": status,
        "setting_keys": list(defaults.SETTING_KEYS),
        "builtin_fields": schema.BUILTIN_FIELDS,
        "checklist_when": list(defaults.CHECKLIST_WHEN),
        # Owner, 2026-11-24: test mode, who may change it, and its last change.
        "test_mode": services.test_mode(settings),
        "may_change_test_mode": people.may_edit_access(membership, form.company),
        "may_edit_access": people.may_edit_access(membership, form.company),
        "test_mode_change": _test_mode_change(form),
    }


def _test_mode_change(form) -> dict | None:
    event = (AuditEvent.all_objects.filter(verb="intake.test_mode_changed", target_id=form.pk)
             .select_related("actor").order_by("-created_at").first())
    if event is None:
        return None
    return {"to": bool((event.payload or {}).get("to")), "from": (event.payload or {}).get("from"),
            "by": _user_name(event.actor), "at": event.created_at.isoformat()}


_DOMAIN = re.compile(r"^(?=.{4,200}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class FormView(Base):
    def get(self, request, company_id):
        company = access.company_or_404(request, company_id)
        form = services.form_for(company)
        lists, status = tracklists.lists_for(company)
        return Response(_form_payload(form, lists, status,
                                      getattr(request, "membership", None)))

    def put(self, request, company_id):
        company = access.company_or_404(request, company_id)
        form = services.form_for(company)
        data = request.data or {}
        for key, most in (("title", 120), ("brand_name", 120), ("contact_phone", 40)):
            if key in data:
                setattr(form, key, str(data[key] or "").strip()[:most])
        if "contact_email" in data:
            form.contact_email = str(data["contact_email"] or "").strip()[:200]
        if "slug" in data:
            slug = re.sub(r"[^a-z0-9-]", "", str(data["slug"] or "").lower())[:60]
            if not slug:
                return Response({"slug": "The address needs a slug, like skyrun-park-city."},
                                status=400)
            if IntakeForm.all_objects.filter(slug=slug).exclude(pk=form.pk).exists():
                return Response({"slug": "Another form uses that address."}, status=400)
            form.slug = slug
        if "domain" in data:
            domain = str(data["domain"] or "").strip().lower().rstrip(".")
            domain = re.sub(r"^https?://", "", domain).split("/")[0]
            if domain and not _DOMAIN.match(domain):
                return Response({"domain": "That isn't a domain name, like "
                                           "owners.skyrunparkcity.com."}, status=400)
            if domain and (domain.endswith("getexecutivesnow.com")
                           or domain in dj_settings.ALLOWED_HOSTS
                           and domain not in hosts.live_hosts()):
                return Response({"domain": "Use the company's own domain."}, status=400)
            if domain and IntakeForm.all_objects.filter(domain=domain).exclude(
                    pk=form.pk).exists():
                return Response({"domain": "Another form uses that domain."}, status=400)
            form.domain = domain
        if "colors" in data and isinstance(data["colors"], dict):
            form.colors = {k: v for k, v in data["colors"].items()
                           if isinstance(v, str) and _COLOR.match(v)}
        if "settings" in data and isinstance(data["settings"], dict):
            current = dict(form.settings or {})
            for key, value in data["settings"].items():
                # Test mode has its own door (`TestModeView`): who may change
                # it is narrower, and each change is recorded on its own.
                if key in defaults.SETTING_KEYS and key != "test_mode":
                    current[key] = value
            form.settings = current
        form.save()
        hosts.forget()
        AuditEvent.all_objects.create(tenant_id=form.tenant_id, actor=request.user,
                                      verb="intake.form_changed", target_type="intake_form",
                                      target_id=form.pk, payload={"keys": sorted(data.keys())})
        lists, status = tracklists.lists_for(company)
        return Response(_form_payload(form, lists, status,
                                      getattr(request, "membership", None)))


class FormImageView(Base):
    def post(self, request, company_id):
        from apps.tenancy import storage

        company = access.company_or_404(request, company_id)
        form = services.form_for(company)
        which = request.data.get("which")
        upload = request.FILES.get("file")
        if which not in ("logo", "icon") or upload is None:
            return Response({"detail": "Choose a logo or an icon file."}, status=400)
        content = upload.read(MOST_IMAGE_BYTES + 1)
        if len(content) > MOST_IMAGE_BYTES:
            return Response({"detail": "Images can be up to 500 KB."}, status=400)
        kind = next((k for k, magic in IMAGE_TYPES.items() if content.startswith(magic)), None)
        if kind is None and content.lstrip()[:5].lower() in (b"<?xml", b"<svg ") \
                and b"<script" not in content.lower():
            kind = "image/svg+xml"
        if kind is None:
            return Response({"detail": "Upload a PNG, JPG or SVG."}, status=400)
        name = f"{which}.{ {'image/png': 'png', 'image/jpeg': 'jpg'}.get(kind, 'svg') }"
        stored = storage.save(tenant=company.tenant, content=content,
                              object_key=storage.object_key("intake-brand", name),
                              purpose="intake_brand", content_type=kind)
        setattr(form, which, stored)
        form.save(update_fields=[which])
        return Response({"ok": True, which: f"/api/forms/{form.slug}/{which}"})


class TestModeView(Base):
    """Owner, 2026-11-24: only the people who may change the permissions screen
    (the practice owner and the Client owner) turn test mode on or off; each
    change is its own audit event, with who, when, from and to. Never while
    acting as someone."""

    def post(self, request, company_id):
        from apps.agreements import access as people
        from apps.agreements import services as agreements

        agreements.not_while_acting()
        company = access.company_or_404(request, company_id)
        membership = getattr(request, "membership", None)
        if not people.may_edit_access(membership, company):
            raise services.Refused("Only the practice owner and the Client owner can change "
                                   "test mode.", 403)
        form = services.form_for(company)
        lists, status = tracklists.lists_for(company)
        before = services.test_mode(services.settings_of(form, lists))
        on = request.data.get("on") is True
        if on != before:
            form.settings = {**(form.settings or {}), "test_mode": on}
            form.save(update_fields=["settings", "updated_at"])
            AuditEvent.all_objects.create(tenant_id=form.tenant_id, actor=request.user,
                                          verb="intake.test_mode_changed",
                                          target_type="intake_form", target_id=form.pk,
                                          payload={"from": before, "to": on,
                                                   "company_id": str(company.pk)})
        return Response(_form_payload(form, lists, status, membership))


class RefreshView(Base):
    def post(self, request, company_id):
        company = access.company_or_404(request, company_id)
        form = services.form_for(company)
        lists, status = tracklists.lists_for(company, refresh=True)
        if lists.get("bed_types"):
            form.settings = services.settings_of(form, lists)
            form.save(update_fields=["settings"])
        return Response(_form_payload(form, lists, status,
                                      getattr(request, "membership", None)))


def _row(sub) -> dict:
    about = (sub.answers or {}).get("about") or {}
    prop = (sub.answers or {}).get("property") or {}
    return {"id": str(sub.pk), "number": sub.number, "status": sub.status,
            "status_label": Submission.Status(sub.status).label,
            "owner": " ".join(p for p in (about.get("first_name") or sub.invite_first_name,
                                          about.get("last_name") or sub.invite_last_name) if p),
            "property": derive.street_line(prop), "link_open": sub.link_open,
            "expires_at": sub.expires_at.isoformat(), "created_at": sub.created_at.isoformat(),
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
            "sent_at": sub.sent_at.isoformat() if sub.sent_at else None,
            # Owner, 2026-11-23: a test send marks the intake as a test.
            "tested": SendRun.all_objects.filter(submission=sub, test=True).exists()}


class SubmissionsView(Base):
    def get(self, request, company_id):
        company = access.company_or_404(request, company_id)
        subs = Submission.all_objects.filter(company=company).order_by("-created_at")[:500]
        form = services.form_for(company)
        lists, _ = tracklists.stored(company)
        from apps.agreements import access as people

        return Response({"submissions": [_row(s) for s in subs],
                         "test_mode": services.test_mode(services.settings_of(form, lists)),
                         "may_edit_access": people.may_edit_access(
                             getattr(request, "membership", None), company)})

    def post(self, request, company_id):
        company = access.company_or_404(request, company_id)
        form = services.form_for(company)
        sub = services.start(form, first_name=request.data.get("first_name", ""),
                             last_name=request.data.get("last_name", ""),
                             email=request.data.get("email", ""), actor=request.user)
        return Response({"id": str(sub.pk), "number": sub.number}, status=201)


# ------------------------------------------------------------ one submission

def review_payload(sub, request) -> dict:
    lists, status = tracklists.stored(sub.company)
    settings = services.settings_of(sub.form, lists)
    staff = services.staff_choices(sub, settings, lists)
    answers = sub.answers or {}
    the_plan = services.build_plan(sub, lists, settings)
    provided = derive.node_amenity_ids(lists, staff.get("node_id"))
    derived = []
    for item in derive.derived_amenities(answers, lists, None):
        derived.append({**item, "provided_by_area": item["id"] in provided,
                        "ticked": item["id"] not in set(staff.get("untick") or [])})
    custom = derive.custom_values(answers, staff, settings, lists)
    run = sub.runs.order_by("-created_at").first()
    today = services.practice_today(sub)
    from apps.tenancy.models import Membership

    membership = getattr(request, "membership", None)
    return {
        **_row(sub), "locked": sub.locked, "owner_may_edit": sub.owner_may_edit,
        "invite": {"first_name": sub.invite_first_name, "last_name": sub.invite_last_name,
                   "email": sub.invite_email},
        "link": links.url_for(sub) if sub.discarded_at is None else "",
        "form": {"title": sub.form.title, "brand_name": sub.form.brand_name,
                 "domain": sub.form.domain, "company": sub.company.name,
                 "company_id": str(sub.company_id)},
        "answers": answers, "secrets": vault.masked(sub),
        "schema": {"sections": [{"key": k, "title": t} for k, t in schema.SECTIONS],
                   "options": {k: [{"value": a, "label": b} for a, b in v]
                               for k, v in schema.OPTIONS.items()},
                   "builtin_fields": schema.BUILTIN_FIELDS},
        "owner_form": _owner_form_safe(sub),
        "lists": {k: lists.get(k) for k in ("nodes", "contracts", "unit_types",
                                            "lodging_types", "code_types")},
        "staff_fields": [{"reference": f["reference"], "name": f["name"], "type": f["type"],
                          "values": [{"value": v["handle"], "label": v["name"]}
                                     for v in f.get("values") or []]}
                         for f in lists.get("custom_fields") or []
                         if ((settings.get("custom_fields") or {}).get(f["reference"]) or {})
                         .get("state") == "staff"],
        "lists_status": {"fetched_at": status.isoformat() if status else None},
        "staff": staff,
        "derived": {
            "rooms": [{**r, "summary": derive.room_summary(r["name"], r.get("beds"), settings,
                                                           lists)
                       if r["roomType"] in ("bedroom", "common") else
                       f"{r['name']}: {derive.BATH_LABEL[r['roomType']]} bathroom"}
                      for r in derive.rooms(answers, settings, lists, staff)],
            "counts": derive.counts(answers, lists, staff),
            "sleeps_worked_out": sum(r["sleeps"] for r in derive.rooms(answers, settings, lists,
                                                                       staff)),
            "sleeps_total": derive.total_sleeps(answers, settings, lists, staff),
            "derived_amenities": derived,
            "amenities": derive.chosen_amenities(answers, settings, lists, staff),
            "custom": {k: ("(hidden)" if isinstance(v, dict) else v) for k, v in custom.items()},
            "keyword_presets": derive.keyword_presets(answers, lists),
            "codes": derive.code_slots(answers, lists, settings),
            "unit_type_suggested": derive.unit_type_for(
                derive.counts(answers, lists, staff)["bedrooms"], lists),
        },
        "plan": {"mode": the_plan["mode"], "summary": the_plan["summary"],
                 "problems": the_plan["problems"], "warnings": the_plan["warnings"],
                 "steps": [{"key": s["key"], "label": s["label"]} for s in the_plan["steps"]],
                 # Every sensitive value the answers call for, and whether it is
                 # held, done in Track, marked as none, or missing.
                 "secrets": the_plan["secrets"]},
        "check": sub.track_check or {}, "checked_at": sub.checked_at.isoformat()
        if sub.checked_at else None,
        "files": [{"id": str(f.pk), "name": f.name, "size": f.byte_size,
                   "content_type": f.content_type} for f in sub.files.all()],
        "events": [{"kind": e.kind, "label": e.get_kind_display(), "detail": e.detail,
                    "who": _user_name(e.actor) if e.actor else "Owner",
                    "at": e.created_at.isoformat()} for e in sub.events.all()],
        "run": _run(run),
        # The practice's date, for "Start today"; and, once the owner is
        # linked to the unit, what to say while that link hasn't started.
        "today": today.isoformat(),
        "link_note": services.link_note(services.link_start(sub, staff), today),
        "owner_dates": services.owner_date_rows(sub),
        "may_send": not the_plan["problems"] and not sub.locked
        and sub.status in (Submission.Status.SUBMITTED, Submission.Status.FAILED,
                           Submission.Status.DRAFT, Submission.Status.IN_PROGRESS),
        "is_practice": bool(membership and membership.role not in ("FCC", "ECC")),
        "test_mode": services.test_mode(settings),
        "agreement": _agreement_card(sub, membership),
        "people": [{"first": p["first"], "last": p["last"], "email": p["email"],
                    "mobile": p["mobile"], "portal": p["portal"]} for p in plan.people(answers)],
    }


def _agreement_card(sub, membership) -> dict | None:
    """The owner agreement this intake came from: its status, a link to it
    for those who may see it, the contract its split points at, and whether
    it holds Send to Track back (owner, 2026-11-23)."""
    from apps.agreements import access as agreement_access
    from apps.agreements import services as agreements

    agreement = services.agreement_of(sub)
    if agreement is None:
        return None
    return {"id": str(agreement.pk), "number": agreement.number,
            "status": agreements.status_line(agreement),
            "countersigned": agreement.countersigned_at is not None,
            "agreement_date": agreement.agreement_date.isoformat()
            if agreement.agreement_date else None,
            "cancelled": agreement.voided_at is not None,
            "may_open": bool(membership and agreement_access.companies_for(membership)
                             .filter(pk=sub.company_id).exists()),
            "contract": agreements.contract_for(agreement),
            # The owner's answer on the agreement (owner, 2026-11-24).
            "sleeps": (agreement.details or {}).get("sleeps") or None,
            "waiting": services.agreement_waiting(sub)}


def _owner_form_safe(sub) -> dict:
    from .views_public import owner_form

    return owner_form(sub)


def _run(run) -> dict | None:
    if run is None:
        return None
    return {"id": str(run.pk), "state": run.state, "steps": run.steps, "error": run.error,
            "test": run.test,
            "created_at": run.created_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}


class SubmissionView(Base):
    def get(self, request, submission_id):
        return Response(review_payload(_submission(request, submission_id), request))


class AnswersView(Base):
    def patch(self, request, submission_id):
        sub = _submission(request, submission_id)
        services.save_section(sub, str(request.data.get("section", "")),
                              request.data.get("value"), by_owner=False)
        return Response(review_payload(sub, request))


class SecretView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        if sub.locked:
            return Response({"detail": "This intake was sent to Track."}, status=409)
        try:
            vault.put(sub, str(request.data.get("kind", "")), str(request.data.get("slot", "")),
                      str(request.data.get("value", "")))
        except vault.Refused as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"secrets": vault.masked(sub)})

    def delete(self, request, submission_id):
        sub = _submission(request, submission_id)
        vault.clear(sub, str(request.data.get("kind", "")), str(request.data.get("slot", "")))
        return Response({"secrets": vault.masked(sub)})


class RevealView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        value = vault.reveal(sub, str(request.data.get("name", "")), request.user)
        if value is None:
            return Response({"detail": "That value isn't held any more."}, status=404)
        response = Response({"value": value})
        response["Cache-Control"] = "no-store"
        return response


class StaffView(Base):
    def patch(self, request, submission_id):
        sub = _submission(request, submission_id)
        services.save_staff(sub, request.data.get("changes") or {}, request.user)
        return Response(review_payload(sub, request))


class CheckView(Base):
    def post(self, request, submission_id):
        from apps.scorecard import feeds, track

        sub = _submission(request, submission_id)
        try:
            client = feeds.track_client(sub.company)
        except track.TrackUnavailable as exc:
            return Response({"detail": str(exc)}, status=503)
        check = services.check_track(sub, client)
        lists, _ = tracklists.stored(sub.company)
        settings = services.settings_of(sub.form, lists)
        staff = services.staff_choices(sub, settings, lists)
        if staff.get("owner_mode") == "existing" and staff.get("existing_owner_id"):
            check["differences"] = services.owner_differences(sub, client,
                                                              staff["existing_owner_id"])
            sub.track_check = check
            sub.save(update_fields=["track_check"])
        return Response(review_payload(sub, request))


class LinkView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        action = request.data.get("action")
        if action not in links.ACTIONS or sub.discarded_at is not None:
            return Response({"detail": "Choose copy link, copy message or open in email."},
                            status=400)
        reminder = request.data.get("reminder") is True
        message = links.message(sub, reminder=reminder, user=request.user,
                                membership=getattr(request, "membership", None))
        links.record(sub, action, reminder=reminder, actor=request.user)
        return Response({"link": links.url_for(sub), **message,
                         "expired": not sub.link_open})


class ReopenView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        if sub.locked or sub.discarded_at is not None:
            return Response({"detail": "This intake is closed."}, status=409)
        links.reopen(sub, request.user)
        return Response(review_payload(sub, request))


class DiscardView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        services.discard(sub, request.user)
        return Response(review_payload(sub, request))


class SendView(Base):
    def post(self, request, submission_id):
        services.not_while_acting()
        sub = _submission(request, submission_id)
        run = services.start_send(sub, request.user)
        return Response({"run": _run(run)}, status=202)


class RunView(Base):
    def get(self, request, submission_id):
        sub = _submission(request, submission_id)
        run = sub.runs.order_by("-created_at").first()
        return Response({"run": _run(run), "status": sub.status, "locked": sub.locked})


class FilesView(Base):
    def post(self, request, submission_id):
        sub = _submission(request, submission_id)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose a file."}, status=400)
        row = services.add_file(sub, upload, by_owner=False)
        return Response({"id": str(row.pk), "name": row.name, "size": row.byte_size},
                        status=201)


class FileView(Base):
    def get(self, request, submission_id, file_id):
        from apps.tenancy import storage

        sub = _submission(request, submission_id)
        row = sub.files.filter(pk=file_id).first() if access._uuid(file_id) else None
        if row is None:
            raise Http404
        content = storage.read(row.stored_file)
        response = HttpResponse(content, content_type=row.content_type)
        response["Content-Disposition"] = f'inline; filename="{row.name}"'
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def delete(self, request, submission_id, file_id):
        sub = _submission(request, submission_id)
        services.remove_file(sub, file_id)
        return Response({"ok": True})


class PlaceDatesView(Base):
    def post(self, request, submission_id):
        from apps.scorecard import feeds, track

        from . import ownerdates

        sub = _submission(request, submission_id)
        if not sub.locked:
            return Response({"detail": "Owner dates are placed after the intake is sent."},
                            status=409)
        try:
            client = feeds.track_client(sub.company)
        except track.TrackUnavailable as exc:
            return Response({"detail": str(exc)}, status=503)
        lists, _ = tracklists.lists_for(sub.company)
        result = ownerdates.place(sub, client, lists, actor=request.user)
        return Response({"result": result, "owner_dates": services.owner_date_rows(sub)})


class CancelDateView(Base):
    def post(self, request, submission_id, date_id):
        sub = _submission(request, submission_id)
        services.owner_dates_cancel(sub, date_id, request.user)
        return Response({"owner_dates": services.owner_date_rows(sub)})
