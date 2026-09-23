"""Module 6's read surface: the shared history, and the unmatched queue.

Matrix §12. **No client-facing surface exists here at all** — these threads
carry internal correspondence *about* a client, so an FCC reading their own
company's history would be reading the practice's notes on them (12.5).

A CF sees the threads of contacts they can already see, which is
`contact_queryset_for` and not a second rule invented here.
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from django.http import Http404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Contact, EmailMessage, EmailThread, UnmatchedInbound
from apps.crm.services import inbound, inbound_poll
from apps.tenancy.models import AuditEvent, Role


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def visible_threads(request, queryset=None):
    """Threads on contacts the caller can already see.

    A thread with no contact — one whose reply has not been filed to anybody —
    is FF and VA only, on the same reasoning as an unreviewed meeting proposal:
    nobody has yet decided whose it is.
    """
    queryset = EmailThread.objects.all() if queryset is None else queryset
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role != Role.CF:
        return queryset.none()
    visible = crm_perms.contact_queryset_for(
        request, Contact.objects.filter(deleted_at__isnull=True))
    return queryset.filter(contact__in=visible)


def visible_messages(request):
    return EmailMessage.objects.filter(thread__in=visible_threads(request))


def represent_message(message) -> dict:
    return {
        "id": str(message.pk),
        "direction": message.direction,
        "from_address": message.from_address,
        "to_addresses": message.to_addresses,
        "subject": message.subject,
        # FR-6.9 — what they wrote, with the conversation under it trimmed off.
        # `raw` is kept, so nothing is lost by showing less.
        "body": message.body_stripped or message.body_text,
        "has_more": bool(message.body_stripped
                         and message.body_text
                         and message.body_stripped != message.body_text.strip()),
        "matched_by": message.matched_by,
        "at": (message.received_at or message.sent_at or message.created_at).isoformat(),
        "attachments": [
            {"id": str(row.pk), "filename": row.filename,
             "content_type": row.content_type, "byte_size": row.byte_size}
            for row in message.attachments.all()
        ],
    }


def represent_thread(thread, *, full=False) -> dict:
    body = {
        "id": str(thread.pk),
        "subject": thread.subject,
        "contact": str(thread.contact_id) if thread.contact_id else None,
        "contact_name": (f"{thread.contact.first_name} {thread.contact.last_name}".strip()
                         if thread.contact_id else ""),
        "last_message_at": (thread.last_message_at.isoformat()
                            if thread.last_message_at else None),
        "message_count": thread.messages.count(),
        "poll_error": thread.poll_error,
    }
    if full:
        # Coalesced, not a three-column sort: an outbound message has no
        # `received_at` and NULLs sort last, which put every reply *before*
        # the thing it was replying to.
        from django.db.models.functions import Coalesce

        body["messages"] = [represent_message(m) for m in
                            thread.messages.prefetch_related("attachments")
                            .annotate(at=Coalesce("received_at", "sent_at",
                                                  "created_at"))
                            .order_by("at")]
    return body


class CommunicationViewSetBase(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]


class EmailThreadViewSet(CommunicationViewSetBase):
    """The shared history (FR-6.7, FR-6.16). One conversation, one place."""

    def list(self, request):
        threads = visible_threads(request).select_related("contact")
        contact_id = request.query_params.get("contact")
        if contact_id:
            if not _is_uuid(contact_id):
                return Response({"detail": "Which contact?"}, status=400)
            threads = threads.filter(contact_id=contact_id)
        threads = threads.order_by("-last_message_at", "-created_at")[:200]
        return Response([represent_thread(t) for t in threads])

    def retrieve(self, request, pk=None):
        if not _is_uuid(pk):
            raise Http404
        thread = visible_threads(request).filter(pk=pk).select_related("contact").first()
        if thread is None:
            raise Http404
        return Response(represent_thread(thread, full=True))

    @action(detail=True, methods=["get"], url_path="raw")
    def raw(self, request, pk=None):
        """FR-6.9 — the full message, exactly as it arrived. Trimming is for
        display, and a reviewer must always be able to see past it."""
        if not _is_uuid(pk):
            raise Http404
        message = visible_messages(request).filter(pk=pk).first()
        if message is None:
            raise Http404
        return Response({"id": str(message.pk), "body_text": message.body_text,
                         "body_html": message.body_html, "raw": message.raw})


class UnmatchedInboundViewSet(CommunicationViewSetBase):
    """R13 — **nothing is ever dropped** (FR-6.8).

    The queue is FF, CF and VA (matrix 12.2/12.3): filing creates no outbound
    mail, which is why a VA may do it.
    """

    def queryset(self):
        role = crm_perms.role_of(self.request)
        if role in (Role.FF, Role.VA):
            return UnmatchedInbound.objects.all()
        if role != Role.CF:
            return UnmatchedInbound.objects.none()
        # A CF sees what is already theirs to see, plus anything unfiled —
        # the queue is work, and a reply from a stranger is not yet anybody's.
        visible = crm_perms.contact_queryset_for(
            self.request, Contact.objects.filter(deleted_at__isnull=True))
        return UnmatchedInbound.objects.filter(
            Q(filed_contact__isnull=True) | Q(filed_contact__in=visible))

    def list(self, request):
        state = request.query_params.get("state", "pending")
        rows = self.queryset()
        if state != "all":
            rows = rows.filter(state=state)
        return Response([{
            "id": str(row.pk),
            "from_address": row.from_address,
            "from_name": row.from_name,
            "subject": row.subject,
            "body": row.body_stripped or row.body_text,
            "reason": row.reason,
            "state": row.state,
            "received_at": row.received_at.isoformat() if row.received_at else None,
            "filed_contact": str(row.filed_contact_id) if row.filed_contact_id else None,
        } for row in rows.order_by("-received_at", "-created_at")[:200]])

    def load(self, pk):
        if not _is_uuid(pk):
            raise Http404
        row = self.queryset().filter(pk=pk).first()
        if row is None:
            raise Http404
        return row

    @action(detail=True, methods=["post"])
    def file(self, request, pk=None):
        """File it to a contact. Creates a record; sends nothing."""
        row = self.load(pk)
        contact_id = request.data.get("contact")
        if not _is_uuid(contact_id or ""):
            return Response({"detail": "Which contact should this go to?"}, status=400)
        contact = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(deleted_at__isnull=True)
        ).filter(pk=contact_id).first()
        if contact is None:
            raise Http404
        try:
            message = inbound.file_to_contact(
                row, contact=contact, actor=request.user,
                add_address=bool(request.data.get("add_address")))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="inbound.filed",
            target_type="unmatched_inbound", target_id=row.pk,
            payload={"contact": str(contact.pk),
                     "address_added": bool(request.data.get("add_address"))})
        row.refresh_from_db()
        return Response({"id": str(row.pk), "state": row.state,
                         "message": str(message.pk),
                         "thread": str(message.thread_id)}, status=201)

    @action(detail=False, methods=["get", "post"], url_path="poll")
    def poll(self, request):
        """"Collect replies now" — the same job the timer runs.

        GET reports where the poll has got to; POST runs it. FF only to run:
        it is the practice's mailbox being read.
        """
        if request.method == "GET":
            return Response(health(request.tenant))
        if crm_perms.role_of(request) != Role.FF:
            self.permission_denied(request, message=(
                "Reading the practice's mailbox is the founder's."))
        try:
            report = inbound_poll.poll(request.tenant)
        except inbound_poll.NotConnected as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({**report, "health": health(request.tenant)})


def health(tenant) -> dict:
    """One line for the screen: can we read, and where have we got to."""
    from django.db.models import Max

    try:
        connection = inbound_poll.reading_connection(tenant)
        can_read, detail = True, ""
        account = connection.email_address
    except inbound_poll.NotConnected as exc:
        can_read, detail, account = False, str(exc), ""
    threads = EmailThread.objects.exclude(gmail_thread_id="")
    return {
        "can_read": can_read,
        "detail": detail,
        "account": account,
        "threads_watched": threads.count(),
        "last_polled_at": (threads.aggregate(Max("last_polled_at"))["last_polled_at__max"]
                           or None) and threads.aggregate(
                               Max("last_polled_at"))["last_polled_at__max"].isoformat(),
        "waiting": UnmatchedInbound.objects.filter(
            state=UnmatchedInbound.State.PENDING).count(),
        "errors": threads.exclude(poll_error="").count(),
    }
