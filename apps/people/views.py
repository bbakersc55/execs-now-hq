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
from apps.people.models import HRGrant, Level, PersonRecord
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
    """One company's People page: its people at this person's level."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        return Response({
            "guidance": services.GUIDANCE, "key": A.scope_key(company), "name": _name(company),
            "level": found.level, "level_label": A.LABELS[found.level],
            "manages": found.manages, "may_add": found.level == A.DIRECTOR,
            "may_export": found.hr,
            "records": services.show_records(request, found, membership.tenant_id, company),
            "members": _members(membership, company) if found.level == A.DIRECTOR else [],
        })


def _members(membership, company) -> list[dict]:
    """Whose sign-in a placeholder person can be linked to."""
    rows = Membership.all_objects.filter(tenant_id=membership.tenant_id,
                                         revoked_at__isnull=True).select_related("user")
    rows = rows.filter(client_company_id=company.pk) if company is not None \
        else rows.exclude(role__in=CLIENT_ROLES)
    return [{"id": str(m.pk), "name": m.user.full_name or m.user.email, "email": m.user.email}
            for m in rows]


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
            return Response({"detail": str(exc)}, status=exc.status)
        row, _ = services.represent(record, found)
        return Response(row, status=201)


class PeopleRecord(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _record(self, membership, company, found, pk):
        try:
            uuid.UUID(str(pk))
        except ValueError:
            raise Http404 from None
        record = A.visible(found, services.records_for(membership.tenant_id, company)) \
            .filter(pk=pk).first()
        if record is None:
            raise Http404
        return record

    def get(self, request, scope, pk):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = self._record(membership, company, found, pk)
        row, shown = services.represent(record, found)
        services.log(request, record, "view", shown)
        return Response(row)

    def patch(self, request, scope, pk):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        record = self._record(membership, company, found, pk)
        try:
            record = services.save_record(request, found, membership.tenant, company,
                                          request.data, record=record)
        except services.PeopleRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        row, _ = services.represent(record, found)
        return Response(row)


class PeopleExport(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scope):
        membership, company, found, gate = _opened(request, scope)
        if gate is not None:
            return gate
        try:
            text = services.export_csv(request, found, membership.tenant_id, company)
        except services.PeopleRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        response = HttpResponse(text, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="people.csv"'
        return response


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
