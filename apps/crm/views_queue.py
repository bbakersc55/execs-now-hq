"""The sending queue (owner, 2026-09-28): everything waiting to go, of every
category, in one list.

Before this, drafts waited in the Outbox and digests waited on their own
screen. The rules about what waits are unchanged — this only puts it in one
place. An Outbox row goes out when approved; a digest, approved here, goes at
its send window as it always has, and `hold_all_digests` still decides what
waits at all. Every action goes through the same service call its own screen
used, so the role boundaries are the ones already tested (a VA can read and
prepare; only the FF or a CF approves).

The Outbox stays the send log.
"""

from __future__ import annotations

from django.http import Http404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import OutboxMessage
from apps.crm.services import email_layout, outbox, unsubscribe
from apps.tenancy.models import CLIENT_ROLES

S = OutboxMessage.State
WAITING = (S.DRAFT, S.PENDING_APPROVAL)


def _name(contact) -> str:
    return f"{contact.first_name} {contact.last_name}".strip() if contact else ""


class SendingQueueView(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    # ------------------------------------------------------------ the rows

    def _messages(self, request):
        return crm_perms.outbox_queryset_for(request, OutboxMessage.objects.filter(
            state__in=WAITING).select_related("to_contact"))

    def _digests(self, request):
        from apps.work.models import Digest

        qs = Digest.objects.filter(state=Digest.State.PENDING).select_related("contact")
        role = crm_perms.role_of(request)
        if role in CLIENT_ROLES:
            return qs.none()
        if role == crm_perms.Role.CF:
            qs = qs.filter(contact__company_id__in=crm_perms.assigned_company_ids(request))
        return qs

    def _message_row(self, m) -> dict:
        return {
            "key": f"outbox:{m.pk}", "kind": "outbox", "id": str(m.pk),
            "category": unsubscribe.category_of(m),
            "label": m.get_producer_display(),
            "to_name": _name(m.to_contact), "to_address": m.to_address,
            "from_address": m.from_address, "subject": m.subject,
            "created_at": m.created_at.isoformat(),
            "expires_at": m.send_by.isoformat() if m.send_by else None,
            "sends": "when approved",
            "warning": m.warning, "is_ai_generated": m.is_ai_generated,
            "body_text": m.body_text, "body_html": m.body_html,
        }

    def _digest_row(self, d) -> dict:
        from apps.work import digests as digest_service

        return {
            "key": f"digest:{d.pk}", "kind": "digest", "id": str(d.pk),
            "category": unsubscribe.UPDATES,
            "label": f"Progress digest ({d.get_cadence_display().lower()})",
            "to_name": _name(d.contact), "to_address": d.contact.primary_email or "",
            "from_address": d.tenant.from_address, "subject": digest_service._subject(d),
            "created_at": (d.generated_at or d.created_at).isoformat(),
            "expires_at": d.send_window_at.isoformat() if d.send_window_at else None,
            "sends": "at its send window, if approved before it",
            "warning": d.stale_reason if d.is_stale else "",
            "is_ai_generated": d.is_ai_generated,
            "body_text": d.body_text, "body_html": "",
        }

    def list(self, request):
        """`?category=marketing|updates|transactional`, `?recipient=` (name or
        address, any part). Soonest to expire first."""
        category = request.query_params.get("category", "")
        who = (request.query_params.get("recipient") or "").strip().lower()
        rows = [self._message_row(m) for m in self._messages(request)]
        rows += [self._digest_row(d) for d in self._digests(request)]
        if category:
            rows = [r for r in rows if r["category"] == category]
        if who:
            rows = [r for r in rows if who in r["to_name"].lower()
                    or who in r["to_address"].lower()]
        rows.sort(key=lambda r: (r["expires_at"] is None, r["expires_at"] or "",
                                 r["created_at"]))
        return Response(rows)

    def _load(self, request, key):
        kind, _, pk = (key or "").partition(":")
        if kind == "outbox":
            found = self._messages(request).filter(pk=pk).first()
        elif kind == "digest":
            found = self._digests(request).filter(pk=pk).first()
        else:
            found = None
        if found is None:
            raise Http404
        return kind, found

    # ------------------------------------------------------------ preview

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """Exactly as it lands: the same function as the send, with the logo
        embedded for a browser. JSON, for a sandboxed frame — never served as
        a page from this origin, because a campaign may be raw HTML."""
        kind, item = self._load(request, request.query_params.get("key"))
        if kind == "outbox":
            html, text = email_layout.for_delivery(item)
            subject, sender, to = item.subject, item.from_address, item.to_address
        else:
            from apps.work import digests as digest_service

            body_html, body_text = digest_service.email_for(
                item, footer_url=digest_service.preview_footer_url())
            stand_in = OutboxMessage(tenant=item.tenant, producer=OutboxMessage.Producer.DIGEST,
                                     category=unsubscribe.UPDATES, to_contact=item.contact,
                                     to_address=item.contact.primary_email or "",
                                     subject=digest_service._subject(item),
                                     body_text=body_text, body_html=body_html)
            html, text = email_layout.for_delivery(stand_in)
            subject, sender, to = stand_in.subject, item.tenant.from_address, stand_in.to_address
        html, _ = email_layout.with_logo(html, item.tenant, as_data_uri=True)
        return Response({"subject": subject, "from": sender, "to": to,
                         "html": html, "text": text})

    # ------------------------------------------------------------ actions

    def _each(self, request, act):
        keys = request.data.get("keys") or []
        if not isinstance(keys, list) or not keys:
            return Response({"detail": "Select at least one."}, status=400)
        done, failed = [], []
        for key in keys:
            try:
                kind, item = self._load(request, key)
                act(kind, item)
                done.append(key)
            except Http404:
                failed.append({"key": key, "detail": "Not in the queue any more."})
            except Exception as exc:          # named per item, never swallowed
                failed.append({"key": key, "detail": str(exc)})
        return Response({"done": done, "done_count": len(done), "failed": failed})

    @action(detail=False, methods=["post"])
    def approve(self, request):
        """Approve each, through its own path. A digest approved here still
        waits for its send window."""
        from apps.work import digests as digest_service

        role = crm_perms.role_of(request)

        def act(kind, item):
            if kind == "outbox":
                outbox.approve(item, actor=request.user, role=role)
            else:
                digest_service.approve(item, actor=request.user, role=role)
        return self._each(request, act)

    @action(detail=False, methods=["post"])
    def skip(self, request):
        """Skip each: an Outbox draft is rejected, a digest skipped."""
        from apps.work import digests as digest_service

        role = crm_perms.role_of(request)

        def act(kind, item):
            if kind == "outbox":
                outbox.reject(item, actor=request.user)
            else:
                digest_service.skip(item, actor=request.user, role=role)
        return self._each(request, act)
