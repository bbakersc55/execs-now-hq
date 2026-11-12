"""Command Centers' API (P8).

    GET   /api/command-centers/                  Settings → Command Centers
    POST  /api/command-centers/<code>/           {on}: the switch (practice owner)
    GET   /api/command-centers/<code>/           the module card: what it ships
    GET   /api/command-centers/library/export/   the practice library, as JSON
    DELETE /api/command-centers/library/         the practice library, emptied
    GET   /api/playbooks/                        the playbooks offered
    POST  /api/playbooks/copy/                   {key}: a shipped one, copied
    GET/PATCH /api/playbooks/<id>/               one, and its edit
    POST  /api/playbooks/start/                  start one on a company
"""

from __future__ import annotations

import json
from datetime import date

from django.http import Http404, HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.centers import catalog, playbooks, services
from apps.centers.models import LibraryRecord, Playbook
from apps.crm import permissions as crm_perms

OWNER_ONLY = "Only the practice owner turns Command Centers on and off."


def _role(request):
    return crm_perms.role_of(request)


def _staff(request):
    if _role(request) not in crm_perms.TENANT_ROLES:
        raise Http404


class CentersView(APIView):
    def get(self, request):
        _staff(request)
        return Response(services.state(request.tenant))


class CenterView(APIView):
    def get(self, request, code):
        _staff(request)
        if code not in catalog.CODES:
            raise Http404
        return Response(card(request.tenant, code))

    def post(self, request, code):
        _staff(request)
        if _role(request) != "FF":
            return Response({"detail": OWNER_ONLY}, status=403)
        on = request.data.get("on")
        if not isinstance(on, bool):
            return Response({"detail": "on is true or false."}, status=400)
        try:
            services.switch(request.tenant, code, on, actor=request.user)
        except services.CenterRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response(services.state(request.tenant))


def card(tenant, code: str) -> dict:
    """The module card: the full name and what each shelf holds."""
    from apps.centers.models import CommandCenter
    from apps.tenancy import ai_actions

    services.ensure_catalog()
    row = CommandCenter.objects.get(code=code)
    content = catalog.content(code)
    on = services.has(tenant.pk, code)
    out = {"code": code, "name": row.name, "short_name": row.short_name,
           "description": row.description, "status": row.status, "on": on,
           "price_cents": row.price_cents}
    if content is None:
        return {**out, "shelves": None}
    out["shelves"] = {
        "session_templates": [{"start_from": f"{code}_command_center",
                               "label": f"Start from the {row.name}"}],
        "kpis": [{"key": k["key"], "name": k["name"], "page": k["page"],
                  "guidance": k["guidance"]} for k in content.KPIS],
        "playbooks": [p for p in playbooks.offered(tenant) if p["center"] == code]
        if on else [{"key": key, "name": name, "description": description}
                    for key, (name, description, _o) in content.PLAYBOOKS.items()],
        "documents": [{"original": key, "name": name} for key, (name, _t, _b)
                      in content.DOCUMENTS.items()],
        "emails": [{"original": key, "name": name} for key, (name, _s, _b)
                   in content.EMAILS.items()],
        "tools": content.TOOLS,
        "feeds": [{"code": f, "name": content.FEED_NAMES[f]} for f in content.FEEDS],
        "ai_actions": [{"key": a.key, "label": a.label, "tier": a.tier}
                       for a in ai_actions.ACTIONS if a.center == code],
    }
    return out


class LibraryExportView(APIView):
    def get(self, request):
        if _role(request) != "FF":
            raise Http404
        rows = [{"kind": r.kind, "source_type": r.source_type, "source_id": str(r.source_id),
                 "title": r.title, "structure": r.structure,
                 "recorded_at": r.recorded_at.isoformat()}
                for r in LibraryRecord.objects.order_by("recorded_at")]
        response = HttpResponse(json.dumps({"practice": request.tenant.name, "records": rows},
                                           indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="practice-library.json"'
        return response


class LibraryView(APIView):
    def delete(self, request):
        if _role(request) != "FF":
            raise Http404
        deleted, _ = LibraryRecord.objects.all().delete()
        from apps.tenancy.models import AuditEvent

        AuditEvent.objects.create(tenant=request.tenant, actor=request.user,
                                  verb="practice_library.deleted", target_type="practice",
                                  target_id=request.tenant.pk, payload={"records": deleted})
        return Response(services.state(request.tenant))


# --------------------------------------------------------------- playbooks

def _may_run(request):
    return _role(request) in ("FF", "CF")


class PlaybooksView(APIView):
    def get(self, request):
        _staff(request)
        out = {"playbooks": playbooks.offered(request.tenant),
               "can_edit": _may_run(request),
               "next_monday": playbooks.next_monday().isoformat()}
        if request.query_params.get("company"):
            # A company's page: what has been started there (2026-11-12), for a
            # company this person can see; any other is not found.
            from apps.crm.models import Company

            company = crm_perms.company_queryset_for(request, Company.objects.all()).filter(
                pk=request.query_params["company"]).first() \
                if _is_uuid(request.query_params["company"]) else None
            if company is None:
                raise Http404
            out["runs"] = playbooks.runs_at(company)
        return Response(out)


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


class PlaybookCopyView(APIView):
    def post(self, request):
        if not _may_run(request):
            return Response({"detail": "The practice owner and associates keep the "
                                       "playbooks."}, status=403)
        try:
            playbook = playbooks.copy_shipped(request.tenant, str(request.data.get("key", "")),
                                              actor=request.user)
        except playbooks.PlaybookError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response(playbooks.represent(playbook), status=201)


class PlaybookView(APIView):
    def _get(self, request, pk):
        _staff(request)
        playbook = Playbook.objects.filter(pk=pk, archived_at__isnull=True).first()
        if playbook is None:
            raise Http404
        return playbook

    def get(self, request, pk):
        return Response(playbooks.represent(self._get(request, pk)))

    def patch(self, request, pk):
        playbook = self._get(request, pk)
        if not _may_run(request):
            return Response({"detail": "The practice owner and associates keep the "
                                       "playbooks."}, status=403)
        try:
            playbooks.save(playbook, name=request.data.get("name"),
                           description=request.data.get("description"),
                           outline=request.data.get("outline"),
                           ready=bool(request.data.get("ready")), actor=request.user)
        except playbooks.PlaybookError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response(playbooks.represent(playbook))


class PlaybookStartView(APIView):
    def post(self, request):
        from apps.crm.models import Company, Contact
        from apps.tenancy.models import Membership

        if not _may_run(request):
            return Response({"detail": "The practice owner and associates start playbooks."},
                            status=403)
        data = request.data
        playbook = Playbook.objects.filter(pk=data.get("playbook"),
                                           archived_at__isnull=True).first() \
            if data.get("playbook") else None
        if playbook is None:
            return Response({"detail": "Choose a playbook."}, status=400)
        company = crm_perms.company_queryset_for(request, Company.objects.all()).filter(
            pk=data.get("company")).first() if data.get("company") else None
        if company is None:
            return Response({"detail": "Choose a company you can see."}, status=400)
        try:
            start_date = date.fromisoformat(str(data.get("start_date")))
        except ValueError:
            return Response({"detail": "The start date is year-month-day."}, status=400)
        lead = request.user
        if data.get("lead"):
            member = Membership.objects.filter(user_id=data["lead"], revoked_at__isnull=True,
                                               role__in=("FF", "CF", "VA")).first()
            if member is None:
                return Response({"detail": "The lead is one of the practice's team."},
                                status=400)
            lead = member.user

        def contact(key):
            if not data.get(key):
                return None
            found = Contact.objects.filter(pk=data[key], company=company).first()
            if found is None:
                raise ValueError("The owner and second-in-command are this company's contacts.")
            return found

        try:
            owner_contact, second_contact = contact("owner_contact"), contact("second_contact")
            run = playbooks.start(playbook, company=company, start_date=start_date, lead=lead,
                                  owner_contact=owner_contact, second_contact=second_contact,
                                  actor=request.user, role=_role(request))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=getattr(exc, "status", 400))
        return Response({"goal": str(run.goal_id), "run": str(run.pk), **run.made},
                        status=201)
