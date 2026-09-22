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

from apps.crm.services import gmail_oauth
from apps.meetings import approval, drive as drive_service, ingest, parsing
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
    """The folder: connecting it, its cursor, and its health (FR-5.1, FR-5.7).

    Connecting has **two steps that fail separately**, so they are two calls:
    `consent` grants the app `drive.readonly` on the FF's Google account, and
    `check`/`create` point it at one folder. A screen that folded them into a
    single button would have to report "it didn't work" for two quite different
    problems with two quite different fixes.
    """

    def require_founder(self, request):
        if not meeting_perms.may_connect(request):
            self.permission_denied(request, message=(
                "Connecting the notes folder is the founder's. "
                "Everything else in the queue is yours."))

    def list(self, request):
        return Response(ingest.health(request.tenant))

    @action(detail=False, methods=["post"], url_path="consent")
    def consent(self, request):
        """Step one — hand back the Google consent URL for `drive.readonly`.

        It asks for the Gmail scopes **as well**: `include_granted_scopes` plus
        the full list means re-consenting for Drive re-grants sending rather
        than replacing it, so an FF who does this does not stop being able to
        send mail halfway through the afternoon.
        """
        self.require_founder(request)
        if not gmail_oauth.is_configured():
            return Response({"detail": (
                "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set, "
                "so there is nothing to connect to. See docs/05_dev_environment.md §5a."
            )}, status=400)
        state = gmail_oauth.new_state()
        request.session[gmail_oauth.STATE_SESSION_KEY] = state
        request.session[gmail_oauth.RETURN_SESSION_KEY] = "meetings"
        request.session[gmail_oauth.DRIVE_SESSION_KEY] = True
        email = request.user.email
        return Response({
            "authorization_url": gmail_oauth.authorization_url(
                state, login_hint=email, hd=gmail_oauth.workspace_domain(email),
                drive=True),
            "redirect_uri": gmail_oauth.redirect_uri(),
        })

    @action(detail=False, methods=["post"], url_path="check")
    def check(self, request):
        """Step two, dry — read the folder and say what it is. Saves nothing."""
        self.require_founder(request)
        return self._describe(request, save=False)

    def create(self, request):
        """Step two, committed — the same read, then the watch. One per tenant."""
        self.require_founder(request)
        return self._describe(request, save=True)

    def _describe(self, request, *, save: bool):
        raw = request.data.get("folder") or request.data.get("folder_id") or ""
        folder_id = drive_service.folder_id_from(raw)
        if not folder_id:
            return Response({"detail": (
                "That does not look like a Drive folder. Open the folder in "
                "Drive and paste its web address."
            )}, status=400)
        try:
            info = ingest.describe_folder(request.tenant, folder_id)
        except ingest.NotConnected as exc:
            return Response({"detail": str(exc)}, status=409)
        except drive_service.DriveUnavailable as exc:
            return Response({"detail": str(exc)}, status=400)

        found = {"folder_id": info.folder_id, "name": info.name, "files": info.files,
                 "readable": info.readable, "truncated": info.truncated}
        if not save:
            return Response(found)

        watch = DriveWatch.objects.filter(tenant=request.tenant).first()
        # A different folder means the old cursor describes a run we are no
        # longer doing; the same folder keeps its place, so reconnecting after
        # a disconnect picks up where it left off rather than replaying.
        moved = watch is not None and watch.folder_id != folder_id
        watch, _ = DriveWatch.objects.update_or_create(
            tenant=request.tenant,
            defaults={"folder_id": folder_id, "folder_name": info.name,
                      "is_active": True, "last_error": "",
                      **({"page_token": ""} if moved or watch is None else {})},
        )
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.folder_connected",
            target_type="drive_watch", target_id=watch.pk,
            payload={"folder_id": folder_id, "folder_name": info.name,
                     "files": info.files, "readable": info.readable,
                     "cursor_reset": moved})
        return Response({**ingest.health(request.tenant), "found": found}, status=201)

    @action(detail=False, methods=["post"], url_path="disconnect")
    def disconnect(self, request):
        """Stop watching. **Keeps the cursor and every proposal already made** —
        this is "stop looking", not "forget what you read"."""
        self.require_founder(request)
        watch = DriveWatch.objects.filter(tenant=request.tenant).first()
        if watch is None:
            return Response({"detail": "No folder is connected."}, status=400)
        watch.is_active = False
        watch.save(update_fields=["is_active", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.folder_disconnected",
            target_type="drive_watch", target_id=watch.pk,
            payload={"folder_id": watch.folder_id})
        return Response(ingest.health(request.tenant))

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
