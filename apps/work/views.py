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
from apps.work import services
from apps.work.models import Comment, Goal, Project, TaskChecklistItem, TaskUpdate

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
        qs = self.get_queryset()
        matched = False
        for field in ("task", "project", "goal"):
            value = request.query_params.get(field)
            if value:
                if not _is_uuid(value):
                    return Response({"detail": f"{field} must be an id."}, status=400)
                qs = qs.filter(**{f"{field}_id": value})
                matched = True
        if not matched:
            return Response({"detail": "Ask for one task, project or goal."}, status=400)
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
