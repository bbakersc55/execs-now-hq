"""Module 5's API — the review queue, and the folder behind it.

Status codes follow the matrix §1 rule: out of scope is 404 (a 403 would
confirm the row exists), in scope but role-forbidden is 403. A client role is
refused the whole module, which is 403 on a route that exists for staff.
"""

from __future__ import annotations

import uuid

from django.http import Http404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.meetings import approval, ingest, parsing
from apps.meetings import permissions as meeting_perms
from apps.meetings import serializers as meeting_serializers
from apps.meetings.models import DriveWatch, MeetingProposal, ProposalItem
from apps.tenancy.models import AuditEvent


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


class MeetingViewSetBase(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "membership", None) is None:
            self.permission_denied(request, message="No membership for this tenant.")
        if not meeting_perms.may_use(request):
            # Matrix 11.1 — no client-facing surface exists here, including for
            # a meeting about their own company.
            self.permission_denied(
                request, message="Meeting ingestion is the practice's.")


class DriveWatchViewSet(MeetingViewSetBase):
    """The folder, its cursor, and its health (FR-5.1, FR-5.7)."""

    def list(self, request):
        return Response(ingest.health(request.tenant))

    def create(self, request):
        """Connect a folder. One per tenant in Beta."""
        folder_id = (request.data.get("folder_id") or "").strip()
        if not folder_id:
            return Response({"detail": "Which folder? Paste its id from the Drive URL."},
                            status=400)
        watch, _ = DriveWatch.objects.update_or_create(
            tenant=request.tenant,
            defaults={"folder_id": folder_id, "is_active": True,
                      "folder_name": (request.data.get("folder_name") or "").strip()},
        )
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.folder_connected",
            target_type="drive_watch", target_id=watch.pk,
            payload={"folder_id": folder_id})
        return Response(ingest.health(request.tenant), status=201)

    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request):
        """"Sync now" — the same job the timer runs (FR-5.3)."""
        try:
            report = ingest.poll(request.tenant)
        except ingest.NotConnected as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({
            "recorded": len(report["recorded"]),
            "skipped": [meeting_serializers.represent_source_file(f)
                        for f in report["skipped"]],
            "failed": [meeting_serializers.represent_source_file(f)
                       for f in report["failed"]],
            "error": report["error"],
            "health": ingest.health(request.tenant),
        })


class ProposalViewSet(MeetingViewSetBase):
    """The queue itself. Scoped by `proposal-scope` for a CF (matrix §11)."""

    def proposals(self):
        return meeting_perms.proposals_for(
            self.request, MeetingProposal.objects.select_related("source_file"))

    def load(self, pk):
        if not _is_uuid(pk):
            raise Http404
        found = self.proposals().filter(pk=pk).first()
        if found is None:
            raise Http404
        return found

    def list(self, request):
        state = request.query_params.get("state", "open")
        qs = self.proposals()
        if state == "open":
            qs = qs.filter(state__in=[MeetingProposal.State.PENDING,
                                      MeetingProposal.State.PARTIALLY_ACTIONED])
        elif state != "all":
            qs = qs.filter(state=state)
        return Response([meeting_serializers.represent_proposal(p)
                         for p in qs.order_by("-created_at")[:200]])

    def retrieve(self, request, pk=None):
        return Response(meeting_serializers.represent_proposal(self.load(pk), full=True))

    def partial_update(self, request, pk=None):
        """The summary is reviewed with the proposal (R11a, FR-5.8b)."""
        proposal = self.load(pk)
        fields = []
        if "summary" in request.data:
            proposal.summary = request.data["summary"] or ""
            fields.append("summary")
        if "summary_discarded" in request.data:
            proposal.summary_discarded = bool(request.data["summary_discarded"])
            fields.append("summary_discarded")
        if fields:
            proposal.save(update_fields=fields + ["updated_at"])
        return Response(meeting_serializers.represent_proposal(proposal, full=True))

    @action(detail=True, methods=["post"])
    def reparse(self, request, pk=None):
        """A fresh proposal that supersedes this one (FR-5.17). Approved items
        are untouched; it writes an `ai_call` like any other read."""
        proposal = self.load(pk)
        fresh = parsing.reparse(proposal, actor=request.user)
        if fresh is None:
            return Response({"detail": "The re-parse failed. The old proposal stands "
                                       "and the call is on AI usage."}, status=502)
        return Response(meeting_serializers.represent_proposal(fresh, full=True),
                        status=201)


class ProposalItemViewSet(MeetingViewSetBase):
    """One proposed thing, approved or rejected on its own (FR-5.15)."""

    def list(self, request):
        """The items of one proposal. `?proposal=` is required: there is no
        useful list of everything proposed everywhere, and a route that
        answers one is a route that leaks one."""
        proposal_id = request.query_params.get("proposal")
        if not _is_uuid(proposal_id or ""):
            return Response({"detail": "Ask for one proposal's items."}, status=400)
        items = meeting_perms.items_for(request).filter(proposal_id=proposal_id)
        return Response([meeting_serializers.represent_item(item) for item in items])

    def load_item(self, pk):
        if not _is_uuid(pk):
            raise Http404
        found = meeting_perms.items_for(self.request).filter(pk=pk).first()
        if found is None:
            raise Http404
        return found

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        item = self.load_item(pk)
        if item.state != ProposalItem.State.PENDING:
            return Response({"detail": "That one has already been decided."}, status=409)
        role = request.membership.role
        try:
            if item.kind == ProposalItem.Kind.PARTICIPANT:
                approval.approve_participant(item, actor=request.user, role=role,
                                             choice=request.data or {})
                # FR-5.8a — the meeting appears on every approved participant's
                # timeline, and is created once.
                approval.create_meeting(item.proposal, actor=request.user)
            else:
                approval.approve_task_item(item, actor=request.user, role=role,
                                           choice=request.data or {})
        except approval.ApprovalRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="meeting.item_approved",
            target_type="proposal_item", target_id=item.pk,
            payload={"kind": item.kind, "created": item.created_record_type})
        item.refresh_from_db()
        return Response(meeting_serializers.represent_item(item), status=201)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        item = self.load_item(pk)
        approval.reject(item, actor=request.user)
        return Response(meeting_serializers.represent_item(item))
