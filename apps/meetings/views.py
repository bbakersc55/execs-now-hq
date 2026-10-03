"""Module 5's API — the review queue, and the folder behind it.

Status codes follow the matrix §1 rule: out of scope is 404 (a 403 would
confirm the row exists), in scope but role-forbidden is 403. A client role is
refused the whole module, which is 403 on a route that exists for staff.
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from django.http import Http404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm.services import gmail_oauth
from apps.meetings import (
    approval, backfill as backfill_service, dismissal, drive as drive_service, ingest,
    parsing,
)
from apps.meetings import permissions as meeting_perms
from apps.meetings import serializers as meeting_serializers
from django.utils import timezone

from apps.meetings.models import (
    DriveBackfill, DriveExclusion, DriveWatch, DriveWatchFolder, Meeting,
    MeetingProposal, MeetingSourceFile, ProposalItem,
)
from apps.tenancy.models import AuditEvent


def _as_date(value):
    """A date from the wire, or None. Never today as a silent default — this
    one decides how much history gets read and what it costs."""
    from datetime import date

    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def add_exclusion(watch, pattern, *, actor, source, extra=None):
    """Put a pattern on the watch's exclusion list, once: the same words in a
    different case are the same exclusion."""
    ingest.exclusions_for(watch)       # the starting ones first, if never added
    existing = (DriveExclusion.objects.filter(watch=watch, deleted_at__isnull=True,
                                              pattern__iexact=pattern).first())
    row = existing or DriveExclusion.objects.create(
        tenant_id=watch.tenant_id, watch=watch, pattern=pattern, source=source,
        created_by=actor)
    AuditEvent.all_objects.create(
        tenant_id=watch.tenant_id, actor=actor, verb="drive.exclusion_added",
        target_type="drive_exclusion", target_id=row.pk,
        payload={"pattern": pattern, "source": source, "already_listed": bool(existing),
                 **(extra or {})})
    return row


class MeetingViewSetBase(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "membership", None) is None:
            self.permission_denied(request, message="You're not a member of this practice.")
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

    def _folder(self, request):
        """An extra folder named on the request, or None for the watch's own.
        A folder that is not this practice's is a 404, as everywhere here."""
        ref = request.data.get("folder") if request.method != "GET" else None
        ref = ref or request.query_params.get("folder")
        if not ref:
            return None
        if not _is_uuid(ref):
            raise Http404
        found = DriveWatchFolder.objects.filter(pk=ref, is_active=True).first()
        if found is None:
            raise Http404
        return found

    # ---------------------------------------------------------- extra folders

    @action(detail=False, methods=["post"], url_path="folders")
    def add_folder(self, request):
        """Watch another folder with the same watch (owner, 2026-09-28).

        `depth=any` reads every folder below it and needs a name pattern —
        Google Meet puts each meeting's notes in a folder of its own, and a
        recursive watch with no pattern would read everything in it.
        """
        self.require_founder(request)
        watch = ingest.watch_for(request.tenant)
        if watch is None:
            return Response({"detail": "Connect the first folder before adding another."},
                            status=409)
        folder_id = drive_service.folder_id_from(
            request.data.get("folder") or request.data.get("folder_id") or "")
        if not folder_id:
            return Response({"detail": "That does not look like a Drive folder. "
                                       "Paste the folder's web address."}, status=400)
        if folder_id == watch.folder_id:
            return Response({"detail": "That folder is already watched."}, status=400)
        depth = request.data.get("depth") or DriveWatchFolder.Depth.ANY
        if depth not in DriveWatchFolder.Depth.values:
            return Response({"detail": "Depth is one level or any depth."}, status=400)
        pattern = (request.data.get("name_pattern", "Notes by Gemini") or "").strip()
        if depth == DriveWatchFolder.Depth.ANY and not pattern:
            return Response({"detail": (
                "A folder read at any depth needs a name to look for, or it would "
                "read everything below it. The default is \u201cNotes by Gemini\u201d."
            )}, status=400)
        try:
            name = ingest.client_for(request.tenant).open_folder(folder_id)
        except ingest.NotConnected as exc:
            return Response({"detail": str(exc)}, status=409)
        except drive_service.DriveUnavailable as exc:
            return Response({"detail": str(exc)}, status=400)
        folder, _ = DriveWatchFolder.objects.update_or_create(
            tenant=request.tenant, folder_id=folder_id,
            defaults={"watch": watch, "folder_name": name, "depth": depth,
                      "name_pattern": pattern, "is_active": True})
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.folder_added",
            target_type="drive_watch_folder", target_id=folder.pk,
            payload={"folder_id": folder_id, "folder_name": name, "depth": depth,
                     "name_pattern": pattern})
        return Response(ingest.health(request.tenant), status=201)

    @action(detail=False, methods=["patch", "delete"],
            url_path=r"folders/(?P<folder_pk>[^/.]+)")
    def change_folder(self, request, folder_pk=None):
        """Change an extra folder's pattern or depth, or stop watching it.
        Stopping keeps every file and proposal it brought in."""
        self.require_founder(request)
        if not _is_uuid(folder_pk):
            raise Http404
        folder = DriveWatchFolder.objects.filter(pk=folder_pk, is_active=True).first()
        if folder is None:
            raise Http404
        if request.method == "DELETE":
            folder.is_active = False
            folder.save(update_fields=["is_active", "updated_at"])
            verb, payload = "drive.folder_removed", {"folder_id": folder.folder_id}
        else:
            depth = request.data.get("depth", folder.depth)
            pattern = (request.data.get("name_pattern", folder.name_pattern) or "").strip()
            if depth not in DriveWatchFolder.Depth.values:
                return Response({"detail": "Depth is one level or any depth."}, status=400)
            if depth == DriveWatchFolder.Depth.ANY and not pattern:
                return Response({"detail": "A folder read at any depth needs a name "
                                           "to look for."}, status=400)
            payload = {"from": {"depth": folder.depth, "name_pattern": folder.name_pattern},
                       "to": {"depth": depth, "name_pattern": pattern}}
            folder.depth, folder.name_pattern = depth, pattern
            folder.save(update_fields=["depth", "name_pattern", "updated_at"])
            verb = "drive.folder_changed"
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb=verb,
            target_type="drive_watch_folder", target_id=folder.pk, payload=payload)
        return Response(ingest.health(request.tenant))

    # -------------------------------------------------------------- exclusions

    @action(detail=False, methods=["post"], url_path="exclusions")
    def add_exclusion(self, request):
        """A title that is never read, in any watched folder."""
        self.require_founder(request)
        watch = ingest.watch_for(request.tenant)
        if watch is None:
            return Response({"detail": "No folder is connected."}, status=409)
        pattern = (request.data.get("pattern") or "").strip()
        if not pattern:
            return Response({"detail": "Give a word or phrase to exclude."}, status=400)
        add_exclusion(watch, pattern, actor=request.user,
                      source=DriveExclusion.Source.MANUAL)
        return Response(ingest.health(request.tenant), status=201)

    @action(detail=False, methods=["delete"],
            url_path=r"exclusions/(?P<exclusion_pk>[^/.]+)")
    def remove_exclusion(self, request, exclusion_pk=None):
        """Read that title again from now on. What it kept out stays skipped."""
        self.require_founder(request)
        if not _is_uuid(exclusion_pk):
            raise Http404
        row = DriveExclusion.objects.filter(pk=exclusion_pk, deleted_at__isnull=True).first()
        if row is None:
            raise Http404
        row.deleted_at = timezone.now()
        row.save(update_fields=["deleted_at", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.exclusion_removed",
            target_type="drive_exclusion", target_id=row.pk,
            payload={"pattern": row.pattern})
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
        from config import environment

        if environment.is_demo():
            return Response({"detail": environment.DEMO_REFUSAL}, status=409)
        if not gmail_oauth.is_configured(request.tenant):
            return Response({"detail": (
                "Google sign-in isn't configured on this server, so there is "
                "nothing to connect to. Contact support."
            )}, status=400)
        state = gmail_oauth.new_state()
        request.session[gmail_oauth.STATE_SESSION_KEY] = state
        request.session[gmail_oauth.RETURN_SESSION_KEY] = "meetings"
        request.session[gmail_oauth.DRIVE_SESSION_KEY] = True
        request.session[gmail_oauth.INBOUND_SESSION_KEY] = False
        email = request.user.email
        return Response({
            "authorization_url": gmail_oauth.authorization_url(
                state, login_hint=email, hd=gmail_oauth.workspace_domain(email),
                drive=True, tenant=request.tenant),
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

        # Counted at the depth the watch will read it, so the number is honest
        # for a folder of per-meeting folders (owner, 2026-09-30).
        try:
            counts = ingest.counted_at_watch_depth(request.tenant, folder_id, info)
        except drive_service.DriveUnavailable as exc:
            return Response({"detail": str(exc)}, status=400)
        found = {"folder_id": info.folder_id, "name": info.name, "files": counts["files"],
                 "readable": counts["readable"], "in_subfolders": counts["in_subfolders"],
                 "depth": counts["depth"], "name_pattern": counts["name_pattern"],
                 "truncated": info.truncated}
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

    @action(detail=False, methods=["get", "post"], url_path="backfill")
    def backfill(self, request):
        """What is already in the folder, and the choice about it (FR-5.1b).

        **GET states the position; POST records the decision.** The counts and
        the cost are shown before anything starts, because a cost nobody has
        seen is a cost nobody has agreed to.
        """
        self.require_founder(request)
        if request.method == "GET":
            folder = self._folder(request)
            try:
                found = backfill_service.survey(request.tenant, folder=folder)
            except backfill_service.BackfillRefused as exc:
                return Response({"detail": str(exc)}, status=exc.status)
            except (ingest.NotConnected, drive_service.DriveUnavailable) as exc:
                return Response({"detail": str(exc)}, status=409)
            return Response({
                "folder": found,
                "backfill": meeting_serializers.represent_backfill(
                    backfill_service.current(request.tenant, folder)),
            })

        since = _as_date(request.data.get("since"))
        if request.data.get("scope") == DriveBackfill.Scope.SINCE and since is None:
            return Response({"detail": "Since when? Give a date to import from."},
                            status=400)
        try:
            started = backfill_service.start(
                request.tenant, scope=request.data.get("scope") or "",
                since=since, actor=request.user, folder=self._folder(request),
                confirmed=bool(request.data.get("confirm_over_balance")))
        except backfill_service.BackfillRefused as exc:
            return Response({"detail": str(exc), **exc.extra}, status=exc.status)
        except (ingest.NotConnected, drive_service.DriveUnavailable) as exc:
            return Response({"detail": str(exc)}, status=409)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.backfill_chosen",
            target_type="drive_backfill", target_id=started.pk,
            payload={"scope": started.scope,
                     "folder": started.folder.folder_name if started.folder else None,
                     "since": started.since.isoformat() if started.since else None,
                     "planned": started.planned,
                     "estimate_usd": str(started.estimated_cost_usd)})
        return Response(meeting_serializers.represent_backfill(started), status=201)

    @action(detail=False, methods=["post"], url_path="backfill/plan")
    def backfill_plan(self, request):
        """The count and the cost for one cut-off date, asked again each time
        the date changes."""
        self.require_founder(request)
        since = _as_date(request.data.get("since"))
        if since is None:
            return Response({"detail": "Give a date to import from."}, status=400)
        try:
            return Response(backfill_service.plan(request.tenant, since,
                                                  folder=self._folder(request)))
        except backfill_service.BackfillRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        except (ingest.NotConnected, drive_service.DriveUnavailable) as exc:
            return Response({"detail": str(exc)}, status=409)

    @action(detail=False, methods=["post"], url_path="backfill/stop")
    def backfill_stop(self, request):
        """Stop the import. What has been read stays read."""
        self.require_founder(request)
        running = DriveBackfill.objects.filter(
            state=DriveBackfill.State.RUNNING).first()
        if running is None:
            return Response({"detail": "No import is running."}, status=400)
        backfill_service.cancel(running, actor=request.user)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="drive.backfill_stopped",
            target_type="drive_backfill", target_id=running.pk,
            payload={"done": running.done, "cost_usd": str(running.cost_usd)})
        return Response(meeting_serializers.represent_backfill(running))

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


    @action(detail=False, methods=["get"], url_path="failed")
    def failed(self, request):
        """Files whose read failed, **named** (matrix 11.8's scope): what went
        wrong, how many automatic tries it has had, and whether the poll will
        try it again by itself."""
        rows = meeting_perms.source_files_for(request, MeetingSourceFile.objects.filter(
            state=MeetingSourceFile.State.FAILED)).order_by("created_at")
        return Response([{
            **meeting_serializers.represent_source_file(row),
            "automatic_failures": row.auto_parse_failures,
            "retries_automatically": parsing.retries_automatically(row),
        } for row in rows])

    @action(detail=False, methods=["post"], url_path="read-again")
    def read_again(self, request):
        """Queue a failed file for the next poll, its automatic tries restored
        (matrix 11.8). A file this person cannot see is a 404."""
        try:
            file_id = uuid.UUID(str(request.data.get("file") or ""))
        except ValueError:
            raise Http404
        row = meeting_perms.source_files_for(request).filter(pk=file_id).first()
        if row is None:
            raise Http404
        try:
            parsing.read_again(row, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({**meeting_serializers.represent_source_file(row),
                         "automatic_failures": 0, "retries_automatically": True})


class MeetingViewSet(MeetingViewSetBase):
    """Call notes on a contact and on a company (FR-5.8d).

    **The meeting is the point, not only the tasks it produced.** Opening a
    contact six months later should show the calls they were in, not merely
    whatever survived them.

    No client-facing surface, like the rest of this module (matrix 11.1): what
    reaches a client is the task, once a person has approved it.
    """

    def list(self, request):
        contact_id = request.query_params.get("contact")
        company_id = request.query_params.get("company")
        if not (_is_uuid(contact_id or "") or _is_uuid(company_id or "")):
            return Response(
                {"detail": "Ask for one contact's calls, or one company's."},
                status=400)

        meetings = Meeting.objects.select_related("source_file", "client_company")
        if contact_id:
            meetings = meetings.filter(participants__contact_id=contact_id)
        else:
            # A company's calls are its contacts' calls. Aggregated rather than
            # stored on the company, so a contact moving takes their history.
            from apps.crm.models import Contact

            meetings = meetings.filter(
                Q(client_company_id=company_id)
                | Q(participants__contact__in=Contact.objects.filter(
                    company_id=company_id, deleted_at__isnull=True)))
        meetings = meetings.distinct().order_by("-meeting_date", "-created_at")[:100]
        return Response([meeting_serializers.represent_meeting(
            meeting, for_contact=contact_id) for meeting in meetings])


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
        elif state == "archived":
            # Dismissed, newest first — where a dismissal is undone.
            return Response([meeting_serializers.represent_proposal(p) for p in
                             qs.filter(state=MeetingProposal.State.DISMISSED)
                             .select_related("dismissed_by")
                             .order_by("-dismissed_at")[:200]])
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
    def dismiss(self, request, pk=None):
        """Close the proposal with a reason; create nothing (owner, 2026-09-28).

        With `vendor` — `{"item": <participant item>, "contact_id"? ,
        "new_contact"?, "service_categories": [...]}` — it is "Record as vendor
        and dismiss the rest": that participant becomes a vendor contact and
        the proposal is dismissed as a vendor pitch. Open to everyone who
        clears the queue, like rejecting an item is.
        """
        proposal = self.load(pk)
        reason = request.data.get("reason") or ""
        note = request.data.get("note") or ""
        vendor = request.data.get("vendor")
        try:
            if vendor:
                if reason and reason != MeetingProposal.DismissReason.VENDOR_PITCH:
                    return Response({"detail": "Recording a vendor dismisses the rest "
                                               "as a vendor pitch."}, status=400)
                dismissal.dismiss_as_vendor(
                    proposal, actor=request.user, role=request.membership.role,
                    item_id=str(vendor.get("item") or ""),
                    choice={k: v for k, v in vendor.items() if k != "item"},
                    note=note, request=request)
            else:
                dismissal.dismiss(proposal, actor=request.user, reason=reason, note=note)
        except approval.ApprovalRefused as exc:
            return Response({"detail": str(exc), **exc.extra}, status=exc.status)
        proposal.refresh_from_db()
        return Response(meeting_serializers.represent_proposal(proposal, full=True))

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Undo a dismissal, from the Archived filter."""
        proposal = self.load(pk)
        try:
            dismissal.restore(proposal, actor=request.user)
        except approval.ApprovalRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response(meeting_serializers.represent_proposal(proposal, full=True))

    @action(detail=True, methods=["post"])
    def ignore(self, request, pk=None):
        """"Ignore this file" — never read titles like it again, and take this
        proposal out of the queue (owner, 2026-09-28).

        The FF's, like the rest of the exclusion list: it changes what the app
        reads from Drive, not just this one proposal. The pattern is what the
        person confirmed, usually the meeting's name; this file's own call to
        Claude has already happened and stays on AI usage.
        """
        if not meeting_perms.may_connect(request):
            self.permission_denied(request, message=(
                "Ignoring a file changes what is read from Drive; that is the founder's."))
        proposal = self.load(pk)
        pattern = (request.data.get("pattern") or "").strip()
        if not pattern:
            return Response({"detail": "Give the word or phrase to ignore."}, status=400)
        watch = ingest.watch_for(request.tenant)
        if watch is None:
            return Response({"detail": "No folder is connected."}, status=409)
        add_exclusion(watch, pattern, actor=request.user,
                      source=DriveExclusion.Source.IGNORED,
                      extra={"proposal": str(proposal.pk),
                             "file": proposal.source_file.name})
        if proposal.state in (MeetingProposal.State.PENDING,
                              MeetingProposal.State.PARTIALLY_ACTIONED):
            ProposalItem.objects.filter(proposal=proposal,
                                        state=ProposalItem.State.PENDING).update(
                state=ProposalItem.State.REJECTED, actioned_at=timezone.now())
            proposal.state = (MeetingProposal.State.REJECTED
                              if proposal.state == MeetingProposal.State.PENDING
                              else proposal.state)
            proposal.save(update_fields=["state", "updated_at"])
        return Response(meeting_serializers.represent_proposal(proposal, full=True))

    @action(detail=True, methods=["post"])
    def reparse(self, request, pk=None):
        """A fresh proposal that supersedes this one (FR-5.17). Approved items
        are untouched; it writes an `ai_call` like any other read."""
        proposal = self.load(pk)
        if proposal.state == MeetingProposal.State.DISMISSED:
            return Response({"detail": "That proposal is dismissed. Restore it first."},
                            status=409)
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
        if item.proposal.state == MeetingProposal.State.DISMISSED:
            return Response({"detail": "That proposal is dismissed. Restore it first."},
                            status=409)
        if item.state != ProposalItem.State.PENDING:
            return Response({"detail": "That one has already been decided."}, status=409)
        role = request.membership.role
        try:
            if item.kind == ProposalItem.Kind.PARTICIPANT:
                approval.approve_participant(item, actor=request.user, role=role,
                                             choice=request.data or {},
                                             request=request)
                # FR-5.8a — the meeting appears on every approved participant's
                # timeline, and is created once.
                approval.create_meeting(item.proposal, actor=request.user)
            elif item.kind == ProposalItem.Kind.ACTION_ITEM:
                # By owner (2026-09-28): the practice's is a task; someone
                # else's is a commitment with the confirmed outcome.
                approval.approve_action_item(item, actor=request.user, role=role,
                                             choice=request.data or {}, request=request)
            else:
                approval.approve_task_item(item, actor=request.user, role=role,
                                           choice=request.data or {})
        except approval.ApprovalRefused as exc:
            return Response({"detail": str(exc), **exc.extra}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="meeting.item_approved",
            target_type="proposal_item", target_id=item.pk,
            payload={"kind": item.kind, "created": item.created_record_type})
        item.refresh_from_db()
        return Response(meeting_serializers.represent_item(item), status=201)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        item = self.load_item(pk)
        if item.proposal.state == MeetingProposal.State.DISMISSED:
            return Response({"detail": "That proposal is dismissed. Restore it first."},
                            status=409)
        approval.reject(item, actor=request.user)
        return Response(meeting_serializers.represent_item(item))
