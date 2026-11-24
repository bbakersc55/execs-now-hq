"""The staff side of owner agreements (apps/agreements/access.py says who).
Anyone else gets a 404, as if nothing existed. Switching the feature on or off
is not here: `manage.py owner_agreements` (SkyRun only).

GET   /api/agreements/companies                         companies with it, for me
GET   /api/agreements/companies/<id>                    the list, the settings summary
POST  /api/agreements/companies/<id>/agreements         {name, email, phone, terms}
POST  /api/agreements/companies/<id>/preview            {terms}: the words, as blocks
GET   /api/agreements/companies/<id>/access             the permissions screen; PUT {rows}
GET   /api/agreements/companies/<id>/settings           the sender; PUT; POST test|resume
GET   /api/agreements/companies/<id>/authority          the signer's authorization;
                                                        POST record; DELETE withdraw
GET   /api/agreements/companies/<id>/documents          final agreements (Documents)
GET   /api/agreements/<id>                              one agreement; PATCH to correct
POST  /api/agreements/<id>/send | link | cancel | countersign
GET   /api/agreements/<id>/pdf?which=owner|final|preview
"""

from __future__ import annotations

import uuid

from django.http import Http404, HttpResponse
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.ratelimit import client_ip

from . import access, mail, pdf, render, services, texts
from .models import (
    AgreementEvent, AgreementSignature, OwnerAgreement, OwnerEmail, Program, StaffAccess,
)


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, services.Refused):
            return Response({"detail": str(exc)}, status=exc.status)
        return super().handle_exception(exc)


def _uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _membership(request):
    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    return membership


def _company(request, company_id):
    """The company, if this person may see its agreements; else 404."""
    membership = _membership(request)
    if not _uuid(company_id):
        raise Http404
    company = access.companies_for(membership).filter(pk=company_id).first()
    if company is None:
        raise Http404
    return company, membership


def _agreement(request, agreement_id):
    membership = _membership(request)
    if not _uuid(agreement_id):
        raise Http404
    a = (OwnerAgreement.all_objects.select_related("company__tenant", "submission")
         .filter(pk=agreement_id, tenant_id=membership.tenant_id).first())
    if a is None or not access.companies_for(membership).filter(pk=a.company_id).exists():
        raise Http404
    return a, membership


def _may_work(membership, company):
    if not access.may_agreements(membership, company):
        raise services.Refused("You don't have the owner agreements permission.", 403)


def _ua(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:500]


def _name(user) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "email", "")) if user else ""


# ------------------------------------------------------------ payloads

def _row(a) -> dict:
    d = a.details or {}
    version = services.current(a)
    return {"id": str(a.pk), "number": a.number, "owner_name": a.owner_name,
            "owner_email": a.owner_email, "owner_phone": a.owner_phone,
            "property": render.one_line(services.terms_for(a).get("property_address")),
            "status": services.status_line(a),
            "cancelled": a.voided_at is not None,
            "manager_percent": (version.terms or {}).get("manager_percent") if version else None,
            "signed_name": " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x)}


def _program_payload(program, company, membership) -> dict:
    return {"sender": program.sender, "sender_label": program.get_sender_display(),
            "sender_domain": program.sender_domain, "from_address": program.from_address,
            "from_name": program.from_name, "reply_to": program.reply_to,
            "tested_at": program.tested_at.isoformat() if program.tested_at else None,
            "domain_ready": mail.domain_ready(program),
            "paused_at": program.paused_at.isoformat() if program.paused_at else None,
            "pause_reason": program.pause_reason,
            "held": OwnerEmail.all_objects.filter(company=company,
                                                  state=OwnerEmail.State.HELD).count(),
            "warning": ("Testing: owners would see Executives Now as the sender."
                        if program.sender == Program.Sender.TESTING else ""),
            "signer_id": str(program.signer_id) if program.signer_id else None,
            "signer_name": _name(program.signer),
            "may_edit": access.may_edit_access(membership, company),
            "may_set_signer": access.is_practice_owner(membership, company)}


def _detail(a, membership, user) -> dict:
    company = a.company
    version = services.current(a)
    terms = services.terms_for(a)
    sigs = {s.role: s for s in AgreementSignature.all_objects.filter(agreement=a)}
    may_cs, authority = access.may_countersign(user, company)
    contract = services.contract_for(a) if version else {}
    owner = sigs.get("owner")
    manager = sigs.get("manager")
    sub = a.submission
    return {
        **_row(a),
        "company_id": str(company.pk), "company_name": company.name,
        "template": texts.get(a.template_key).title,
        "version": version.revision if version else None,
        "terms": version.terms if version else {},
        "terms_shown": terms,
        "details": a.details or {},
        "address_changed": services.address_changed(a),
        "staff_address": render.one_line((version.terms or {}).get("property_address")),
        "owner_address": render.one_line((a.details or {}).get("property_address")),
        "editable": a.owner_signed_at is None and a.voided_at is None,
        "may_work": access.may_agreements(membership, company),
        "may_countersign": bool(may_cs and owner and not manager and a.voided_at is None),
        "countersign_as": ("signer" if access.is_signer(user, company) else
                           "authorized" if may_cs else ""),
        "authority": _authority_payload(authority, company) if authority else None,
        "signer_name": texts.get(a.template_key).signer_name,
        "owner_signature": ({"name": owner.printed_name, "at": owner.signed_at.isoformat(),
                             "ip": owner.ip_address, "method": owner.method}
                            if owner else None),
        "manager_signature": ({"name": manager.printed_name,
                               "applied_by": manager.applied_by_name,
                               "under_authority": manager.authority_id is not None,
                               "at": manager.signed_at.isoformat(), "ip": manager.ip_address}
                              if manager else None),
        "agreement_date": a.agreement_date.isoformat() if a.agreement_date else None,
        "has_owner_pdf": bool(a.owner_pdf_id), "has_final_pdf": bool(a.final_pdf_id),
        "contract": contract,
        "intake": ({"id": str(sub.pk), "number": sub.number, "status": sub.status,
                    "may_open": access.may_intake(membership, company)} if sub else None),
        "events": [{"kind": e.kind, "detail": e.detail, "at": e.created_at.isoformat(),
                    "by": _name(e.actor)}
                   for e in AgreementEvent.all_objects.filter(agreement=a)
                   .select_related("actor").order_by("created_at")],
        "emails": [{"kind": m.kind, "to": m.to_address, "state": m.state,
                    "at": (m.sent_at or m.created_at).isoformat(), "error": m.error}
                   for m in OwnerEmail.all_objects.filter(agreement=a).order_by("created_at")],
        "sender": services.program_for(company).sender,
        "blocks": render.document(a.template_key, terms, a.details or {},
                                  agreement_date=a.agreement_date),
    }


def _authority_payload(row, company) -> dict:
    return {"id": str(row.pk), "principal": row.principal_name,
            "recorded_at": row.recorded_at.isoformat(),
            "recorded_on": services._day(row.recorded_at, company),
            "people": row.people, "method": row.method, "typed": row.typed_text,
            "wording": row.wording}


# ------------------------------------------------------------ companies

class CompaniesView(Base):
    def get(self, request):
        membership = _membership(request)
        return Response({"companies": [{"id": str(c.pk), "name": c.name}
                                       for c in access.companies_for(membership)
                                       .order_by("name")]})


class CompanyView(Base):
    def get(self, request, company_id):
        company, membership = _company(request, company_id)
        program = services.program_for(company)
        rows = OwnerAgreement.all_objects.filter(company=company).select_related(
            "submission").order_by("-number")
        may_cs, _ = access.may_countersign(request.user, company)
        return Response({
            "company": {"id": str(company.pk), "name": company.name},
            "may_work": access.may_agreements(membership, company),
            "may_edit_access": access.may_edit_access(membership, company),
            "is_signer": access.is_signer(request.user, company),
            "may_countersign": may_cs,
            "program": _program_payload(program, company, membership),
            "defaults": services.default_terms(),
            "agreements": [_row(a) for a in rows]
            if access.may_agreements(membership, company) or may_cs else []})


class CreateView(Base):
    def post(self, request, company_id):
        company, membership = _company(request, company_id)
        _may_work(membership, company)
        d = request.data
        a = services.create(company, name=d.get("name"), email=d.get("email", ""),
                            phone=d.get("phone", ""), terms=d.get("terms") or {},
                            actor=request.user)
        return Response(_detail(a, membership, request.user), status=201)


class PreviewView(Base):
    def post(self, request, company_id):
        company, membership = _company(request, company_id)
        _may_work(membership, company)
        terms = services.clean_terms(request.data.get("terms") or {})
        return Response({"blocks": render.document(texts.DEFAULT, terms, {}),
                         "terms": terms})


# ------------------------------------------------------------ one agreement

class AgreementView(Base):
    def get(self, request, agreement_id):
        a, membership = _agreement(request, agreement_id)
        if not access.may_agreements(membership, a.company) \
                and not access.may_countersign(request.user, a.company)[0]:
            raise Http404
        return Response(_detail(a, membership, request.user))

    def patch(self, request, agreement_id):
        a, membership = _agreement(request, agreement_id)
        _may_work(membership, a.company)
        d = request.data
        services.update(a, name=d.get("name"), email=d.get("email"), phone=d.get("phone"),
                        terms=d.get("terms"), actor=request.user)
        a.refresh_from_db()
        return Response(_detail(a, membership, request.user))


class ActionView(Base):
    def post(self, request, agreement_id, action):
        a, membership = _agreement(request, agreement_id)
        if action == "countersign":
            d = request.data
            services.countersign(a, request.user, agreed=d.get("agreed") is True,
                                 method=d.get("method", ""), typed=d.get("typed", ""),
                                 drawn=d.get("drawn", ""), ip=client_ip(request),
                                 user_agent=_ua(request))
            a.refresh_from_db()
            return Response(_detail(a, membership, request.user))
        _may_work(membership, a.company)
        out = {}
        if action == "send":
            services.send_email(a, request.user)
        elif action == "link":
            out["link"] = services.copy_link(a, request.user)
        elif action == "cancel":
            services.cancel(a, request.user)
        else:
            raise Http404
        a.refresh_from_db()
        return Response({**_detail(a, membership, request.user), **out})


class PdfView(Base):
    def get(self, request, agreement_id):
        from apps.tenancy import storage

        a, membership = _agreement(request, agreement_id)
        which = request.GET.get("which", "final")
        if not (access.may_agreements(membership, a.company)
                or access.may_countersign(request.user, a.company)[0]
                or (which == "final" and access.may_see_documents(membership, a.company))):
            raise Http404
        if which == "preview":
            content, name = pdf.preview(a), f"Agreement {a.number} (preview).pdf"
        else:
            stored = a.final_pdf if which == "final" else a.owner_pdf
            if stored is None:
                raise Http404
            content = storage.read(stored)
            name = (f"Rental Management Agreement #{a.number}.pdf" if which == "final" else
                    f"Rental Management Agreement #{a.number} (awaiting signature).pdf")
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{name}"'
        return response


# ------------------------------------------------------------ permissions

class AccessView(Base):
    def get(self, request, company_id):
        company, membership = _company(request, company_id)
        if not access.may_edit_access(membership, company):
            raise Http404
        return Response(_access_payload(company))

    def put(self, request, company_id):
        company, membership = _company(request, company_id)
        if not access.may_edit_access(membership, company):
            raise Http404
        allowed = {str(m.user_id): (m, owner) for m, owner in access.company_users(company)}
        changed = []
        for row in request.data.get("rows") or []:
            user_id = str(row.get("user_id"))
            if user_id not in allowed:
                continue
            m, is_owner = allowed[user_id]
            values = {f: row.get(f) is True for f in access.FLAGS}
            if is_owner:                       # the practice owner always has a and c
                values["agreements"] = values["intake"] = False
            obj, _ = StaffAccess.all_objects.get_or_create(
                tenant_id=company.tenant_id, company=company, user_id=m.user_id)
            if any(getattr(obj, f) != v for f, v in values.items()):
                for f, v in values.items():
                    setattr(obj, f, v)
                obj.updated_by = request.user
                obj.save()
                changed.append({"user": _name(m.user), **values})
        if changed:
            services._audit(company, request.user, "agreements.access_changed",
                            {"changed": changed})
        return Response(_access_payload(company))


def _access_payload(company) -> dict:
    ticks = {str(s.user_id): s for s in StaffAccess.all_objects.filter(company=company)}
    rows = []
    for m, is_owner in access.company_users(company):
        t = ticks.get(str(m.user_id))
        rows.append({"user_id": str(m.user_id), "name": _name(m.user),
                     "role": "Practice owner" if is_owner else
                     ("Client owner" if m.role == "FCC" else "Client team member"),
                     "practice_owner": is_owner,
                     "agreements": True if is_owner else bool(t and t.agreements),
                     "signed_pdfs": bool(t and t.signed_pdfs),
                     "intake": True if is_owner else bool(t and t.intake)})
    return {"rows": rows}


# ------------------------------------------------------------ the sender

class SettingsView(Base):
    def get(self, request, company_id):
        company, membership = _company(request, company_id)
        program = services.program_for(company)
        return Response(_program_payload(program, company, membership))

    def put(self, request, company_id):
        company, membership = _company(request, company_id)
        if not access.may_edit_access(membership, company):
            raise services.Refused("Only the practice owner or the Client owner can change "
                                   "the sender.", 403)
        program = services.program_for(company)
        d = request.data
        fields = []
        for key in ("sender_domain", "from_address", "from_name", "reply_to"):
            if key in d:
                value = " ".join(str(d.get(key) or "").split())
                if key == "sender_domain":
                    value = value.lower().strip(".")
                if key in ("from_address", "reply_to"):
                    value = value.lower()
                    if value and not services._EMAIL.match(value):
                        raise services.Refused(f"The {key.replace('_', '-')} doesn't look "
                                               "right.")
                setattr(program, key, value[:200])
                fields.append(key)
        if program.from_address and program.sender_domain and not \
                program.from_address.endswith("@" + program.sender_domain):
            raise services.Refused("The from-address must be on the domain.")
        if "signer_id" in d:
            if not access.is_practice_owner(membership, company):
                raise services.Refused("Only the practice owner sets who signs.", 403)
            ids = {str(m.user_id): m.user for m, owner in access.company_users(company)
                   if not owner}
            program.signer = ids.get(str(d.get("signer_id"))) if d.get("signer_id") else None
            fields.append("signer")
        if "sender" in d:
            want = d.get("sender")
            if want == Program.Sender.DOMAIN and not mail.domain_ready(program):
                raise services.Refused("Our own domain can be chosen once the domain and "
                                       "from-address are set and Send a test to me has worked.")
            if want in (Program.Sender.TESTING, Program.Sender.DOMAIN):
                program.sender = want
                fields.append("sender")
        if fields:
            program.save(update_fields=list(dict.fromkeys(fields)) + ["updated_at"])
            services._audit(company, request.user, "agreements.settings_changed",
                            {"fields": fields})
        return Response(_program_payload(program, company, membership))

    def post(self, request, company_id):
        company, membership = _company(request, company_id)
        if not (access.may_edit_access(membership, company)
                or access.may_agreements(membership, company)):
            raise Http404
        program = services.program_for(company)
        action = request.data.get("action")
        if action == "test":
            if not access.may_edit_access(membership, company):
                raise services.Refused("Only the practice owner or the Client owner can test "
                                       "the sender.", 403)
            message = mail.send_test(program, request.user)
        elif action == "resume":
            sent = mail.resume(program, request.user)
            message = f"Resumed. {sent} held email(s) sent."
        else:
            raise Http404
        program.refresh_from_db()
        return Response({**_program_payload(program, company, membership), "message": message})


# ------------------------------------------------------------ the authorization

class AuthorityView(Base):
    def get(self, request, company_id):
        company, membership = _company(request, company_id)
        row = access.authority_in_force(company)
        people = [{"user_id": str(m.user_id), "name": _name(m.user),
                   "role": "Practice owner" if owner else
                   ("Client owner" if m.role == "FCC" else "Client team member")}
                  for m, owner in access.company_users(company)]
        tpl = texts.get(texts.DEFAULT)
        from . import consent

        return Response({
            "is_signer": access.is_signer(request.user, company),
            "signer_name": tpl.signer_name, "signer_title": tpl.signer_title,
            "authority": _authority_payload(row, company) if row else None,
            "people": people,
            "wording": consent.authorization(company=services._brand(company),
                                             principal=tpl.signer_name,
                                             title=tpl.signer_title)})

    def post(self, request, company_id):
        company, membership = _company(request, company_id)
        d = request.data
        services.record_authority(company, request.user, method=d.get("method", ""),
                                  typed=d.get("typed", ""), drawn=d.get("drawn", ""),
                                  people=d.get("people") or [], agreed=d.get("agreed") is True,
                                  ip=client_ip(request), user_agent=_ua(request))
        return self.get(request, company_id)

    def delete(self, request, company_id):
        company, membership = _company(request, company_id)
        services.withdraw_authority(company, request.user, ip=client_ip(request),
                                    user_agent=_ua(request))
        return self.get(request, company_id)


# ------------------------------------------------------------ Documents

class DocumentsView(Base):
    """Final agreements, in the company's Documents: only for ticks a or b,
    the practice owner and the Client owner (owner, 2026-11-23)."""

    def get(self, request, company_id):
        membership = _membership(request)
        if not _uuid(company_id):
            raise Http404
        from apps.crm.models import Company

        company = Company.all_objects.filter(pk=company_id, tenant_id=membership.tenant_id,
                                             deleted_at__isnull=True).first()
        if company is None or not access.is_on(company) \
                or not access.may_see_documents(membership, company):
            return Response({"documents": []})
        rows = OwnerAgreement.all_objects.filter(company=company, final_pdf__isnull=False) \
            .order_by("-countersigned_at")
        return Response({"documents": [
            {"id": str(a.pk), "title": f"Rental Management Agreement #{a.number}",
             "owner": a.owner_name,
             "property": render.one_line(services.terms_for(a).get("property_address")),
             "date": a.agreement_date.isoformat() if a.agreement_date else None,
             "pdf": f"/api/agreements/{a.pk}/pdf?which=final"} for a in rows]})
