"""Invoices over the API (matrix 13.4a–13.4f, `docs/p4a_client_invoicing.md` §5).

Status codes follow the rest of the app: a role that may never see invoices
gets 403 (an assistant) or 404 (a client user, who has the portal routes
instead); a row outside what an associate may see is 404, never 403, so a
probe cannot learn that it exists.
"""

from __future__ import annotations

import csv

from django.http import Http404, HttpResponse
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing import money, services
from apps.billing.models import (
    ClientInvoice, ClientInvoiceLine, ClientInvoiceSchedule, ClientPayment,
)
from apps.crm import permissions as crm_perms
from apps.crm.models import Company, Contact, OutboxMessage
from apps.tenancy.models import CLIENT_ROLES, AuditEvent, Role

S = ClientInvoice.Status
NO_FINANCIALS = "Assistants have no access to invoices."
OWNER_ONLY = "Only the practice owner can do this."


def _name(contact) -> str:
    return f"{contact.first_name} {contact.last_name}".strip() if contact else ""


def _person(user) -> str:
    return (user.full_name or user.email) if user else ""


def _send_state(invoice) -> str:
    """Where the email is: waiting for approval, sent back, or neither."""
    message = invoice.outbox_message
    if invoice.status != S.READY or message is None:
        return ""
    if message.state in (OutboxMessage.State.PENDING_APPROVAL, OutboxMessage.State.DRAFT):
        return "waiting"
    return "sent_back"


def represent_row(invoice, today=None) -> dict:
    return {
        "id": str(invoice.pk), "kind": invoice.kind, "number": invoice.number or "",
        "status": invoice.status, "status_label": invoice.get_status_display(),
        "overdue": services.is_overdue(invoice, today),
        "client_company": ({"id": str(invoice.client_company_id),
                            "name": invoice.client_company.name}
                           if invoice.client_company_id else None),
        "contact": {"id": str(invoice.contact_id), "name": _name(invoice.contact)},
        "issue_date": invoice.issue_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "total_cents": invoice.total_cents, "paid_cents": invoice.paid_cents,
        "balance_cents": invoice.balance_cents,
        "from_schedule": invoice.schedule_id is not None,
        "send_state": _send_state(invoice),
    }


def represent(invoice) -> dict:
    lines = ClientInvoiceLine.all_objects.filter(invoice=invoice).order_by(
        "position", "created_at")
    payments = (ClientPayment.all_objects.filter(invoice=invoice)
                .select_related("recorded_by", "removed_by").order_by("paid_on", "created_at"))
    return {
        **represent_row(invoice),
        "subtotal_cents": invoice.subtotal_cents, "tax_cents": invoice.tax_cents,
        "currency": invoice.currency, "notes": invoice.notes, "terms": invoice.terms,
        "pay_instructions": invoice.pay_instructions, "pay_url": invoice.pay_url,
        "email_to": invoice.email_to, "email_subject": invoice.email_subject,
        "email_body": invoice.email_body, "bill_to": invoice.bill_to or {},
        "has_pdf": invoice.pdf_id is not None,
        "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None,
        "voided_at": invoice.voided_at.isoformat() if invoice.voided_at else None,
        "void_reason": invoice.void_reason,
        "lines": [{
            "id": str(line.pk), "description": line.description,
            "quantity": str(line.quantity), "unit_price_cents": line.unit_price_cents,
            "amount_cents": line.amount_cents,
            "project": str(line.project_id) if line.project_id else None,
            "goal": str(line.goal_id) if line.goal_id else None,
        } for line in lines],
        "payments": [{
            "id": str(p.pk), "amount_cents": p.amount_cents, "paid_on": p.paid_on.isoformat(),
            "method": p.method, "method_label": p.get_method_display(),
            "reference": p.reference, "note": p.note, "recorded_by": _person(p.recorded_by),
            "removed": p.removed_at is not None, "remove_reason": p.remove_reason,
            "removed_by": _person(p.removed_by),
        } for p in payments],
        "merge_fields": list(services.MERGE_FIELDS),
    }


class BillingViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _role(self):
        return crm_perms.role_of(self.request)

    def _staff(self):
        """Refuses everyone who has no invoices at all. Returns a response to
        give back, or None for the practice owner and an associate."""
        role = self._role()
        if role in CLIENT_ROLES or role is None:
            raise Http404
        if role == Role.VA:
            return Response({"detail": NO_FINANCIALS}, status=403)
        return None

    def _owner(self):
        refused = self._staff()
        if refused:
            return refused
        if self._role() != Role.FF:
            return Response({"detail": OWNER_ONLY}, status=403)
        return None

    def invoices(self):
        """What this person may see (13.4a). An associate: assigned client
        companies, and never an invoice to a contact."""
        qs = ClientInvoice.objects.select_related("client_company", "contact",
                                                  "outbox_message")
        role = self._role()
        if role == Role.FF:
            return qs
        if role == Role.CF:
            return qs.filter(
                client_company_id__in=crm_perms.assigned_company_ids(self.request))
        return qs.none()

    def load(self, pk) -> ClientInvoice:
        invoice = self.invoices().filter(pk=pk).first()
        if invoice is None:
            raise Http404
        return invoice

    def _company(self, pk):
        """A client company this person may bill, or 404."""
        company = crm_perms.company_queryset_for(
            self.request, Company.objects.filter(deleted_at__isnull=True)).filter(
                pk=pk).first() if pk else None
        if company is None:
            raise Http404
        return company

    def _contact(self, pk):
        contact = Contact.objects.filter(pk=pk, deleted_at__isnull=True).first() \
            if pk else None
        if contact is None:
            raise Http404
        return contact

    @staticmethod
    def _refusal(exc):
        return Response({"detail": str(exc)}, status=exc.status)


class InvoiceViewSet(BillingViewSet):

    def _filtered(self, request):
        qs = self.invoices()
        params = request.query_params
        status = params.get("status")
        if status == "overdue":
            from django.utils import timezone

            qs = qs.filter(status__in=ClientInvoice.OPEN, due_date__lt=timezone.localdate())
        elif status:
            qs = qs.filter(status=status)
        if params.get("company"):
            qs = qs.filter(client_company_id=params["company"])
        try:
            if params.get("from"):
                qs = qs.filter(issue_date__gte=services._a_date(params["from"], "from"))
            if params.get("to"):
                qs = qs.filter(issue_date__lte=services._a_date(params["to"], "to"))
        except services.BillingError:
            return qs.none()
        return qs.order_by("-issue_date", "-created_at")

    def list(self, request):
        refused = self._staff()
        if refused:
            return refused
        qs = self._filtered(request)
        return Response({"invoices": [represent_row(invoice) for invoice in qs[:500]],
                         "totals": services.totals(qs),
                         "drafts_from_schedules": self.invoices().filter(
                             status=S.DRAFT, schedule__isnull=False).count()})

    @action(detail=False, methods=["get"])
    def export(self, request):
        """The list as it is filtered, and its totals, as CSV."""
        refused = self._staff()
        if refused:
            return refused
        qs = self._filtered(request)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="invoices.csv"'
        out = csv.writer(response)
        out.writerow(["Number", "Status", "Overdue", "Client", "Addressed to", "Issued", "Due",
                      "Total", "Paid", "Balance"])
        plain = lambda value: f"{value / 100:.2f}"  # noqa: E731
        for invoice in qs:
            out.writerow([
                invoice.number or "", invoice.get_status_display(),
                "yes" if services.is_overdue(invoice) else "",
                invoice.client_company.name if invoice.client_company_id else "",
                _name(invoice.contact), invoice.issue_date.isoformat(),
                invoice.due_date.isoformat(), plain(invoice.total_cents),
                plain(invoice.paid_cents), plain(invoice.balance_cents)])
        totals = services.totals(qs)
        out.writerow([])
        for label, key in (("Invoiced", "invoiced_cents"), ("Paid", "paid_cents"),
                           ("Outstanding", "outstanding_cents"),
                           ("Overdue", "overdue_cents")):
            out.writerow([label, plain(totals[key])])
        return response

    def create(self, request):
        refused = self._staff()
        if refused:
            return refused
        data = request.data
        kind = data.get("kind") or ClientInvoice.Kind.ONE_OFF
        if kind == ClientInvoice.Kind.CONTACT:
            # 13.4e: an invoice to someone who is not a client company.
            if self._role() != Role.FF:
                return Response({"detail": OWNER_ONLY}, status=403)
            company = None
        else:
            company = self._company(data.get("client_company"))
        contact = self._contact(data.get("contact"))
        changes = {field: data[field] for field in services.EDITABLE if field in data}
        try:
            invoice = services.create_draft(
                request.tenant, actor=request.user, kind=kind, client_company=company,
                contact=contact, lines=data.get("lines") or [], **changes)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(represent(invoice), status=201)

    def retrieve(self, request, pk=None):
        refused = self._staff()
        if refused:
            return refused
        return Response(represent(self.load(pk)))

    def partial_update(self, request, pk=None):
        refused = self._staff()
        if refused:
            return refused
        invoice = self.load(pk)
        data = request.data
        changes = {field: data[field] for field in services.EDITABLE if field in data}
        contact = self._contact(data["contact"]) if data.get("contact") else None
        try:
            invoice = services.update_draft(invoice, actor=request.user,
                                            lines=data.get("lines"), contact=contact,
                                            **changes)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(represent(invoice))

    def destroy(self, request, pk=None):
        refused = self._staff()
        if refused:
            return refused
        try:
            services.delete_draft(self.load(pk), actor=request.user)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(status=204)

    def _do(self, request, pk, fn, *, owner):
        refused = self._owner() if owner else self._staff()
        if refused:
            return refused
        invoice = self.load(pk)
        try:
            fn(invoice)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(represent(self.load(pk)))

    @action(detail=True, methods=["post"], url_path="make-ready")
    def make_ready(self, request, pk=None):
        return self._do(request, pk, lambda i: services.make_ready(
            i, actor=request.user, role=self._role()), owner=False)

    @action(detail=True, methods=["post"], url_path="back-to-draft")
    def back_to_draft(self, request, pk=None):
        return self._do(request, pk, lambda i: services.back_to_draft(
            i, actor=request.user), owner=False)

    @action(detail=True, methods=["post"], url_path="queue-again")
    def queue_again(self, request, pk=None):
        return self._do(request, pk, lambda i: services.queue_again(
            i, actor=request.user, role=self._role()), owner=False)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """13.4c — the practice owner's approval, or a resend."""
        return self._do(request, pk, lambda i: services.send(
            i, actor=request.user, role=self._role(),
            to_address=(request.data.get("to_address") or "").strip() or None), owner=True)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        data = request.data
        return self._do(request, pk, lambda i: services.record_payment(
            i, actor=request.user, amount_cents=data.get("amount_cents"),
            paid_on=data.get("paid_on"), method=data.get("method"),
            reference=data.get("reference", ""), note=data.get("note", "")), owner=True)

    @action(detail=True, methods=["post"], url_path="remove-payment")
    def remove_payment(self, request, pk=None):
        def remove(invoice):
            payment = ClientPayment.objects.filter(
                invoice=invoice, pk=request.data.get("payment")).first()
            if payment is None:
                raise services.BillingError("That payment is not on this invoice.",
                                            status=404)
            services.remove_payment(payment, actor=request.user,
                                    reason=request.data.get("reason"))
        return self._do(request, pk, remove, owner=True)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        return self._do(request, pk, lambda i: services.void(
            i, actor=request.user, reason=request.data.get("reason")), owner=True)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        refused = self._staff()
        if refused:
            return refused
        return pdf_response(self.load(pk))

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """A draft as it would print, before it has a number. Nothing is
        stored, and nothing is numbered by looking."""
        from apps.billing import pdf

        refused = self._staff()
        if refused:
            return refused
        invoice = self.load(pk)
        if invoice.pdf_id and invoice.status != S.DRAFT:
            return pdf_response(invoice)
        contact = invoice.contact
        invoice.number = invoice.number or "DRAFT"
        invoice.bill_to = {
            "name": _name(contact),
            "company": invoice.client_company.name if invoice.client_company_id else "",
            "email": invoice.email_to or services._email_of(contact),
            "address": services._address_of(invoice)}
        response = HttpResponse(pdf.render_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="Invoice-draft.pdf"'
        return response

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """The audit trail of this invoice, in order (§4)."""
        refused = self._staff()
        if refused:
            return refused
        invoice = self.load(pk)
        events = (AuditEvent.objects.filter(target_type="client_invoice",
                                            target_id=invoice.pk)
                  .select_related("actor").order_by("created_at"))
        return Response([{
            "at": event.created_at.isoformat(), "what": event.verb.removeprefix("billing."),
            "by": _person(event.actor) or "The schedule",
            "before": event.payload.get("before", ""), "after": event.payload.get("after", ""),
            "reason": event.payload.get("reason", ""),
            "amount_cents": event.payload.get("amount_cents"),
            "to": event.payload.get("to", ""),
        } for event in events])


def pdf_response(invoice):
    from apps.tenancy import storage

    if invoice.pdf_id is None:
        raise Http404
    try:
        content = storage.read(invoice.pdf)
    except storage.StorageError:
        return Response({"detail": "The invoice's PDF could not be read just now."},
                        status=503)
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Invoice-{invoice.number}.pdf"'
    return response


class InvoiceSettingsView(BillingViewSet):
    """13.4f — the practice owner's. An associate reads what a new invoice
    starts with, because they write drafts."""

    @staticmethod
    def _represent(row) -> dict:
        return {
            "prefix": row.prefix, "next_value": row.next_value, "terms_days": row.terms_days,
            "default_notes": row.default_notes, "default_terms": row.default_terms,
            "pay_instructions": row.pay_instructions,
            "email_subject": row.email_subject or services.DEFAULT_SUBJECT,
            "email_body": row.email_body or services.DEFAULT_BODY,
            "merge_fields": list(services.MERGE_FIELDS),
            "next_number": f"{row.prefix}{row.next_value:04d}",
        }

    def list(self, request):
        refused = self._staff()
        if refused:
            return refused
        return Response(self._represent(services.settings_for(request.tenant)))

    def create(self, request):
        refused = self._owner()
        if refused:
            return refused
        try:
            row = services.update_settings(request.tenant, dict(request.data),
                                           actor=request.user)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(self._represent(row))


class ScheduleViewSet(BillingViewSet):

    def schedules(self):
        qs = ClientInvoiceSchedule.objects.select_related("client_company", "contact")
        if self._role() == Role.FF:
            return qs
        if self._role() == Role.CF:
            return qs.filter(
                client_company_id__in=crm_perms.assigned_company_ids(self.request))
        return qs.none()

    @staticmethod
    def _represent(row) -> dict:
        lines = [{**line, "amount_cents": money.line_amount(
            services.Decimal(str(line["quantity"])), line["unit_price_cents"])}
            for line in row.lines]
        return {
            "id": str(row.pk),
            "client_company": {"id": str(row.client_company_id),
                               "name": row.client_company.name},
            "contact": {"id": str(row.contact_id), "name": _name(row.contact)},
            "day_of_month": row.day_of_month, "next_on": row.next_on.isoformat(),
            "ends_on": row.ends_on.isoformat() if row.ends_on else None,
            "lines": lines, "total_cents": sum(line["amount_cents"] for line in lines),
            "notes": row.notes, "terms": row.terms, "is_active": row.is_active,
        }

    def list(self, request):
        refused = self._staff()
        if refused:
            return refused
        qs = self.schedules().order_by("client_company__name", "created_at")
        if request.query_params.get("company"):
            qs = qs.filter(client_company_id=request.query_params["company"])
        return Response([self._represent(row) for row in qs])

    def _save(self, request, schedule=None):
        data = request.data
        fields = {}
        for name in ("day_of_month", "starts_on", "lines", "notes", "terms", "is_active"):
            if name in data:
                fields[name] = data[name]
        if "ends_on" in data:
            fields["ends_on"] = data["ends_on"]
        if data.get("contact"):
            fields["contact"] = self._contact(data["contact"])
        try:
            if schedule is None:
                fields["client_company"] = self._company(data.get("client_company"))
                if "contact" not in fields:
                    raise services.BillingError("Choose who the invoices are addressed to.")
            row = services.save_schedule(request.tenant, actor=request.user,
                                         schedule=schedule, **fields)
        except services.BillingError as exc:
            return self._refusal(exc)
        return Response(self._represent(row), status=201 if schedule is None else 200)

    def create(self, request):
        refused = self._staff()
        if refused:
            return refused
        return self._save(request)

    def partial_update(self, request, pk=None):
        refused = self._staff()
        if refused:
            return refused
        schedule = self.schedules().filter(pk=pk).first()
        if schedule is None:
            raise Http404
        return self._save(request, schedule)


class PortalInvoiceViewSet(viewsets.ViewSet):
    """Matrix 13.4a, the client columns: a client owner and a client team
    member see their own company's invoices, as sent. Never a draft, never one
    not yet sent, never another company's, and never an invoice written to a
    contact rather than to the company."""

    permission_classes = [permissions.IsAuthenticated]

    def invoices(self):
        membership = getattr(self.request, "membership", None)
        if membership is None or membership.role not in CLIENT_ROLES \
                or membership.client_company_id is None:
            raise Http404
        return ClientInvoice.objects.filter(
            client_company_id=membership.client_company_id,
            status__in=ClientInvoice.SEEN_BY_CLIENT).exclude(
                kind=ClientInvoice.Kind.CONTACT)

    def list(self, request):
        rows = self.invoices().order_by("-issue_date", "-created_at")
        return Response([{
            "id": str(invoice.pk), "number": invoice.number,
            "issue_date": invoice.issue_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
            "total_cents": invoice.total_cents, "balance_cents": invoice.balance_cents,
            "status": invoice.status, "status_label": invoice.get_status_display(),
            "overdue": services.is_overdue(invoice),
            # Empty until a processor is connected (P4).
            "pay_url": invoice.pay_url,
        } for invoice in rows])

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        invoice = self.invoices().filter(pk=pk).first()
        if invoice is None:
            raise Http404
        return pdf_response(invoice)
