"""People screens' API (2026-11-17). Every answer here is a People screen:

1. no access at all is **404**, never 403, whoever asks;
2. anyone holding an HR permission must have two-factor sign-in on first
   (`two_factor: "enroll"`);
3. anyone with it on is asked for a code again after four hours
   (`two_factor: "recheck"`);
4. then the level decides what is shown (`access.py`), and every view,
   change and export of sensitive data is logged.

The demo waives 2 and 3 (`two_factor.waived`).
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import two_factor
from apps.people import access as A
from apps.people import services
from apps.people.models import HRGrant, Level
from apps.tenancy.models import CLIENT_ROLES, Membership, Role

ENROLL = ("Set up two-factor sign-in first, under Profile: it is required for anyone who "
          "holds an HR permission.")
RECHECK = "Enter the code from your authenticator app again: it has been over four hours."


def _guarded(request, *, hr: bool):
    """The two-factor gates of a People screen, or None to go on."""
    if two_factor.waived():
        return None
    user = request.user
    if (hr or A.holds_hr_permission(user)) and not two_factor.enabled(user):
        return Response({"detail": ENROLL, "two_factor": "enroll"}, status=403)
    if two_factor.recheck_due(request):
        return Response({"detail": RECHECK, "two_factor": "recheck"}, status=403)
    return None


def _membership(request):
    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    return membership


def _company(membership, scope):
    from apps.crm.models import Company

    if scope == A.PRACTICE:
        return None
    try:
        uuid.UUID(str(scope))
    except ValueError:
        raise Http404 from None
    company = Company.all_objects.filter(pk=scope, tenant_id=membership.tenant_id,
                                         is_client_company=True,
                                         deleted_at__isnull=True).first()
    if company is None:
        raise Http404
    return company


def _opened(request, scope):
    """(membership, company, access) for a scope, or 404; or a gate's answer."""
    membership = _membership(request)
    company = _company(membership, scope)
    found = A.access_for(membership, company)
    if found is None:
        raise Http404
    gate = _guarded(request, hr=found.hr)
    return membership, company, found, gate


def _name(company) -> str:
    return "The practice's own people" if company is None else company.name


class PeopleHome(APIView):
    """The scopes this person can open."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = _membership(request)
        scopes = A.scopes_for(membership)
        if not scopes:
            raise Http404
        gate = _guarded(request, hr=any(a.hr for _, a in scopes))
        if gate is not None:
            return gate
        return Response({"guidance": services.GUIDANCE, "scopes": [
            {"key": A.scope_key(c), "name": _name(c), "level": a.level,
             "level_label": A.LABELS[a.level], "manages": a.manages}
            for c, a in scopes]})


class PeopleScope(APIView):
    """One company's People page: its directory at this person's level, the
    org chart, headcount by status, anniversaries and birthdays, and what
    is theirs to do or sign."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope):
        from apps.people import checklists, hiring
        from apps.people.models import Status, Target

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        everyone = list(services.records_for(membership.tenant_id, company))
        reached = list(A.visible(found, services.records_for(membership.tenant_id, company)))
        broad = found.level in (A.DIRECTOR, A.GENERALIST, A.DIRECTORY)
        director = found.level == A.DIRECTOR
        rows = [services.list_row(r, found) for r in reached]
        if found.level == A.REPORTS:
            # A manager: their direct reports' checklist progress.
            for row, record in zip(rows, reached):
                if record.pk not in found.own:
                    row["progress"] = [checklists.progress(c) for c in record.checklists
                                       .filter(closed_at__isnull=True)]
        own = [r for r in reached if r.pk in found.own]
        live = [r for r in everyone if r.status != Status.ENDED] if broad else []
        return Response({
            "guidance": services.GUIDANCE, "key": A.scope_key(company), "name": _name(company),
            "level": found.level, "level_label": A.LABELS[found.level],
            "manages": found.manages, "may_add": director, "may_export": found.hr,
            "may_export_sensitive": director, "may_run": found.hr,
            "may_hire": director and company is not None,
            "records": rows,
            "headcount": services.headcount(everyone) if found.hr else None,
            "upcoming": services.upcoming(live) if broad else None,
            "chart": services.org_chart(membership.tenant, live) if broad else None,
            "client_users": services.client_users(membership.tenant_id, company)
            if membership.role == Role.FF else None,
            "members": _members(membership, company) if director else [],
            "fields": [{"id": str(f.pk), "label": f.label} for f in
                       services.custom_fields(membership.tenant_id, company, Target.RECORD)]
            if found.hr else [],
            # Their own items, whoever they are about: an IT owner at the
            # client finishes "Revoke …" without reaching the person.
            "my_items": checklists.assigned_to(request.user, everyone),
            "to_sign": [d for r in own for d in hiring.to_sign(r)],
            "held_in_payroll": services.HELD_IN_PAYROLL,
        })


def _members(membership, company) -> list[dict]:
    """Whose sign-in a record can be linked to."""
    rows = Membership.all_objects.filter(tenant_id=membership.tenant_id,
                                         revoked_at__isnull=True).select_related("user")
    rows = rows.filter(client_company_id=company.pk) if company is not None \
        else rows.exclude(role__in=CLIENT_ROLES)
    return [{"id": str(m.pk), "name": m.user.full_name or m.user.email, "email": m.user.email}
            for m in rows]


def _refused(exc):
    return Response({"detail": str(exc)}, status=getattr(exc, "status", 400))


class PeopleRecords(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        try:
            record = services.save_record(request, found, membership.tenant, company,
                                          request.data)
        except services.PeopleRefused as exc:
            return _refused(exc)
        row, _ = services.represent(record, found)
        return Response(row, status=201)


def _record(membership, company, found, pk):
    if not _is_uuid(pk):
        raise Http404
    record = A.visible(found, services.records_for(membership.tenant_id, company)) \
        .filter(pk=pk).first()
    if record is None:
        raise Http404
    return record


def _person_page(request, membership, company, found, record) -> dict:
    """The person's page by section, and the sensitive fields shown."""
    from apps.people import checklists, hiring
    from apps.people.models import Target

    row, shown = services.represent(record, found)
    if "employment" not in row:
        if found.level == A.REPORTS:
            row["progress"] = [checklists.progress(c) for c in
                               record.checklists.filter(closed_at__isnull=True)]
        return row, shown
    row["checklists"] = [checklists.represent(c, request.user) for c in
                         record.checklists.order_by("-created_at")]
    row["access"] = [checklists.entry_row(e) for e in
                     record.access.order_by("revoked_at", "given_on", "created_at")]
    row["to_sign"] = hiring.to_sign(record) if record.pk in found.own else []
    director = found.level == A.DIRECTOR
    row["may"] = {"edit": director, "run": found.hr, "offer": director and company is not None
                  and record.status == "offer_out", "handbook": found.hr and company is not None,
                  "upload": director}
    if found.hr:
        row["owners"] = checklists.owner_choices(record)
        row["checklist_fields"] = {
            kind: [{"id": str(f.pk), "label": f.label} for f in
                   services.custom_fields(membership.tenant_id, company, kind)]
            for kind in (Target.ONBOARDING, Target.OFFBOARDING)}
        row["reasons"] = [{"value": v, "label": label}
                          for v, label in checklists.Checklist.Reason.choices]
    return row, shown


class PeopleRecord(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope, pk):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        row, shown = _person_page(request, membership, company, found, record)
        services.log(request, record, "view", shown)
        return Response(row)

    def patch(self, request, scope, pk):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        try:
            record = services.save_record(request, found, membership.tenant, company,
                                          request.data, record=record)
        except services.PeopleRefused as exc:
            return _refused(exc)
        row, _ = services.represent(record, found)
        return Response(row)


class PeopleExport(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        try:
            text = services.export_csv(request, found, membership.tenant_id, company,
                                       sensitive=request.query_params.get("sensitive") == "1")
        except services.PeopleRefused as exc:
            return _refused(exc)
        response = HttpResponse(text, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="people.csv"'
        return response


# ------------------------------------------------------------ hiring and signing

class PeopleSend(APIView):
    """POST .../records/<pk>/offer/ or .../handbook/ {email}."""

    permission_classes = [permissions.IsAuthenticated]
    what = "offer"

    def post(self, request, scope, pk):
        from apps.people import hiring

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        send = hiring.send_offer if self.what == "offer" else hiring.send_handbook
        try:
            document = send(request, found, record, request.data, role=membership.role)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response({"document": str(document.pk), "title": document.title,
                         "detail": "It is in the Outbox, waiting for approval, as every "
                                   "signature request is."}, status=201)


# ------------------------------------------------------------ checklists

def _hr(found):
    if not found.hr:
        raise services.PeopleRefused("Only HR permissions run checklists.", 403)


class PeopleChecklistStart(APIView):
    """POST .../records/<pk>/checklists/ {kind, anchor_date, it_owner,
    reason, note, custom}."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk):
        from datetime import date

        from apps.people import checklists

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        data = request.data
        try:
            _hr(found)
            raw = services._a_date(data.get("anchor_date"), "The date")
            checklist = checklists.start(
                record, data.get("kind"), actor=request.user,
                anchor_date=date.fromisoformat(raw) if raw else None,
                it_owner=data.get("it_owner") or None, reason=data.get("reason") or "",
                note=data.get("note") or "", custom=data.get("custom") or None)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(checklists.represent(checklist, request.user), status=201)


def _item(membership, company, found, pk):
    from apps.people.models import ChecklistItem

    if not _is_uuid(pk):
        raise Http404
    item = (ChecklistItem.all_objects.filter(
        pk=pk, tenant_id=membership.tenant_id, checklist__person__client_company=company)
        .select_related("checklist__person", "task").first())
    if item is None:
        raise Http404
    if not (found.hr or item.owner_id == membership.user_id):
        raise Http404
    return item


class PeopleItem(APIView):
    """POST .../items/<pk>/<done|waive|reopen>/: done by HR permissions or
    the item's owner; waived (with a note) and reopened by HR permissions."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk, act):
        from apps.people import checklists

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        item = _item(membership, company, found, pk)
        try:
            if act == "done":
                item = checklists.mark_done(item, actor=request.user)
            elif act in ("waive", "reopen"):
                _hr(found)
                item = (checklists.waive(item, actor=request.user,
                                         note=request.data.get("note") or "")
                        if act == "waive" else checklists.reopen(item, actor=request.user))
            else:
                raise Http404
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(checklists.item_row(item, request.user))


class PeopleChecklistClose(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk):
        from apps.people import checklists
        from apps.people.models import Checklist

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        checklist = Checklist.all_objects.filter(
            pk=pk, tenant_id=membership.tenant_id, person__client_company=company).first() \
            if _is_uuid(pk) else None
        if checklist is None or not found.hr:
            raise Http404
        try:
            checklist = checklists.close(checklist, actor=request.user)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(checklists.represent(checklist, request.user))


# ------------------------------------------------------------ the access list

class PeopleAccessEntries(APIView):
    """POST .../records/<pk>/access/; PATCH or DELETE .../access/<pk>/."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk):
        from apps.people import checklists

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        try:
            _hr(found)
            entry = checklists.save_entry(record, request.data, actor=request.user)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(checklists.entry_row(entry), status=201)


class PeopleAccessEntry(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _entry(self, request, scope, pk):
        from apps.people.models import AccessEntry

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return None, gate
        entry = AccessEntry.all_objects.filter(
            pk=pk, tenant_id=membership.tenant_id, person__client_company=company).first() \
            if _is_uuid(pk) else None
        if entry is None or not found.hr:
            raise Http404
        return entry, None

    def patch(self, request, scope, pk):
        from apps.people import checklists

        entry, gate = self._entry(request, scope, pk)
        if gate is not None:
            return gate
        try:
            entry = checklists.save_entry(entry.person, request.data, actor=request.user,
                                          entry=entry)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(checklists.entry_row(entry))

    def delete(self, request, scope, pk):
        from apps.people import checklists

        entry, gate = self._entry(request, scope, pk)
        if gate is not None:
            return gate
        try:
            checklists.remove_entry(entry, actor=request.user)
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(status=204)


# ------------------------------------------------------------ documents

class PeopleDocuments(APIView):
    """POST .../records/<pk>/documents/ (a form: kind, title, file): an HR
    Director's."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk):
        from apps.people import files

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = _record(membership, company, found, pk)
        if found.level != A.DIRECTOR:
            return Response({"detail": "Only an HR Director adds documents."}, status=403)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose a file."}, status=400)
        try:
            document = files.upload(record, kind=request.data.get("kind"),
                                    title=request.data.get("title") or upload.name,
                                    content=upload.read(), content_type=upload.content_type,
                                    actor=request.user)
        except files.FileRefused as exc:
            return _refused(exc)
        services.log(request, record, "change", ["documents"])
        return Response({"id": str(document.pk), "title": document.title}, status=201)


class PeopleDocumentFile(APIView):
    """GET .../documents/<pk>/: the file, to an HR Director or the person
    themself. Each opening is logged."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope, pk):
        from apps.people import files
        from apps.people.models import PersonDocument

        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        document = PersonDocument.all_objects.filter(
            pk=pk, tenant_id=membership.tenant_id, person__client_company=company) \
            .select_related("person", "stored_file", "esign_document").first() \
            if _is_uuid(pk) else None
        if document is None or not A.sees_in_full(found, document.person) or not \
                A.visible(found, services.records_for(membership.tenant_id, company)) \
                .filter(pk=document.person_id).exists():
            raise Http404
        try:
            content, content_type, filename = files.content_of(document)
        except files.FileRefused as exc:
            return _refused(exc)
        services.log(request, document.person, "view", ["documents"])
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ------------------------------------------------------------ the company's setup

class PeopleSetup(APIView):
    """The company's checklist items and fields: HR permissions read them,
    an HR Director changes them.

    GET .../setup/; POST .../setup/items/ or .../setup/fields/ (new);
    POST .../setup/items/<pk>/ or .../setup/fields/<pk>/ (a change, or
    {archived: true}); POST .../setup/items/reorder/ {kind, ids} or
    .../setup/fields/reorder/ {target, ids}. Each answers the whole setup."""

    permission_classes = [permissions.IsAuthenticated]

    def _open(self, request, scope, *, change=False):
        membership, company, found, gate = _opened(request, scope)
        if gate is None and not found.hr:
            raise Http404
        if gate is None and change and found.level != A.DIRECTOR:
            return membership, company, Response(
                {"detail": "Only an HR Director changes the checklists and fields."},
                status=403)
        return membership, company, gate

    def _state(self, membership, company):
        from apps.people import checklists
        from apps.people.models import Kind, Target

        tenant = membership.tenant
        return {"items": {k: [checklists.template_row(i)
                              for i in checklists.ensure_template(tenant, company, k)]
                          for k in Kind.values},
                "fields": {t: [{"id": str(f.pk), "label": f.label} for f in
                               services.custom_fields(tenant.pk, company, t)]
                           for t in Target.values},
                "held_in_payroll": services.HELD_IN_PAYROLL}

    def get(self, request, scope, **_kwargs):
        membership, company, gate = self._open(request, scope)
        if gate is not None:
            return gate
        return Response(self._state(membership, company))

    def post(self, request, scope, what, pk=None):
        from apps.people import checklists
        from apps.people.models import PeopleCustomField, TemplateItem

        membership, company, gate = self._open(request, scope, change=True)
        if gate is not None:
            return gate
        tenant, data = membership.tenant, request.data
        try:
            if what == "items" and pk == "reorder":
                checklists.reorder_template(tenant, company, data.get("kind"),
                                            data.get("ids") or [])
            elif what == "fields" and pk == "reorder":
                services.reorder_fields(tenant.pk, company, data.get("target"),
                                        data.get("ids") or [])
            elif what == "items" and pk is None:
                checklists.save_template_item(tenant, company, data)
            elif what == "fields" and pk is None:
                services.save_field(tenant, company, data, actor=request.user)
            elif what == "items" and _is_uuid(pk):
                item = TemplateItem.all_objects.filter(pk=pk, tenant=tenant,
                                                       client_company=company).first()
                if item is None:
                    raise Http404
                checklists.save_template_item(tenant, company, data, item=item)
            elif what == "fields" and _is_uuid(pk):
                field = PeopleCustomField.all_objects.filter(pk=pk, tenant=tenant,
                                                             client_company=company).first()
                if field is None:
                    raise Http404
                services.save_field(tenant, company, data, actor=request.user, field=field)
            else:
                raise Http404
        except services.PeopleRefused as exc:
            return _refused(exc)
        return Response(self._state(membership, company))


# ------------------------------------------------------------ permissions

def _grantable(membership, company) -> list[Membership]:
    """Who may be given an HR permission here: the practice owner gives it
    to anyone on the practice team; a client owner to their own people."""
    rows = Membership.all_objects.filter(tenant_id=membership.tenant_id,
                                         revoked_at__isnull=True).select_related("user")
    if membership.role == Role.FF:
        return list(rows.filter(role__in=(Role.CF, Role.VA)))
    if membership.role == Role.FCC and company is not None:
        return list(rows.filter(role=Role.ECC, client_company_id=company.pk))
    return []


def _grant_row(grant) -> dict:
    scope = ("all" if grant.all_companies else
             str(grant.client_company_id) if grant.client_company_id else A.PRACTICE)
    return {"id": str(grant.pk), "user": grant.user.full_name or grant.user.email,
            "email": grant.user.email, "level": grant.level,
            "level_label": grant.get_level_display(), "scope": scope,
            "scope_label": ("Everyone: the practice and every client" if grant.all_companies
                            else grant.client_company.name if grant.client_company_id
                            else "The practice's own people"),
            "granted_at": grant.created_at.isoformat(),
            "two_factor": two_factor.enabled(grant.user)}


class PeoplePermissions(APIView):
    """HR permissions for this scope: the practice owner's or the client
    owner's to give and take back."""

    permission_classes = [permissions.IsAuthenticated]

    def _manager(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is None and not found.manages:
            raise Http404
        return membership, company, gate

    def _grants(self, membership, company):
        from django.db.models import Q

        rows = HRGrant.all_objects.filter(tenant_id=membership.tenant_id,
                                          revoked_at__isnull=True).select_related(
            "user", "client_company")
        if membership.role == Role.FCC:
            rows = rows.filter(client_company=company)
        else:
            rows = rows.filter(Q(all_companies=True) | Q(client_company=company)
                               if company is not None
                               else Q(all_companies=True) | Q(client_company__isnull=True))
        return rows.order_by("created_at")

    def get(self, request, scope):
        membership, company, gate = self._manager(request, scope)
        if gate is not None:
            return gate
        return Response({
            "guidance": services.GUIDANCE,
            "grants": [_grant_row(g) for g in self._grants(membership, company)],
            "grantable": [{"id": str(m.pk), "name": m.user.full_name or m.user.email,
                           "email": m.user.email} for m in _grantable(membership, company)],
            "may_grant_all": membership.role == Role.FF,
        })

    def post(self, request, scope):
        from apps.tenancy.models import AuditEvent

        membership, company, gate = self._manager(request, scope)
        if gate is not None:
            return gate
        level = request.data.get("level")
        if level not in Level.values:
            return Response({"detail": "Choose HR Director or HR Generalist."}, status=400)
        target = next((m for m in _grantable(membership, company)
                       if str(m.pk) == str(request.data.get("member"))), None)
        if target is None:
            return Response({"detail": "Choose someone who can be given it here."}, status=400)
        everywhere = request.data.get("all") is True and membership.role == Role.FF
        HRGrant.all_objects.filter(
            tenant_id=membership.tenant_id, user=target.user, revoked_at__isnull=True,
            all_companies=everywhere, client_company=None if everywhere else company,
        ).update(revoked_at=timezone.now(), revoked_by=request.user)
        try:
            grant = HRGrant.all_objects.create(
                tenant_id=membership.tenant_id, user=target.user, level=level,
                all_companies=everywhere, client_company=None if everywhere else company,
                granted_by=request.user)
        except IntegrityError:
            return Response({"detail": "They have that already."}, status=409)
        AuditEvent.all_objects.create(
            tenant_id=membership.tenant_id, actor=request.user, verb="people.hr_granted",
            target_type="user", target_id=target.user_id,
            payload={"level": level, "scope": _grant_row(grant)["scope"]})
        return Response(_grant_row(grant), status=201)


class PeoplePermissionRevoke(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, scope, pk):
        from apps.tenancy.models import AuditEvent

        view = PeoplePermissions()
        membership, company, gate = view._manager(request, scope)
        if gate is not None:
            return gate
        grant = view._grants(membership, company).filter(pk=pk).first() \
            if _is_uuid(pk) else None
        if grant is None:
            raise Http404
        HRGrant.all_objects.filter(pk=grant.pk).update(revoked_at=timezone.now(),
                                                       revoked_by=request.user)
        AuditEvent.all_objects.create(
            tenant_id=membership.tenant_id, actor=request.user, verb="people.hr_revoked",
            target_type="user", target_id=grant.user_id, payload={"level": grant.level})
        return Response({"revoked": True})


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


class PeopleAccessLogView(APIView):
    """People → Access log: the practice owner's and the client owner's, for
    their scope. Read only: there is no route that changes it."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        if not found.manages:
            raise Http404
        return Response({"guidance": services.GUIDANCE,
                         "entries": services.access_log(membership.tenant_id, company)})
