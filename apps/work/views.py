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
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Task
from apps.crm.services import search as crm_search
from apps.tenancy.models import CLIENT_ROLES, AuditEvent, Role
from apps.work import permissions as work_perms
from apps.work import serializers as work_serializers
from apps.work import digests as digest_service
from apps.work import portal
from apps.work import services
from apps.work import stakeholders as stakeholder_service
from apps.work import milestones as milestone_service
from apps.work import narratives as narrative_service
from apps.work import value_pdf
from apps.work import value_report
from apps.work.models import (
    Cadence, Comment, Digest, Goal, GoalMeasurement, GoalMilestone, GoalNarrative,
    GoalNarrativeVersion, GoalReportExport, GoalResolution, Project, Stakeholder,
    TaskChecklistItem, TaskUpdate,
)

LIST_LIMIT = 500

# The other side of the company dimension the Work and Tasks screens carry: the
# practice's own work has no company id to be filtered by, so the screens send
# this word in place of one (FR-3.39/3.39a).
INTERNAL = "internal"


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


class DashboardView(viewsets.ViewSet):
    """The landing page (design brief, Tier 2).

    Staff only: a client user's landing page is their portal, and every figure
    here spans the practice. One call rather than five, so the scoping rules
    cannot drift between the screen and the screens it summarises.
    """

    permission_classes = [crm_perms.IsTenantStaff]

    def list(self, request):
        from apps.work import dashboard

        return Response(dashboard.for_request(request))


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
    # Module 4B's measurable prompt is asked at creation and editable after
    # (FR-4B.13). `outcome_statement` is in the list and gated in the
    # serializer — a VA may set a baseline and may not write the sentence.
    fields = PARENT_FIELDS + [
        "measurable_kind", "measurable", "measurable_unit", "how_we_will_know",
        "direction", "baseline_value", "baseline_at", "target_value", "horizon_days",
        "outcome_statement",
    ]

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
        internal = request.query_params.get("client_company") == INTERNAL
        if internal:
            qs = qs.filter(client_company__isnull=True)
        for field in ("project", "goal", "client_company", "assignee"):
            value = request.query_params.get(field)
            if value and not (field == "client_company" and internal):
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

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        """Who "Who hears about this" offers (Phase 3 manual checks, item 3).

        It used to search every contact in the tenant, so a client's task
        offered other clients' people. For work with a client company it now
        lists **that company's contacts**, no typing needed; `outside=1` is the
        explicit, typed search for the cases the spec allows — the fractional's
        own boss, a board member — and excludes the company. Internal work, with
        no company to anchor it, searches any contact. Tenant staff who are also
        contacts are marked, so the owner can tell his own row from a client's.
        """
        from apps.crm.models import Contact, ContactEmail
        from apps.tenancy.models import TENANT_ROLES, Membership

        if (refused := self._staff_only(request)) is not None:
            return refused
        entity = None
        for field, model, scoper in (("task", Task, work_perms.task_queryset_for),
                                     ("project", Project, work_perms.project_queryset_for),
                                     ("goal", Goal, work_perms.goal_queryset_for)):
            value = request.query_params.get(field)
            if value:
                entity = scoper(request, model.objects.filter(
                    pk=value, deleted_at__isnull=True)).select_related(
                        "client_company").first() if _is_uuid(value) else None
                if entity is None:
                    raise Http404
                break
        if entity is None:
            return Response({"detail": "Name the task, project or goal."}, status=400)

        company = entity.client_company
        outside = request.query_params.get("outside") == "1"
        term = (request.query_params.get("q") or "").strip()
        contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(deleted_at__isnull=True))
        if company is not None and not outside:
            contacts = contacts.filter(company=company)
            if term:
                contacts = contacts.filter(crm_search.as_typed(term)).distinct()
        else:
            if company is not None:
                contacts = contacts.exclude(company=company)
            # The whole tenant is never listed unasked: it takes a typed name.
            contacts = (contacts.filter(crm_search.as_typed(term)).distinct()
                        if len(term) >= 2 else contacts.none())
        contacts = list(contacts.select_related("company")
                        .order_by("first_name", "last_name")[:50])

        staff = list(Membership.objects.filter(role__in=TENANT_ROLES, revoked_at__isnull=True)
                     .select_related("user"))
        staff_contacts = {m.contact_id for m in staff if m.contact_id}
        staff_emails = {m.user.email.lower() for m in staff if m.user.email}
        for contact_id, address in ContactEmail.objects.filter(
                contact_id__in=[c.pk for c in contacts]).values_list("contact_id", "address"):
            if address.lower() in staff_emails:
                staff_contacts.add(contact_id)

        return Response({
            "company": str(company.pk) if company else None,
            "company_name": company.name if company else "",
            "outside": outside,
            "people": [
                {"contact": str(c.pk),
                 "name": f"{c.first_name} {c.last_name}".strip(),
                 "email": c.primary_email or "",
                 "company_name": c.company.name if c.company else "",
                 "is_practice": c.pk in staff_contacts}
                for c in contacts
            ],
        })

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

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """Development only — a pending digest exactly as it will send, with a
        placeholder where the recipient's own cadence link goes (a real one is a
        credential, issued only at send). `?part=text` shows the plain part."""
        from django.conf import settings
        from django.http import HttpResponse

        if not settings.IS_LOCAL:
            raise Http404
        digest = self.load(pk)
        if digest.state != Digest.State.PENDING:
            return Response({"detail": f"This digest is {digest.state}. Preview what was "
                                       "sent from its Outbox row."}, status=409)
        html, text = digest_service.email_for(digest,
                                              footer_url=digest_service.preview_footer_url())
        if request.query_params.get("part") == "text":
            return HttpResponse(text, content_type="text/plain; charset=utf-8")
        from apps.crm.services import email_layout

        html, _ = email_layout.with_logo(html, digest.tenant, as_data_uri=True)
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        """FR-3.29a — every-update content waiting on its quiet window. Read-only
        and computed; scoped like the digest list itself."""
        from apps.crm.models import Contact

        role = crm_perms.role_of(request)
        if role not in crm_perms.TENANT_ROLES:
            return Response({"detail": "A digest is the practice's to review."}, status=403)
        contact_ids = None
        if role == crm_perms.Role.CF:
            contact_ids = set(Contact.objects.filter(
                company_id__in=crm_perms.assigned_company_ids(request)
            ).values_list("pk", flat=True))
        return Response(digest_service.upcoming_every_update(request.tenant,
                                                             contact_ids=contact_ids))

    @action(detail=False, methods=["get"], url_path="tick-status")
    def tick_status(self, request):
        """Whether expiry, generation and sending are running at all."""
        from apps.work.tasks import tick_health

        if crm_perms.role_of(request) not in crm_perms.TENANT_ROLES:
            return Response({"detail": "Not available."}, status=403)
        return Response(tick_health(request.tenant))

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


class ActivityView(viewsets.GenericViewSet):
    """The practice's activity feed. **FF, CF and VA only — never a client.**

    This reverses the Phase 3 ruling (FR-3.41, matrix 7.16) that made the log the
    client's. The owner asked for it, used it, and reversed it: the value is to
    the practice, which runs several accounts and wants to see across them
    including its own team's work. The client's window into the engagement is
    the value report (Module 4B), not an audit feed of their own company.

    Read-only, structurally: `list` is the only route, there is no serializer
    with a write path, and `apps/work/activity.py` has no function that writes.

    Scope (activity.Scope): FF and VA see the tenant; a CF sees their assigned
    companies plus the contacts they own, resolved through the CRM's own
    `contact_queryset_for` so the two can never disagree.
    """

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from apps.work import activity

        membership = getattr(request, "membership", None)
        if membership is None:
            return Response({"detail": "No membership for this tenant."}, status=403)
        if membership.role in CLIENT_ROLES:
            # Matrix 7.16 as it now reads. A client is not told what the feed is.
            return Response({"detail": "Not available."}, status=403)

        params = request.query_params
        company = params.get("company") or None
        contact = params.get("contact") or None
        actor = params.get("actor") or None
        category = params.get("category") or None
        for value, label in ((company, "company"), (contact, "contact"), (actor, "actor")):
            if value and not _is_uuid(value):
                return Response({"detail": f"{label} must be an id."}, status=400)
        if category and category not in activity.CATEGORIES:
            return Response({"detail": "Unknown category."}, status=400)
        since, until = parse_datetime(params.get("since") or ""), \
            parse_datetime(params.get("until") or "")
        if params.get("since") and since is None:
            return Response({"detail": "since must be a timestamp."}, status=400)
        if params.get("until") and until is None:
            return Response({"detail": "until must be a timestamp."}, status=400)

        return Response(activity.build(
            request, company=company, contact=contact, actor=actor,
            category=category, since=since, until=until))


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

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        """Who can be given access, and for anyone who cannot, why not.

        The picker used to run the **global** contact search — every contact in
        the tenant, ranked by full text — which is the wrong question twice
        over: it offers people at companies that are not clients, and it finds
        nobody at all until a whole indexed word is typed. This lists the
        company's own contacts, so the common case (three people, no typing)
        needs no search, and `q` filters that list as plain text.

        Pass `company` for the list, or `contact` for one person: the contact
        page grants without a search at all.
        """
        from apps.crm.models import Contact

        if not self._may_manage(request):
            return Response({"detail": "Portal access is not available to you."}, status=403)

        one = request.query_params.get("contact")
        if one:
            contact = crm_perms.contact_queryset_for(
                request, Contact.objects.filter(pk=one, deleted_at__isnull=True)
            ).first() if _is_uuid(one) else None
            if contact is None:
                raise Http404
            company = contact.company
            if company is not None:
                # A CF may only manage the companies they are assigned.
                self._company(request, str(company.pk))
            contacts = [contact]
        else:
            company = self._company(request, request.query_params.get("company"))
            contacts = crm_perms.contact_queryset_for(
                request,
                Contact.objects.filter(company=company, deleted_at__isnull=True),
            )
            term = (request.query_params.get("q") or "").strip()
            if term:
                contacts = contacts.filter(crm_search.as_typed(term)).distinct()
            contacts = contacts.order_by("first_name", "last_name")[:100]

        seats = portal.seat_refusal(company) if company is not None else None
        return Response({
            "company": str(company.pk) if company is not None else None,
            "company_name": company.name if company is not None else None,
            "is_client_company": bool(company and company.is_client_company),
            "seat_count": company.seat_count if company is not None else None,
            "seats_in_use": company.seats_in_use if company is not None else 0,
            "seat_refusal": seats,
            "people": [
                {
                    "contact": str(c.pk),
                    "name": f"{c.first_name} {c.last_name}".strip(),
                    "email": c.primary_email or "",
                    "title": c.title,
                    "role": portal.default_role_for(c),
                    # The person-level reason first: an unallocated seat count is
                    # not a reason to hide someone who is otherwise eligible.
                    "refusal": portal.refusal_for(c, tenant=request.tenant) or seats,
                }
                for c in contacts
            ],
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

    def _live_access(self, request, pk):
        """A live portal login in scope: FF any, a CF only on assigned companies."""
        from apps.tenancy.models import Membership

        membership = Membership.objects.filter(
            pk=pk, role__in=CLIENT_ROLES, revoked_at__isnull=True
        ).select_related("user").first() if _is_uuid(pk) else None
        if membership is None:
            raise Http404
        if crm_perms.role_of(request) == crm_perms.Role.CF and \
                membership.client_company_id not in crm_perms.assigned_company_ids(request):
            raise Http404
        return membership

    def partial_update(self, request, pk=None):
        """Matrix 9.2a — change FCC vs ECC on an existing portal user. Same
        scope as revoke, and the same session handling when the role narrows."""
        if not self._may_manage(request):
            return Response({"detail": "A VA does not change portal roles."}, status=403)
        membership = self._live_access(request, pk)
        try:
            result = portal.change_role(membership, request.data.get("role"),
                                        actor=request.user)
        except portal.PortalAccessRefused as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({**work_serializers.represent_access(membership), **result})

    def destroy(self, request, pk=None):
        if not self._may_manage(request):
            return Response({"detail": "A VA does not revoke portal access."}, status=403)
        return Response(portal.revoke(self._live_access(request, pk), actor=request.user))


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


# ==================================================== Module 4B — value report
#
# Matrix §10A. Out of scope is 404 (a 403 would confirm the row exists); in
# scope but role-forbidden is 403 — including for a VA reaching a judgement
# verb, which is asserted against the response body, not the absence of a button.

class ValueReportBase(viewsets.GenericViewSet):
    """Shared scoping for everything under the report.

    A client's company is implied and never asked for: they have exactly one,
    and accepting the parameter would invite the question of what happens when
    they name someone else's.
    """

    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "membership", None) is None:
            self.permission_denied(request, message="No membership for this tenant.")

    def for_client(self) -> bool:
        return work_perms.is_client(self.request)

    def company_or_404(self, request):
        from apps.crm.models import Company

        if self.for_client():
            # Their own company, and their membership is the authorisation.
            # `company_queryset_for` is Module 1's staff scope and returns
            # nothing for a client role — right there, wrong here.
            company_id = request.membership.client_company_id
            if company_id is None:
                raise Http404
            company = Company.objects.filter(pk=company_id,
                                             deleted_at__isnull=True).first()
        else:
            company_id = request.query_params.get("client_company") \
                or request.data.get("client_company")
            if not _is_uuid(company_id or ""):
                raise Http404
            company = crm_perms.company_queryset_for(
                request, Company.objects.filter(pk=company_id, deleted_at__isnull=True)
            ).first()
        if company is None:
            raise Http404
        return company

    def goal_or_404(self, request, pk):
        """**Internal goals are not reachable here at all** (FR-4B.4): the
        report is a client artifact, and a goal with no client company has no
        place in one — for any role."""
        if not _is_uuid(pk or ""):
            raise Http404
        goal = work_perms.goal_queryset_for(
            request, Goal.objects.filter(pk=pk, deleted_at__isnull=True,
                                         client_company__isnull=False)
        ).select_related("client_company", "client_owner_contact", "source_map_row").first()
        if goal is None:
            raise Http404
        return goal

    def judgement_or_403(self, request, goal):
        """Ruling 6 and ruling H — resolving, accepting a narrative and writing
        the outcome statement are the fractional's."""
        if work_perms.may_judge(request, goal.client_company_id):
            return None
        return Response(
            {"detail": "That is the fractional's call, not an administrative one. "
                       "Recording a reading and exporting the report are yours; "
                       "this is not."},
            status=403)

    def staff_or_403(self, request, message):
        if work_perms.may_administer(request):
            return None
        return Response({"detail": message}, status=403)


class ValueReportViewSet(ValueReportBase):
    """FR-4B.1, FR-4B.2 — the whole report, and any single goal on its own."""

    def list(self, request):
        company = self.company_or_404(request)
        return Response(value_report.report_for(
            request, company=company, for_client=self.for_client()))

    def retrieve(self, request, pk=None):
        goal = self.goal_or_404(request, pk)
        task_queryset = work_perms.task_queryset_for(request, Task.objects.all())
        return Response(value_report.goal_block(
            goal, request=request, for_client=self.for_client(),
            task_queryset=task_queryset))

    # ------------------------------------------------------------- narrative

    @action(detail=True, methods=["post"], url_path="draft-narrative")
    def draft_narrative(self, request, pk=None):
        """Matrix 10A.12 — a VA may prepare, exactly as with a digest."""
        goal = self.goal_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "The narrative is the practice's to draft.")) is not None:
            return refused
        narrative = narrative_service.draft(goal, trigger="button")
        if narrative is None:
            return Response({"detail": "Claude could not be reached. The call is "
                                       "recorded on AI usage; the goal is unchanged."},
                            status=502)
        return Response(value_report.narrative_for(goal, for_client=False))

    @action(detail=True, methods=["post"], url_path="accept-narrative")
    def accept_narrative(self, request, pk=None):
        """R9a — accepting is publishing to the client, and appends a dated
        snapshot (ruling B)."""
        goal = self.goal_or_404(request, pk)
        if (refused := self.judgement_or_403(request, goal)) is not None:
            return refused
        body = request.data.get("body")
        if body is None:
            narrative = GoalNarrative.objects.filter(goal=goal).first()
            body = narrative.proposed_body if narrative else ""
        try:
            narrative_service.accept(goal, body=body, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="goal.narrative_accepted",
            target_type="goal", target_id=goal.pk, payload={})
        return Response(value_report.narrative_for(goal, for_client=False))

    @action(detail=True, methods=["post"], url_path="discard-narrative")
    def discard_narrative(self, request, pk=None):
        goal = self.goal_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "The narrative is the practice's.")) is not None:
            return refused
        narrative_service.discard(goal)
        return Response(value_report.narrative_for(goal, for_client=False))

    @action(detail=True, methods=["get"], url_path="narrative-versions")
    def narrative_versions(self, request, pk=None):
        """What the client was told, and when. Append-only: there is no write
        method here of any kind (matrix 10A.11a)."""
        goal = self.goal_or_404(request, pk)
        rows = GoalNarrativeVersion.objects.filter(goal=goal).select_related("accepted_by")
        return Response([
            {"id": str(v.pk), "body": v.body, "accepted_at": v.accepted_at.isoformat(),
             "accepted_by": v.accepted_by.full_name if v.accepted_by else ""}
            for v in rows
        ])

    # ------------------------------------------------------------------- PDF

    @action(detail=False, methods=["get"], url_path="pdf")
    def company_pdf(self, request):
        return self._pdf(request, company=self.company_or_404(request), goal=None)

    @action(detail=True, methods=["get"], url_path="pdf")
    def goal_pdf(self, request, pk=None):
        goal = self.goal_or_404(request, pk)
        return self._pdf(request, company=goal.client_company, goal=goal)

    def _pdf(self, request, *, company, goal):
        """A true preview: the same content the export is built from. Generating
        is not exporting and neither is sending."""
        from django.http import HttpResponse

        if request.query_params.get("as") == "html":
            return HttpResponse(value_pdf.render_html(request, company=company,
                                                      goal=goal))
        content = value_pdf.render_pdf(request, company=company, goal=goal)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="value-report.pdf"'
        return response


class GoalReportExportViewSet(ValueReportBase):
    """Ruling 4 — a snapshot at export, kept for good (ruling F)."""

    def list(self, request):
        if (refused := self.staff_or_403(
                request, "The portal is your copy, and it is always current.")) is not None:
            return refused
        company = self.company_or_404(request)
        rows = GoalReportExport.objects.filter(client_company=company).select_related(
            "goal", "exported_by", "stored_file")
        goal_id = request.query_params.get("goal")
        if goal_id:
            if not _is_uuid(goal_id):
                return Response({"detail": "goal must be an id."}, status=400)
            rows = rows.filter(goal_id=goal_id)
        return Response([work_serializers.represent_export(r) for r in rows])

    def create(self, request):
        """Matrix 10A.15 — a VA may export; a client does not."""
        if (refused := self.staff_or_403(
                request, "The portal is your copy, and it is always current.")) is not None:
            return refused
        goal = None
        if request.data.get("goal"):
            goal = self.goal_or_404(request, request.data.get("goal"))
            company = goal.client_company
        else:
            company = self.company_or_404(request)
        row = value_pdf.export(request, company=company, goal=goal, actor=request.user)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="value_report.exported",
            target_type="goal_report_export", target_id=row.pk,
            payload={"goal": str(goal.pk) if goal else None,
                     "company": str(company.pk)})
        return Response(work_serializers.represent_export(row), status=201)

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        from django.http import HttpResponse

        from apps.tenancy import storage

        if (refused := self.staff_or_403(request, "Not available.")) is not None:
            return refused
        if not _is_uuid(pk or ""):
            raise Http404
        row = GoalReportExport.objects.filter(pk=pk).select_related("stored_file").first()
        if row is None or not work_perms.may_administer(request):
            raise Http404
        if crm_perms.role_of(request) == Role.CF and row.client_company_id not in set(
                crm_perms.assigned_company_ids(request)):
            raise Http404
        response = HttpResponse(storage.read(row.stored_file),
                                content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="value-report.pdf"'
        return response


class GoalMeasurementViewSet(ValueReportBase):
    """FR-4B.14–17. Matrix 10A.4/10A.5 — a VA may; a client may not."""

    def list(self, request):
        goal = self.goal_or_404(request, request.query_params.get("goal"))
        if self.for_client():
            # A client reads the series through the report, where it is shaped.
            raise Http404
        return Response([work_serializers.represent_measurement(m)
                         for m in value_report.measurements_of(goal)])

    def create(self, request):
        goal = self.goal_or_404(request, request.data.get("goal"))
        if (refused := self.staff_or_403(
                request, "Readings are the practice's to record.")) is not None:
            return refused
        serializer = work_serializers.GoalMeasurementSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        row = GoalMeasurement.objects.create(
            tenant=request.tenant, goal=goal, recorded_by=request.user,
            **serializer.validated_data)
        return Response(work_serializers.represent_measurement(row), status=201)

    def partial_update(self, request, pk=None):
        row = self._row_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "Readings are the practice's.")) is not None:
            return refused
        serializer = work_serializers.GoalMeasurementSerializer(
            instance=row, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(row, field, value)
        row.save(update_fields=list(serializer.validated_data) + ["updated_at"])
        return Response(work_serializers.represent_measurement(row))

    def destroy(self, request, pk=None):
        row = self._row_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "Readings are the practice's.")) is not None:
            return refused
        row.delete()
        return Response(status=204)

    def _row_or_404(self, request, pk):
        if not _is_uuid(pk or ""):
            raise Http404
        row = GoalMeasurement.objects.filter(pk=pk).select_related("goal").first()
        if row is None:
            raise Http404
        self.goal_or_404(request, str(row.goal_id))     # scope through the goal
        return row


class GoalMilestoneViewSet(ValueReportBase):
    """FR-4B.23–25 and ruling E. A derived milestone's dates belong to its task
    and are not editable here (matrix 10A.9)."""

    def create(self, request):
        goal = self.goal_or_404(request, request.data.get("goal"))
        if (refused := self.staff_or_403(
                request, "The goal's timeline is the practice's to compose.")) is not None:
            return refused
        serializer = work_serializers.GoalMilestoneSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        task = data.pop("source_task", None)
        if task is not None:
            try:
                milestone_service.check_eligible(task, goal)
            except milestone_service.MilestoneRefused as exc:
                return Response({"detail": str(exc)}, status=exc.status)
            if GoalMilestone.objects.filter(source_task=task).exists():
                return Response({"detail": "That task is already a milestone."},
                                status=409)
            # The date is derived from the task's completion, every time it is
            # read (FR-4B.25). Storing it would need a sync path, and a sync
            # path is a thing that drifts.
            data["occurred_at"] = None
            data.setdefault("title", task.title)
            data["title"] = data.get("title") or task.title
        row = GoalMilestone.objects.create(tenant=request.tenant, goal=goal,
                                           source_task=task, **data)
        return Response(work_serializers.represent_milestone(row), status=201)

    def partial_update(self, request, pk=None):
        row = self._row_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "The goal's timeline is the practice's.")) is not None:
            return refused
        if row.source_task_id is not None:
            return Response(
                {"detail": "This milestone is a task. Its title and its dates belong "
                           "to the task, so that the same fact is not kept in two "
                           "places — edit the task."},
                status=409)
        serializer = work_serializers.GoalMilestoneSerializer(
            instance=row, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("source_task", None)
        for field, value in data.items():
            setattr(row, field, value)
        row.save(update_fields=list(data) + ["updated_at"])
        return Response(work_serializers.represent_milestone(row))

    def destroy(self, request, pk=None):
        row = self._row_or_404(request, pk)
        if (refused := self.staff_or_403(
                request, "The goal's timeline is the practice's.")) is not None:
            return refused
        row.delete()
        return Response(status=204)

    def _row_or_404(self, request, pk):
        if not _is_uuid(pk or ""):
            raise Http404
        row = GoalMilestone.objects.filter(pk=pk).select_related(
            "goal", "source_task", "source_task__project").first()
        if row is None:
            raise Http404
        self.goal_or_404(request, str(row.goal_id))
        return row


class GoalResolutionViewSet(ValueReportBase):
    """FR-4B.26–30, ruling 7. **Append-only: there is no update and no destroy
    here**, and reversing a resolution is appending another with its own reason."""

    def list(self, request):
        goal = self.goal_or_404(request, request.query_params.get("goal"))
        return Response([work_serializers.represent_resolution(r)
                         for r in value_report.resolutions_of(goal)])

    def create(self, request):
        goal = self.goal_or_404(request, request.data.get("goal"))
        if (refused := self.judgement_or_403(request, goal)) is not None:
            return refused
        serializer = work_serializers.GoalResolutionSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        row = GoalResolution.objects.create(
            tenant=request.tenant, goal=goal, resolved_by=request.user,
            **serializer.validated_data)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="goal.resolved",
            target_type="goal", target_id=goal.pk,
            payload={"resolution": row.resolution})
        return Response(work_serializers.represent_resolution(row), status=201)
