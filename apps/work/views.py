"""Module 3 API — goals, projects, tasks, comments, checklists, updates.

Status codes follow the matrix §1 rule: out of scope is 404 (a 403 would
confirm the row exists), in scope but role-forbidden is 403.

`/api/tasks/` moved here from `apps.crm`, which had a read-only stand-in for
Phase 1. The table still lives in `crm` because stage automations write it.
"""

from __future__ import annotations

import uuid

from django.http import Http404
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Task
from apps.tenancy.models import CLIENT_ROLES, AuditEvent
from apps.work import permissions as work_perms
from apps.work import serializers as work_serializers
from apps.work import digests as digest_service
from apps.work import portal
from apps.work import services
from apps.work import stakeholders as stakeholder_service
from apps.work.models import (
    Cadence, Comment, Digest, Goal, Project, Stakeholder, TaskChecklistItem, TaskUpdate,
)

LIST_LIMIT = 500


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


class WorkViewSet(viewsets.GenericViewSet):
    """Shared plumbing: tenant staff and client users both reach these routes,
    each scoped by `permissions`."""

    # Authenticated, and then narrowed per role by `permissions`. Never an
    # empty list: that would drop DRF's authentication requirement entirely.
    permission_classes = [permissions.IsAuthenticated]
    model = None
    scoper = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "membership", None) is None:
            self.permission_denied(request, message="No membership for this tenant.")

    def base_queryset(self):
        return self.model.objects.filter(deleted_at__isnull=True)

    def get_queryset(self):
        return type(self).scoper(self.request, self.base_queryset())

    def load(self, pk):
        if not _is_uuid(pk):
            raise Http404
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise Http404
        self.object = found
        return found

    def _apply(self, entity, data, fields):
        touched = []
        for field in fields:
            if field in data:
                setattr(entity, field, data[field])
                touched.append(field)
        if touched:
            entity.save(update_fields=sorted(set(touched)) + ["updated_at"])
        return touched


# ------------------------------------------------------------- goals, projects

PARENT_FIELDS = ["title", "description", "client_company", "client_owner_contact",
                 "target_date", "status_override"]


class GoalViewSet(WorkViewSet):
    """Matrix 7.2 — only the practice authors goals. A goal is the strategy the
    engagement is judged against (FR-3.35a)."""

    model = Goal
    scoper = staticmethod(work_perms.goal_queryset_for)
    kind = "goal"
    write_serializer = work_serializers.GoalSerializer
    fields = PARENT_FIELDS

    def _represent(self, entity):
        return work_serializers.represent_parent(entity, request=self.request,
                                                 kind=self.kind)

    def _staff_only(self, request):
        if crm_perms.role_of(request) in CLIENT_ROLES:
            return Response({"detail": "Goals are set by the practice."}, status=403)
        return None

    def list(self, request):
        qs = self.get_queryset().select_related("client_company", "owner",
                                                "client_owner_contact")
        company = request.query_params.get("client_company")
        if company:
            if not _is_uuid(company):
                return Response({"detail": "client_company must be an id."}, status=400)
            qs = qs.filter(client_company_id=company)
        return Response([self._represent(e) for e in qs.order_by("-created_at")[:LIST_LIMIT]])

    def retrieve(self, request, pk=None):
        return Response(self._represent(self.load(pk)))

    def create(self, request):
        if (refused := self._staff_only(request)) is not None:
            return refused
        serializer = self.write_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        entity = self.model.objects.create(
            tenant=request.tenant, owner=request.user,
            **{k: v for k, v in serializer.validated_data.items()},
        )
        return Response(self._represent(entity), status=201)

    def partial_update(self, request, pk=None):
        entity = self.load(pk)
        if (refused := self._staff_only(request)) is not None:
            return refused
        serializer = self.write_serializer(instance=entity, data=request.data, partial=True,
                                           context={"request": request})
        serializer.is_valid(raise_exception=True)
        self._apply(entity, serializer.validated_data, self.fields)
        return Response(self._represent(entity))

    def destroy(self, request, pk=None):
        """FR-3.6 — children are detached and reported, never deleted."""
        entity = self.load(pk)
        if (refused := self._staff_only(request)) is not None:
            return refused
        detached = services.soft_delete(entity, actor=request.user,
                                        verb=f"{self.kind}.deleted")
        return Response({"detached": detached})

    @action(detail=True, methods=["get"])
    def children(self, request, pk=None):
        entity = self.load(pk)
        projects = [] if self.kind == "project" else [
            work_serializers.represent_parent(p, request=request, kind="project")
            for p in work_perms.project_queryset_for(
                request, Project.objects.filter(goal=entity, deleted_at__isnull=True)
            ).select_related("client_company", "owner", "client_owner_contact")
        ]
        tasks = work_perms.task_queryset_for(
            request, Task.objects.filter(deleted_at__isnull=True, **{self.kind: entity})
        ).select_related("project", "goal", "client_company", "owner", "assignee",
                         "client_owner_contact")
        return Response({
            "projects": projects,
            "tasks": [work_serializers.represent_task(t, request=request) for t in tasks],
        })


class ProjectViewSet(GoalViewSet):
    """Matrix 7.2a — a client may create one for their own company, with no
    parent goal (FR-3.35a)."""

    model = Project
    scoper = staticmethod(work_perms.project_queryset_for)
    kind = "project"
    write_serializer = work_serializers.ProjectSerializer
    fields = PARENT_FIELDS + ["goal", "start_date"]

    def _staff_only(self, request):
        return None      # clients may create and edit their own projects

    def create(self, request):
        serializer = self.write_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if work_perms.is_client(request):
            data["client_company"] = request.membership.client_company
            data["goal"] = None
        project = Project.objects.create(
            tenant=request.tenant, owner=request.user,
            created_by_client=work_perms.is_client(request), **data,
        )
        return Response(self._represent(project), status=201)

    def partial_update(self, request, pk=None):
        project = self.load(pk)
        if work_perms.is_client(request) and not project.created_by_client:
            return Response({"detail": "This project belongs to the practice."}, status=403)
        return super().partial_update(request, pk)

    def destroy(self, request, pk=None):
        project = self.load(pk)
        if work_perms.is_client(request) and not project.created_by_client:
            return Response({"detail": "This project belongs to the practice."}, status=403)
        detached = services.soft_delete(project, actor=request.user, verb="project.deleted")
        return Response({"detached": detached})


# --------------------------------------------------------------------- tasks

class TaskViewSet(WorkViewSet):
    model = Task
    scoper = staticmethod(work_perms.task_queryset_for)

    def base_queryset(self):
        return Task.objects.filter(deleted_at__isnull=True).select_related(
            "project", "goal", "client_company", "owner", "assignee",
            "client_owner_contact",
        )

    def _represent(self, task):
        return work_serializers.represent_task(task, request=self.request)

    def list(self, request):
        qs = self.get_queryset()
        for field in ("project", "goal", "client_company", "assignee"):
            value = request.query_params.get(field)
            if value:
                if not _is_uuid(value):
                    return Response({"detail": f"{field} must be an id."}, status=400)
                qs = qs.filter(**{f"{field}_id": value})
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status__in=status_filter.split(","))
        if request.query_params.get("unfiled") == "1":
            qs = qs.filter(project__isnull=True, goal__isnull=True)
        return Response([self._represent(t) for t in
                         qs.order_by("-created_at")[:LIST_LIMIT]])

    def retrieve(self, request, pk=None):
        return Response(self._represent(self.load(pk)))

    def create(self, request):
        """Matrix 7.3 — a client creates for their own company, and FR-3.36
        says no review queue stands in their way."""
        serializer = work_serializers.TaskSerializer(data=request.data,
                                                     context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        line = data.pop("client_facing_line", "")
        role = crm_perms.role_of(request)
        if work_perms.is_client(request):
            data["client_company"] = request.membership.client_company
            data["is_client_visible"] = True
        task = services.create_task(tenant=request.tenant, actor=request.user, role=role,
                                    client_facing_line=line, **data)
        self.object = task
        return Response(self._represent(task), status=201)

    def partial_update(self, request, pk=None):
        task = self.load(pk)
        if not work_perms.may_write(request, task):
            return Response(
                {"detail": "This task is the practice's to change. Add a comment and "
                           "they will see it."},
                status=403,
            )
        serializer = work_serializers.TaskSerializer(instance=task, data=request.data,
                                                     partial=True,
                                                     context={"request": request})
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        line = changes.pop("client_facing_line", "")
        role = crm_perms.role_of(request)
        if "is_client_visible" in changes and changes["is_client_visible"] != task.is_client_visible:
            services.audit_visibility_change(task, actor=request.user,
                                             to_visible=changes["is_client_visible"])
        services.apply_task_changes(task, actor=request.user, role=role,
                                    changes=changes, client_facing_line=line)
        task.refresh_from_db()
        return Response(self._represent(task))

    def destroy(self, request, pk=None):
        task = self.load(pk)
        role = crm_perms.role_of(request)
        allowed = (role not in CLIENT_ROLES) or work_perms.client_may_delete(request, task)
        if not allowed:
            return Response({"detail": "You can delete only tasks you created."}, status=403)
        task.deleted_at = timezone.now()
        task.save(update_fields=["deleted_at", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=task.tenant, actor=request.user, verb="task.deleted",
            target_type="task", target_id=task.pk, payload={},
        )
        return Response(status=204)

    @action(detail=True, methods=["get"])
    def updates(self, request, pk=None):
        """FR-3.15 — the event log a digest is built from, in the open."""
        task = self.load(pk)
        rows = TaskUpdate.objects.filter(task=task).select_related("actor")
        if work_perms.is_client(request):
            # A client sees the shared record: internal comments are not theirs.
            rows = rows.exclude(kind=TaskUpdate.Kind.COMMENT_ADDED,
                                to_value=Comment.Visibility.INTERNAL)
        return Response([work_serializers.represent_update(u)
                         for u in rows.order_by("-created_at")[:LIST_LIMIT]])

    @action(detail=True, methods=["post"])
    def narrative(self, request, pk=None):
        """FR-3.18 — a client-facing line without a status change."""
        task = self.load(pk)
        if crm_perms.role_of(request) in CLIENT_ROLES:
            return Response({"detail": "The practice writes the client-facing line."},
                            status=403)
        line = (request.data.get("client_facing_line") or "").strip()
        if not line:
            return Response({"detail": "Write the line first."}, status=400)
        update = services.add_narrative(task, actor=request.user,
                                        role=crm_perms.role_of(request), line=line)
        return Response(work_serializers.represent_update(update), status=201)

    @action(detail=True, methods=["get", "post"])
    def checklist(self, request, pk=None):
        """FR-3.4 — the flat substitute for subtasks."""
        task = self.load(pk)
        if request.method == "POST":
            if not work_perms.may_write(request, task):
                return Response({"detail": "This task is the practice's to change."},
                                status=403)
            serializer = work_serializers.ChecklistItemSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            text = (serializer.validated_data.get("text") or "").strip()
            if not text:
                return Response({"detail": "The step needs text."}, status=400)
            last = task.checklist.order_by("-position").first()
            item = TaskChecklistItem.objects.create(
                tenant=task.tenant, task=task, text=text,
                position=(last.position + 1) if last else 0,
            )
            return Response(work_serializers.represent_checklist_item(item), status=201)
        return Response([work_serializers.represent_checklist_item(i)
                         for i in task.checklist.all()])


class ChecklistItemViewSet(WorkViewSet):
    model = TaskChecklistItem

    def base_queryset(self):
        return TaskChecklistItem.objects.select_related("task")

    def get_queryset(self):
        tasks = work_perms.task_queryset_for(
            self.request, Task.objects.filter(deleted_at__isnull=True)
        ).values("pk")
        return self.base_queryset().filter(task_id__in=tasks)

    def partial_update(self, request, pk=None):
        item = self.load(pk)
        if not work_perms.may_write(request, item.task):
            return Response({"detail": "This task is the practice's to change."}, status=403)
        serializer = work_serializers.ChecklistItemSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "text" in data:
            item.text = data["text"]
            item.save(update_fields=["text", "updated_at"])
        if "is_done" in data:
            services.set_checklist_done(item, actor=request.user,
                                        role=crm_perms.role_of(request),
                                        is_done=data["is_done"])
        item.refresh_from_db()
        return Response(work_serializers.represent_checklist_item(item))

    def destroy(self, request, pk=None):
        item = self.load(pk)
        if not work_perms.may_write(request, item.task):
            return Response({"detail": "This task is the practice's to change."}, status=403)
        item.delete()
        return Response(status=204)


# ------------------------------------------------------------------ comments

class CommentViewSet(WorkViewSet):
    """FR-3.12 — internal or shared, defaulting to internal for tenant users.

    A client's response never contains an internal comment (AC-3.4): the
    queryset excludes them rather than the UI hiding them.
    """

    model = Comment

    def base_queryset(self):
        return Comment.objects.filter(deleted_at__isnull=True).select_related(
            "author", "task", "project", "goal"
        )

    def get_queryset(self):
        qs = work_perms.comment_queryset_for(self.request, self.base_queryset())
        tasks = work_perms.task_queryset_for(
            self.request, Task.objects.filter(deleted_at__isnull=True)).values("pk")
        goals = work_perms.goal_queryset_for(
            self.request, Goal.objects.filter(deleted_at__isnull=True)).values("pk")
        projects = work_perms.project_queryset_for(
            self.request, Project.objects.filter(deleted_at__isnull=True)).values("pk")
        from django.db.models import Q

        return qs.filter(Q(task_id__in=tasks) | Q(goal_id__in=goals)
                         | Q(project_id__in=projects))

    def list(self, request):
        """Asking about something out of scope is a 404, not an empty list:
        otherwise "no comments" and "not yours" look the same (matrix §1)."""
        asked = {field: request.query_params.get(field)
                 for field in ("task", "project", "goal")
                 if request.query_params.get(field)}
        if len(asked) != 1:
            return Response({"detail": "Ask for one task, project or goal."}, status=400)
        field, value = next(iter(asked.items()))
        if not _is_uuid(value):
            return Response({"detail": f"{field} must be an id."}, status=400)
        self._target(request, {field: value})     # 404 when it is not theirs
        qs = self.get_queryset().filter(**{f"{field}_id": value})
        return Response([work_serializers.represent_comment(c)
                         for c in qs.order_by("created_at")[:LIST_LIMIT]])

    def create(self, request):
        serializer = work_serializers.CommentSerializer(data=request.data,
                                                         context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entity = self._target(request, data)
        comment = services.add_comment(
            entity, author=request.user, role=crm_perms.role_of(request),
            body=data["body"], visibility=data.get("visibility"),
        )
        return Response(work_serializers.represent_comment(comment), status=201)

    def _target(self, request, data):
        if data.get("task"):
            return self._scoped(request, Task, data["task"], work_perms.task_queryset_for)
        if data.get("project"):
            return self._scoped(request, Project, data["project"],
                                work_perms.project_queryset_for)
        return self._scoped(request, Goal, data["goal"], work_perms.goal_queryset_for)

    def _scoped(self, request, model, pk, scoper):
        found = scoper(request, model.objects.filter(pk=pk, deleted_at__isnull=True)).first()
        if found is None:
            raise Http404
        return found


# ------------------------------------------------------------- stakeholders

class StakeholderViewSet(WorkViewSet):
    """FR-3.20/3.21 — who hears about this work, and how often.

    Matrix 7.12: who gets emailed is the fractional's call, so client users
    read the list but do not change it — except their own cadence (7.13),
    which they can also change from any digest footer without signing in.
    """

    model = Stakeholder

    def base_queryset(self):
        return Stakeholder.objects.select_related("contact", "task", "project", "goal")

    def get_queryset(self):
        tasks = work_perms.task_queryset_for(
            self.request, Task.objects.filter(deleted_at__isnull=True)).values("pk")
        goals = work_perms.goal_queryset_for(
            self.request, Goal.objects.filter(deleted_at__isnull=True)).values("pk")
        projects = work_perms.project_queryset_for(
            self.request, Project.objects.filter(deleted_at__isnull=True)).values("pk")
        from django.db.models import Q

        return self.base_queryset().filter(
            Q(task_id__in=tasks) | Q(goal_id__in=goals) | Q(project_id__in=projects))

    def _staff_only(self, request):
        if crm_perms.role_of(request) in CLIENT_ROLES:
            return Response({"detail": "The practice decides who is emailed."}, status=403)
        return None

    def list(self, request):
        qs = self.get_queryset()
        for field in ("task", "project", "goal"):
            value = request.query_params.get(field)
            if value:
                if not _is_uuid(value):
                    return Response({"detail": f"{field} must be an id."}, status=400)
                qs = qs.filter(**{f"{field}_id": value})
        effective = request.query_params.get("effective")
        if effective:
            if not _is_uuid(effective):
                return Response({"detail": "effective must be a task id."}, status=400)
            task = work_perms.task_queryset_for(
                request, Task.objects.filter(pk=effective, deleted_at__isnull=True)).first()
            if task is None:
                raise Http404
            rows = stakeholder_service.effective_for_task(task).values()
            return Response([work_serializers.represent_stakeholder(r, effective=True)
                             for r in rows])
        return Response([work_serializers.represent_stakeholder(r)
                         for r in qs.order_by("created_at")[:LIST_LIMIT]])

    def create(self, request):
        if (refused := self._staff_only(request)) is not None:
            return refused
        serializer = work_serializers.StakeholderSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row, created = Stakeholder.objects.get_or_create(
            tenant=request.tenant, contact=data["contact"],
            task=data.get("task"), project=data.get("project"), goal=data.get("goal"),
            defaults={"cadence": data.get("cadence", Cadence.WEEKLY)},
        )
        if not created and "cadence" in data:
            row.cadence = data["cadence"]
            row.save(update_fields=["cadence", "updated_at"])
        return Response(work_serializers.represent_stakeholder(row),
                        status=201 if created else 200)

    def partial_update(self, request, pk=None):
        row = self.load(pk)
        if crm_perms.role_of(request) in CLIENT_ROLES:
            # Matrix 7.13 — a client may change their OWN cadence only.
            own = request.membership.contact_id == row.contact_id
            if not own:
                return Response({"detail": "You can change only your own updates."},
                                status=403)
        serializer = work_serializers.StakeholderSerializer(
            instance=row, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        for field in ("cadence", "is_muted"):
            if field in serializer.validated_data:
                setattr(row, field, serializer.validated_data[field])
        row.save(update_fields=["cadence", "is_muted", "updated_at"])
        return Response(work_serializers.represent_stakeholder(row))

    def destroy(self, request, pk=None):
        row = self.load(pk)
        if (refused := self._staff_only(request)) is not None:
            return refused
        services.revoke_stakeholder_tokens(row)   # FR-3.33b
        row.delete()
        return Response(status=204)


# ------------------------------------------------------------------ digests

class DigestViewSet(WorkViewSet):
    """FR-3.29 — the approval screen. Matrix §8, the highest-consequence rows
    in the access matrix: a VA may read and prepare, and may never approve."""

    model = Digest

    def base_queryset(self):
        return Digest.objects.select_related("contact", "approved_by", "outbox_message")

    def get_queryset(self):
        qs = self.base_queryset()
        role = crm_perms.role_of(self.request)
        if role in CLIENT_ROLES:
            return qs.none()          # a digest is the practice's to review
        if role == crm_perms.Role.CF:
            companies = crm_perms.assigned_company_ids(self.request)
            return qs.filter(contact__company_id__in=companies)
        return qs

    def _act(self, request, pk, fn, **kwargs):
        digest = self.load(pk)
        try:
            fn(digest, actor=request.user, role=crm_perms.role_of(request), **kwargs)
        except digest_service.DigestActionRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        digest.refresh_from_db()
        return Response(work_serializers.represent_digest(digest))

    def list(self, request):
        qs = self.get_queryset()
        state = request.query_params.get("state", Digest.State.PENDING)
        if state and state != "all":
            qs = qs.filter(state__in=state.split(","))
        return Response([work_serializers.represent_digest(d)
                         for d in qs.order_by("send_window_at")[:LIST_LIMIT]])

    def retrieve(self, request, pk=None):
        return Response(work_serializers.represent_digest(self.load(pk), full=True))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._act(request, pk, digest_service.approve)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        return self._act(request, pk, digest_service.skip)

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        body = request.data.get("body_text")
        if not (body or "").strip():
            return Response({"detail": "The digest cannot be emptied."}, status=400)
        return self._act(request, pk, digest_service.edit_body, body_text=body)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        """FR-3.30a — one click, because a stale draft should be cheap to fix."""
        digest = self.load(pk)
        if crm_perms.role_of(request) in CLIENT_ROLES:
            raise Http404
        try:
            digest_service.regenerate(digest, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        digest.refresh_from_db()
        return Response(work_serializers.represent_digest(digest, full=True))

    @action(detail=False, methods=["post"], url_path="generate-now")
    def generate_now(self, request):
        """**Development only.** Run generation for one stakeholder over a chosen
        period, instead of waiting for Thursday.

        It is the same code path the scheduler uses — same claims, same hold
        rules, same composition — so what a manual check sees here is what the
        Thursday run would have produced. It creates a draft and sends nothing.
        """
        from datetime import timedelta

        from django.conf import settings as dj_settings

        from apps.crm.models import Contact
        from apps.work.models import Cadence

        if not dj_settings.IS_LOCAL:
            raise Http404          # not a route that exists off the laptop
        if crm_perms.role_of(request) in CLIENT_ROLES:
            return Response({"detail": "Not available."}, status=403)

        contact_id = request.data.get("contact")
        if not _is_uuid(contact_id or ""):
            return Response({"detail": "Choose whose digest to generate."}, status=400)
        contact = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk=contact_id, deleted_at__isnull=True)
        ).select_related("company").first()
        if contact is None:
            raise Http404

        cadence = request.data.get("cadence") or Cadence.WEEKLY
        if cadence not in Cadence.values:
            return Response({"detail": "Unknown cadence."}, status=400)
        try:
            days = max(1, min(int(request.data.get("days", 7)), 365))
            send_in = request.data.get("send_in_minutes")
            send_in = int(send_in) if send_in not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "days and send_in_minutes are numbers."}, status=400)

        now = timezone.now()
        since = now - timedelta(days=days)
        owed = digest_service.owed_to(contact.pk, tenant=request.tenant, cadence=cadence,
                                      since=since, until=now)
        if not owed:
            # FR-3.31 is a real outcome, not an error: say so plainly.
            return Response({
                "detail": f"Nothing is owed to {contact.first_name} at that cadence in the "
                          f"last {days} days, so no digest was generated — which is exactly "
                          f"what would happen on Thursday.",
                "digest": None,
            })
        window = (now + timedelta(minutes=send_in)) if send_in is not None else             digest_service.next_window(request.tenant, cadence, after=now)
        digest = digest_service.generate(
            tenant=request.tenant, contact=contact, cadence=cadence,
            period_start=since, period_end=now, send_window_at=window, owed=owed,
        )
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="digest.generated_on_demand",
            target_type="digest", target_id=digest.pk,
            payload={"contact": str(contact.pk), "cadence": cadence, "days": days,
                     "development_only": True},
        )
        return Response({
            "detail": f"Generated a {digest.state} digest for {contact.first_name} "
                      f"from {len(owed)} update{'s' if len(owed) != 1 else ''}.",
            "digest": work_serializers.represent_digest(digest, full=True),
        }, status=201)

    @action(detail=False, methods=["post"], url_path="approve-selected")
    def approve_selected(self, request):
        """FR-3.29 — approve-all for a batch that has been read. Each one still
        goes through the same approval, and one failure does not hide the rest."""
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one digest."}, status=400)
        approved, refused = [], []
        for pk in ids:
            digest = self.get_queryset().filter(pk=pk).first() if _is_uuid(pk) else None
            if digest is None:
                refused.append({"id": str(pk), "detail": "Not found."})
                continue
            try:
                digest_service.approve(digest, actor=request.user,
                                       role=crm_perms.role_of(request))
                approved.append(str(digest.pk))
            except digest_service.DigestActionRefused as exc:
                refused.append({"id": str(digest.pk), "detail": str(exc)})
        status_code = 200 if approved else 403 if refused else 400
        return Response({"approved": approved, "refused": refused}, status=status_code)


# ------------------------------------------------- reports and client activity

class ProgressReportView(viewsets.GenericViewSet):
    """FR-3.38 — the same content as a digest, pulled rather than sent.

    No email, no approval, and it consumes nothing: reading a report never eats
    the Friday digest.
    """

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from datetime import timedelta

        if getattr(request, "membership", None) is None:
            return Response({"detail": "No membership for this tenant."}, status=403)
        try:
            days = max(1, min(int(request.query_params.get("days", 7)), 365))
        except (TypeError, ValueError):
            return Response({"detail": "days must be a number."}, status=400)
        since = timezone.now() - timedelta(days=days)

        if crm_perms.role_of(request) in CLIENT_ROLES:
            # A client's report is always their own company's. If they name a
            # contact, it must be one of theirs — ignoring the parameter would
            # answer a question about someone else with their own data.
            asked = request.query_params.get("contact")
            if asked:
                from apps.crm.models import Contact

                if not _is_uuid(asked) or not Contact.objects.filter(
                    pk=asked, company_id=request.membership.client_company_id,
                    deleted_at__isnull=True,
                ).exists():
                    raise Http404
            report = digest_service.report_for_company(
                request.tenant, company=request.membership.client_company, since=since)
        else:
            contact_id = request.query_params.get("contact")
            if not _is_uuid(contact_id or ""):
                return Response({"detail": "Ask for one contact."}, status=400)
            from apps.crm.models import Contact

            contact = crm_perms.contact_queryset_for(
                request, Contact.objects.filter(pk=contact_id)).first()
            if contact is None:
                raise Http404
            report = digest_service.report_for(request.tenant, contact=contact, since=since)
        return Response({
            "since": report["since"].isoformat(), "until": report["until"].isoformat(),
            "body_text": report["body_text"],
            "updates": [work_serializers.represent_update(u) for u in report["updates"]],
        })


class ClientActivityView(viewsets.GenericViewSet):
    """FR-3.40's in-app half: a feed of what clients did, built from the
    `task_update` rows already recorded (owner decision, 2026-09-11)."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from datetime import timedelta

        if crm_perms.role_of(request) in CLIENT_ROLES or getattr(
                request, "membership", None) is None:
            return Response({"detail": "Not available."}, status=403)
        tasks = work_perms.task_queryset_for(
            request, Task.objects.filter(deleted_at__isnull=True)).values("pk")
        rows = TaskUpdate.objects.filter(
            is_client_actor=True, task_id__in=tasks,
            created_at__gte=timezone.now() - timedelta(days=14),
        ).select_related("actor", "task").order_by("-created_at")[:100]
        return Response([
            {**work_serializers.represent_update(u),
             "task": str(u.task_id), "task_title": u.task.title if u.task else ""}
            for u in rows
        ])


# ------------------------------------------------------------ portal access

class PortalAccessViewSet(WorkViewSet):
    """Matrix §9 — FF, or a CF on an assigned company. A VA never grants."""

    model = None

    def get_queryset(self):
        from apps.tenancy.models import Membership

        return Membership.objects.none()

    def _company(self, request, company_id):
        from apps.crm.models import Company

        if not _is_uuid(company_id or ""):
            raise Http404
        company = crm_perms.company_queryset_for(
            request, Company.objects.filter(pk=company_id, deleted_at__isnull=True)).first()
        if company is None:
            raise Http404
        return company

    def _may_manage(self, request):
        return crm_perms.role_of(request) in (crm_perms.Role.FF, crm_perms.Role.CF)

    def list(self, request):
        # Matrix 9.5 — seat usage is the practice's: FF, or a CF on a company
        # they are assigned. A VA sees none of it, and neither does a client.
        if not self._may_manage(request):
            return Response({"detail": "Seats and portal access are not available to you."},
                            status=403)
        company = self._company(request, request.query_params.get("company"))
        return Response({
            "company": str(company.pk),
            "seat_count": company.seat_count,
            "seats_in_use": company.seats_in_use,
            "seats_available": company.seats_available,
            "may_manage": self._may_manage(request),
            "people": [work_serializers.represent_access(m)
                       for m in portal.access_rows(company)],
        })

    def create(self, request):
        if not self._may_manage(request):
            return Response({"detail": "A VA does not grant portal access."}, status=403)
        from apps.crm.models import Contact

        contact = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk=request.data.get("contact"),
                                            deleted_at__isnull=True)
        ).first() if _is_uuid(request.data.get("contact") or "") else None
        if contact is None:
            raise Http404
        try:
            membership = portal.grant(tenant=request.tenant, contact=contact,
                                      role=request.data.get("role") or None,
                                      actor=request.user)
        except portal.SeatsExhausted as exc:
            return Response({"detail": str(exc)}, status=409)
        except portal.PortalAccessRefused as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(work_serializers.represent_access(membership), status=201)

    def destroy(self, request, pk=None):
        from apps.tenancy.models import Membership

        if not self._may_manage(request):
            return Response({"detail": "A VA does not revoke portal access."}, status=403)
        membership = Membership.objects.filter(
            pk=pk, role__in=CLIENT_ROLES, revoked_at__isnull=True
        ).first() if _is_uuid(pk) else None
        if membership is None:
            raise Http404
        if crm_perms.role_of(request) == crm_perms.Role.CF and \
                membership.client_company_id not in crm_perms.assigned_company_ids(request):
            raise Http404
        return Response(portal.revoke(membership, actor=request.user))


class AssignablePeopleView(viewsets.GenericViewSet):
    """Who a task may be assigned to, from this requester's point of view.

    AC-3.14 — for a client user this lists **only their own company**, so the
    picker cannot offer what FR-3.9a.2 would then refuse.
    """

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from apps.tenancy.models import Membership

        membership = getattr(request, "membership", None)
        if membership is None:
            return Response({"detail": "No membership for this tenant."}, status=403)
        rows = Membership.objects.filter(revoked_at__isnull=True).select_related("user")
        if crm_perms.role_of(request) in CLIENT_ROLES:
            rows = rows.filter(client_company_id=membership.client_company_id,
                               role__in=CLIENT_ROLES)
        return Response([
            {"id": str(row.user_id),
             "name": row.user.full_name or row.user.email,
             "role": row.role,
             "company": str(row.client_company_id) if row.client_company_id else None}
            for row in rows.order_by("role", "user__email")
        ])
