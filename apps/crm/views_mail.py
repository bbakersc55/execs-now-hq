"""Mailboxes and the Mail tab (2026-10-28).

GET    /api/mailboxes/                       every mailbox, my default, may I add
POST   /api/mailboxes/start/                 connect another {provider, kind, label, company?, inbound, files_mail}
PATCH  /api/mailboxes/<id>/                  {label?, send_as?, files_mail?, company?}
POST   /api/mailboxes/<id>/verify/           check its send-as again
POST   /api/mailboxes/<id>/disconnect/       stops sending through it and reading it
POST   /api/mailboxes/default/               {mailbox: id | ""}   my default
POST   /api/mailboxes/company/               {company, mailbox: id | ""}   a company's default

GET    /api/mail/?contact=<id> | ?company=<id>[&page=]   every message in or out, newest first
POST   /api/mail/reply/                      {message, body_text}   reply in place, through its thread's mailbox

Who: mailboxes are the practice owner's and associates' (an assistant has
no mailbox, H7). An associate disconnects or changes only a mailbox they
connected, or their own; the practice owner, any. The Mail tab is the
practice owner's and associates' for whatever contact or company they may
see, an assistant's only for the client companies they are assigned to,
and a client's never; nobody is shown an invoice's mail they may not see
(`permissions.threads_without_money`).
"""

from __future__ import annotations

import uuid

from django.conf import settings as dj_settings
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import Http404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Company, Contact, EmailMessage, EmailThread, Mailbox
from apps.crm.services import mailboxes
from apps.tenancy.models import AuditEvent, Role

PAGE = 50


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _may_change(request, mailbox) -> bool:
    if crm_perms.role_of(request) == Role.FF:
        return True
    return mailbox.connected_by_id == request.user.pk or mailbox.user_id == request.user.pk


def _company_label(mailbox) -> str:
    return mailbox.client_company.name if mailbox.client_company_id else ""


def payload(request, mailbox) -> dict:
    connection = mailbox.connection
    return {
        "id": str(mailbox.pk), "provider": mailbox.provider,
        "provider_label": mailbox.get_provider_display(), "kind": mailbox.kind,
        "kind_label": mailbox.get_kind_display(), "label": mailbox.label,
        "email_address": mailbox.email_address,
        "whose": (getattr(mailbox.user, "full_name", "") or "").strip()
        if mailbox.user_id else "",
        "company": str(mailbox.client_company_id) if mailbox.client_company_id else None,
        "company_name": _company_label(mailbox),
        "connected": connection is not None,
        "sends_as": mailboxes.address_of(mailbox) if connection is not None else "",
        "send_as_address": connection.send_as_address if connection is not None else "",
        "send_as_verified": bool(connection is not None and connection.send_as_verified_at),
        "send_as_error": connection.send_as_error if connection is not None else "",
        "reads": mailboxes.reads(mailbox), "files_mail": mailbox.files_mail,
        "files_after": mailbox.files_after.isoformat() if mailbox.files_after else None,
        "files_error": mailbox.files_error,
        "last_poll_error": getattr(connection, "last_poll_error", "") if connection else "",
        "connected_by": (getattr(mailbox.connected_by, "full_name", "") or "").strip()
        if mailbox.connected_by_id else "",
        "disconnected_at": mailbox.disconnected_at.isoformat()
        if mailbox.disconnected_at else None,
        "may_change": _may_change(request, mailbox),
        "allowlist": [{"id": str(e.pk), "address": e.address}
                      for e in mailbox.allowlist.all()] if dj_settings.IS_LOCAL else [],
    }


def _company_for(request, company_id):
    """A client company this person may see (404 otherwise)."""
    if not _uuid(company_id):
        raise Http404
    found = crm_perms.company_queryset_for(request, Company.objects.all()).filter(
        pk=company_id).first()
    if found is None:
        raise Http404
    return found


def connected_mailbox(request, spec, *, provider, email_address, refresh_token, scopes,
                      reads, directory_id="") -> dict:
    """The end of a consent for a shared or client mailbox: what the
    Settings → Email screen is told."""
    company = Company.objects.filter(pk=spec.get("company")).first() \
        if _uuid(spec.get("company")) else None
    try:
        mailbox = mailboxes.store(
            request.tenant, actor=request.user, provider=provider,
            email_address=email_address, refresh_token=refresh_token, scopes=scopes,
            kind=spec.get("kind") or Mailbox.Kind.SHARED, label=spec.get("label", ""),
            company=company, files_mail=bool(spec.get("files_mail")) and reads,
            directory_id=directory_id)
    except mailboxes.MailboxRefused as exc:
        return {"gmail_error" if provider == "gmail" else "ms_error": str(exc)}
    said = mailboxes.check_send_as(mailbox)
    out = {"mailbox_connected": mailbox.email_address}
    if spec.get("inbound") and not reads:
        said = " ".join(filter(None, [said, "Consent was granted without permission to read "
                                      "mail, so replies cannot be collected from it."]))
    if said:
        out["mailbox_warning"] = said
    return out


class MailboxViewSet(viewsets.ViewSet):
    permission_classes = [crm_perms.IsTenantStaff, crm_perms.CanConnectMailbox]

    def _get(self, request, pk):
        found = Mailbox.objects.filter(pk=pk).select_related(
            "gmail", "microsoft", "user", "client_company", "connected_by").first() \
            if _uuid(pk) else None
        if found is None:
            raise Http404
        return found

    def _all(self, request):
        from apps.crm.services import sender

        preference = sender.preference_for(request.tenant, request.user)
        rows = mailboxes.of_tenant(request.tenant)
        return {"mailboxes": [payload(request, m) for m in rows],
                "default": str(preference.default_mailbox_id)
                if preference and preference.default_mailbox_id else None,
                "is_local_build": dj_settings.IS_LOCAL}

    def list(self, request):
        return Response(self._all(request))

    @action(detail=False, methods=["post"])
    def start(self, request):
        """Hand back the consent URL for a shared or a client's mailbox."""
        from config import environment

        from apps.crm.services import gmail_oauth, microsoft_oauth

        if environment.is_demo():
            return Response({"detail": "This is the demo. It sends from one address only, "
                                       "so no other mailbox is connected here."}, status=409)
        kind = request.data.get("kind") or Mailbox.Kind.SHARED
        if kind not in (Mailbox.Kind.SHARED, Mailbox.Kind.CLIENT):
            return Response({"kind": "Choose a shared address or a client's mailbox."},
                            status=400)
        company = None
        if kind == Mailbox.Kind.CLIENT:
            company = _company_for(request, request.data.get("company")) \
                if request.data.get("company") else None
            if company is None:
                return Response({"company": "Choose whose mailbox it is."}, status=400)
        inbound = bool(request.data.get("inbound"))
        spec = {"kind": kind, "label": str(request.data.get("label") or "")[:80],
                "company": str(company.pk) if company else "", "inbound": inbound,
                "files_mail": inbound and bool(request.data.get("files_mail"))}
        provider = request.data.get("provider") or "gmail"
        if provider == "microsoft":
            if not microsoft_oauth.is_configured():
                return Response({"detail": "Microsoft 365 isn't set up on this server yet, so "
                                           "a Microsoft mailbox can't be connected."}, status=400)
            state = microsoft_oauth.new_state()
            request.session[microsoft_oauth.STATE_SESSION_KEY] = state
            request.session[microsoft_oauth.INBOUND_SESSION_KEY] = inbound
            request.session[microsoft_oauth.FILES_SESSION_KEY] = False
            request.session[microsoft_oauth.RETURN_SESSION_KEY] = "email"
            request.session[gmail_oauth.MAILBOX_SESSION_KEY] = spec
            return Response({"authorization_url": microsoft_oauth.authorization_url(
                state, inbound=inbound)})
        if not gmail_oauth.is_configured(request.tenant):
            return Response({"detail": "Google sign-in isn't configured on this server, so "
                                       "there is nothing to connect to."}, status=400)
        state = gmail_oauth.new_state()
        request.session[gmail_oauth.STATE_SESSION_KEY] = state
        request.session[gmail_oauth.RETURN_SESSION_KEY] = "email"
        request.session[gmail_oauth.DRIVE_SESSION_KEY] = False
        request.session[gmail_oauth.SHEETS_SESSION_KEY] = False
        request.session[gmail_oauth.INBOUND_SESSION_KEY] = inbound
        request.session[gmail_oauth.MAILBOX_SESSION_KEY] = spec
        return Response({"authorization_url": gmail_oauth.authorization_url(
            state, inbound=inbound, tenant=request.tenant)})

    def partial_update(self, request, pk=None):
        mailbox = self._get(request, pk)
        if not _may_change(request, mailbox):
            return Response({"detail": "Only the practice owner, or whoever connected it, "
                                       "changes this mailbox."}, status=403)
        fields = []
        if "label" in request.data:
            mailbox.label = str(request.data.get("label") or "").strip()[:80]
            fields.append("label")
        if "files_mail" in request.data:
            wanted = bool(request.data.get("files_mail"))
            if wanted and not mailboxes.reads(mailbox):
                return Response({"files_mail": "This mailbox wasn't connected with permission "
                                               "to read mail. Connect it again with “Also "
                                               "collect replies” ticked."}, status=400)
            mailbox.files_mail = wanted
            if wanted:
                mailboxes.file_start(mailbox)
            fields += ["files_mail", "files_after"]
        if "company" in request.data and mailbox.kind == Mailbox.Kind.CLIENT:
            mailbox.client_company = _company_for(request, request.data.get("company"))
            fields.append("client_company")
        said = ""
        if "send_as" in request.data and not mailbox.is_own:
            from django.core.exceptions import ValidationError
            from django.core.validators import validate_email

            address = str(request.data.get("send_as") or "").strip().lower() \
                or mailbox.email_address
            try:
                validate_email(address)
            except ValidationError:
                return Response({"send_as": "Enter an email address."}, status=400)
            mailbox.send_as_address, mailbox.send_as_verified_at = address, None
            fields += ["send_as_address", "send_as_verified_at"]
        if fields:
            mailbox.save(update_fields=[*fields, "updated_at"])
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="mailbox.changed",
                target_type="mailbox", target_id=mailbox.pk, payload={"fields": fields})
        if "send_as" in request.data and not mailbox.is_own:
            said = mailboxes.check_send_as(mailbox)
            mailbox.refresh_from_db()
        return Response({**payload(request, mailbox), **({"verify_error": said} if said else {})})

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        mailbox = self._get(request, pk)
        if mailbox.is_own:
            return Response({"detail": "Check your own connection's address above."},
                            status=400)
        said = mailboxes.check_send_as(mailbox)
        mailbox.refresh_from_db()
        return Response({**payload(request, mailbox), **({"verify_error": said} if said else {})})

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        mailbox = self._get(request, pk)
        if not _may_change(request, mailbox):
            return Response({"detail": "Only the practice owner, or whoever connected it, "
                                       "disconnects this mailbox."}, status=403)
        if mailboxes.is_connected(mailbox):
            mailboxes.disconnect(mailbox, actor=request.user)
        return Response(self._all(request))

    @action(detail=False, methods=["post"])
    def default(self, request):
        """My default mailbox ("" for the practice alias, as before)."""
        from apps.crm.services import sender

        preference = sender.preference_for(request.tenant, request.user)
        chosen = None
        if request.data.get("mailbox"):
            chosen = mailboxes.usable(request.tenant, request.data["mailbox"])
            if chosen is None:
                return Response({"mailbox": "Choose a connected mailbox."}, status=400)
        preference.default_mailbox = chosen
        preference.save(update_fields=["default_mailbox", "updated_at"])
        return Response(self._all(request))

    @action(detail=False, methods=["get", "post"])
    def company(self, request):
        """A company's default: "mail about this client goes from this mailbox"."""
        company = _company_for(request, request.query_params.get("company")
                               if request.method == "GET" else request.data.get("company"))
        if request.method == "POST":
            chosen = None
            if request.data.get("mailbox"):
                chosen = mailboxes.usable(request.tenant, request.data["mailbox"])
                if chosen is None:
                    return Response({"mailbox": "Choose a connected mailbox."}, status=400)
            company.mail_from = chosen
            company.save(update_fields=["mail_from", "updated_at"])
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="company.mail_from_changed",
                target_type="company", target_id=company.pk,
                payload={"mailbox": chosen.email_address if chosen else ""})
        current = company.mail_from if mailboxes.is_connected(company.mail_from) else None
        return Response({"company": str(company.pk),
                         "mailbox": str(current.pk) if current else None,
                         "options": mailboxes.options(request.tenant)})


# ------------------------------------------------------------- the Mail tab

def _scope(request, params):
    """(messages, contact, company) this person may see, or 404/403."""
    role = crm_perms.role_of(request)
    contact = company = None
    if params.get("contact"):
        if not _uuid(params["contact"]):
            raise Http404
        contact = crm_perms.contact_queryset_for(request, Contact.objects.all()).filter(
            pk=params["contact"]).select_related("company").first()
        if contact is None:
            raise Http404
        company_id = contact.company_id
    elif params.get("company"):
        company = _company_for(request, params["company"])
        company_id = company.pk
    else:
        raise Http404
    if role == Role.VA and (company_id is None
                            or company_id not in crm_perms.assigned_company_ids(request)):
        return None, contact, company
    messages = EmailMessage.objects.all()
    if contact is not None:
        messages = messages.filter(Q(contact=contact) | Q(thread__contact=contact))
    else:
        messages = messages.filter(Q(thread__client_company=company)
                                   | Q(contact__company=company)
                                   | Q(thread__contact__company=company))
    threads = crm_perms.threads_without_money(request, EmailThread.objects.all())
    messages = messages.filter(thread__in=threads)
    return messages, contact, company


def _other_party(message) -> str:
    if message.direction == "inbound":
        return message.from_address
    return (message.to_addresses or [""])[0]


def _reply_state(request, message):
    """(may_reply, from_line, refusal)."""
    if message.thread.is_financial:
        return False, "", "An invoice's mail is answered from the invoice."
    mailbox = message.thread.mailbox
    if mailbox is not None and not mailboxes.is_connected(mailbox):
        return False, "", (f"{mailbox.email_address} is disconnected, so replies can't go "
                           "from it. Connect it again in Settings → Email.")
    if not _other_party(message):
        return False, "", ""
    if mailbox is not None:
        return True, mailboxes.address_of(mailbox), ""
    from apps.crm.services import sender

    return True, sender.resolve_from(request.tenant, request.user, "manual"), ""


def _item(request, message) -> dict:
    when = message.received_at or message.sent_at or message.created_at
    may, reply_from, refusal = _reply_state(request, message)
    mailbox = message.thread.mailbox
    return {
        "id": str(message.pk), "direction": message.direction,
        "from_address": message.from_address, "to_addresses": message.to_addresses or [],
        "cc_addresses": message.cc_addresses or [], "subject": message.subject,
        "when": when.isoformat() if when else None,
        "snippet": " ".join((message.body_stripped or message.body_text or "").split())[:240],
        "body": message.body_text or message.body_stripped or "",
        "mailbox": {"id": str(mailbox.pk), "label": mailbox.label or mailbox.email_address,
                    "address": mailbox.email_address} if mailbox else None,
        "contact": str(message.contact_id) if message.contact_id else None,
        "may_reply": may, "reply_from": reply_from, "reply_refusal": refusal,
    }


class MailView(viewsets.ViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def list(self, request):
        messages, contact, company = _scope(request, request.query_params)
        if messages is None:
            return Response({"detail": "Mail is for the assistants assigned to this client."},
                            status=403)
        try:
            page = max(1, int(request.query_params.get("page") or 1))
        except ValueError:
            page = 1
        ordered = messages.select_related("thread", "thread__mailbox").annotate(
            at=Coalesce("received_at", "sent_at", "created_at")).order_by("-at", "-created_at")
        rows = list(ordered[(page - 1) * PAGE: page * PAGE + 1])
        return Response({"results": [_item(request, m) for m in rows[:PAGE]],
                         "page": page, "previous": page > 1, "next": len(rows) > PAGE})

    @action(detail=False, methods=["post"])
    def reply(self, request):
        """Reply in place, through the mailbox its thread is in. Sent at once
        by the practice owner or an associate; an assistant's is a draft in
        the Outbox, as their manual mail always is."""
        from apps.crm.services import outbox

        found = EmailMessage.objects.filter(pk=request.data.get("message")).select_related(
            "thread", "thread__mailbox", "contact").first() \
            if _uuid(request.data.get("message")) else None
        if found is None:
            raise Http404
        thread = found.thread
        params = {"contact": str(thread.contact_id)} if thread.contact_id else \
            {"company": str(thread.client_company_id)} if thread.client_company_id else {}
        messages, _, _ = _scope(request, params)
        if messages is None:
            return Response({"detail": "Mail is for the assistants assigned to this client."},
                            status=403)
        if not messages.filter(pk=found.pk).exists():
            raise Http404
        may, _, refusal = _reply_state(request, found)
        if not may:
            return Response({"detail": refusal or "There is nobody to reply to."}, status=409)
        body = str(request.data.get("body_text") or "").strip()
        if not body:
            return Response({"body_text": "Write the reply first."}, status=400)
        subject = found.subject if found.subject.lower().startswith("re:") \
            else f"Re: {found.subject}".strip()
        from apps.crm.services.transport import TransportUnavailable

        role = crm_perms.role_of(request)
        try:
            message = outbox.create_message(
                tenant=request.tenant, producer=outbox.P.MANUAL, role=role, actor=request.user,
                to_contact=thread.contact or found.contact, to_address=_other_party(found),
                subject=subject[:255], body_text=body, thread=thread,
                mailbox=thread.mailbox if mailboxes.is_connected(thread.mailbox) else None,
                category="transactional", source_type="mail_reply", source_id=found.pk)
        except outbox.SendNotPermitted as exc:
            return Response({"detail": str(exc)}, status=403)
        except TransportUnavailable as exc:
            return Response({"detail": str(exc)}, status=409)

        sent = message.state == outbox.S.SENT
        return Response({"state": message.state, "outbox": str(message.pk),
                         "detail": f"Sent from {message.from_address}." if sent else
                         "Saved as a draft in the Outbox for the practice owner or an "
                         "associate to approve."}, status=201)
