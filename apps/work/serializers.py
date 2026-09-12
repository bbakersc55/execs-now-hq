"""Task-engine representations and input validation.

Two things the shapes here are responsible for:

- **A derived status is never returned as if it were stored.** Goals and
  projects report `status` (what to show), `status_override` (what was set by
  hand, or null) and `status_is_derived`, so a reader can always tell which.
- **An internal comment is absent from a client's response** (AC-3.4), which is
  a queryset rule in `permissions.comment_queryset_for`, not a field flag.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.crm import permissions as crm_perms
from apps.crm.models import Company, Contact, Task
from apps.tenancy.models import CLIENT_ROLES
from apps.work import permissions as work_perms
from apps.work import status as status_service
from apps.work.models import Comment, Goal, Priority, Project, TaskChecklistItem, TaskUpdate


def _person(user):
    if user is None:
        return {"id": None, "name": ""}
    return {"id": str(user.pk), "name": user.full_name or user.email}


def _contact(contact):
    if contact is None:
        return {"id": None, "name": ""}
    return {"id": str(contact.pk),
            "name": f"{contact.first_name} {contact.last_name}".strip()}


def represent_update(update: TaskUpdate) -> dict:
    return {
        "id": str(update.pk),
        "kind": update.kind,
        "from_value": update.from_value,
        "to_value": update.to_value,
        # FR-3.17 — first-class, because every digest is only as good as this.
        "client_facing_line": update.client_facing_line,
        "actor": _person(update.actor),
        "source": update.source,
        "is_client_actor": update.is_client_actor,
        "created_at": update.created_at.isoformat(),
    }


def represent_comment(comment: Comment) -> dict:
    return {
        "id": str(comment.pk),
        "body": comment.body,
        "visibility": comment.visibility,
        "author": _person(comment.author),
        "created_at": comment.created_at.isoformat(),
        "task": str(comment.task_id) if comment.task_id else None,
        "project": str(comment.project_id) if comment.project_id else None,
        "goal": str(comment.goal_id) if comment.goal_id else None,
    }


def represent_checklist_item(item: TaskChecklistItem) -> dict:
    return {"id": str(item.pk), "text": item.text, "is_done": item.is_done,
            "position": item.position}


def represent_task(task: Task, *, request) -> dict:
    return {
        "id": str(task.pk),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "priority_label": Priority(task.priority).label if task.priority in
        Priority.values else str(task.priority),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "project": str(task.project_id) if task.project_id else None,
        "project_title": task.project.title if task.project_id else "",
        "goal": str(task.goal_id) if task.goal_id else None,
        "goal_title": task.goal.title if task.goal_id else "",
        "client_company": str(task.client_company_id) if task.client_company_id else None,
        "client_company_name": task.client_company.name if task.client_company_id else "",
        "owner": _person(task.owner),
        "assignee": _person(task.assignee),
        "client_owner_contact": _contact(task.client_owner_contact),
        "contact": str(task.contact_id) if task.contact_id else None,
        "is_client_visible": task.is_client_visible,
        "created_by_client": task.created_by_client,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        # What this requester may do, so the UI need not re-derive FR-3.9a.
        "may_edit": work_perms.may_write(request, task),
        "may_delete": (crm_perms.role_of(request) not in CLIENT_ROLES
                       or work_perms.client_may_delete(request, task)),
        "may_set_visibility": crm_perms.role_of(request) not in CLIENT_ROLES,
    }


def represent_parent(entity, *, request, kind: str) -> dict:
    data = {
        "id": str(entity.pk),
        "kind": kind,
        "title": entity.title,
        "description": entity.description,
        # FR-3.10 — all three, so "derived" is never mistaken for "stored".
        "status": status_service.status_of(entity),
        "status_override": entity.status_override,
        "status_is_derived": status_service.is_derived(entity),
        "client_company": str(entity.client_company_id) if entity.client_company_id else None,
        "client_company_name": entity.client_company.name if entity.client_company_id else "",
        "owner": _person(entity.owner),
        "client_owner_contact": _contact(entity.client_owner_contact),
        "target_date": entity.target_date.isoformat() if entity.target_date else None,
        "created_at": entity.created_at.isoformat(),
    }
    if kind == "project":
        data.update({
            "goal": str(entity.goal_id) if entity.goal_id else None,
            "goal_title": entity.goal.title if entity.goal_id else "",
            "start_date": entity.start_date.isoformat() if entity.start_date else None,
            "created_by_client": entity.created_by_client,
        })
    return data


class ScopedFieldsMixin:
    """Every FK a caller can set is checked against what that caller may see,
    so a CF cannot attach work to a company they are not assigned to and a
    client cannot reach outside their own."""

    def _scoped(self, model, pk, scoper=None, **filters):
        if pk is None:
            return None
        request = self.context["request"]
        qs = model.objects.filter(pk=pk, **filters)
        if scoper is not None:
            qs = scoper(request, qs)
        found = qs.first()
        if found is None:
            raise serializers.ValidationError("Not found.")
        return found

    def validate_client_company(self, value):
        request = self.context["request"]
        company = self._scoped(Company, value, crm_perms.company_queryset_for,
                               deleted_at__isnull=True)
        if work_perms.is_client(request) and company is not None and \
                company.pk != request.membership.client_company_id:
            raise serializers.ValidationError("Not found.")
        return company

    def validate_client_owner_contact(self, value):
        return self._scoped(Contact, value, crm_perms.contact_queryset_for,
                            deleted_at__isnull=True)

    def validate_status_override(self, value):
        if value in ("", None):
            return None
        if value not in Task.Status.values:
            raise serializers.ValidationError("Unknown status.")
        return value


class GoalSerializer(ScopedFieldsMixin, serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    client_company = serializers.UUIDField(required=False, allow_null=True)
    client_owner_contact = serializers.UUIDField(required=False, allow_null=True)
    target_date = serializers.DateField(required=False, allow_null=True)
    status_override = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs):
        if self.instance is None and not (attrs.get("title") or "").strip():
            raise serializers.ValidationError({"title": "A goal needs a title."})
        return attrs


class ProjectSerializer(GoalSerializer):
    goal = serializers.UUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)

    def validate_goal(self, value):
        request = self.context["request"]
        if value is not None and work_perms.is_client(request):
            # FR-3.35a — a client's project never hangs off a goal; strategy
            # is the fractional's.
            raise serializers.ValidationError(
                "A project you create is not filed under a goal."
            )
        return self._scoped(Goal, value, work_perms.goal_queryset_for,
                            deleted_at__isnull=True)

    def validate(self, attrs):
        if self.instance is None and not (attrs.get("title") or "").strip():
            raise serializers.ValidationError({"title": "A project needs a title."})
        return attrs


class TaskSerializer(ScopedFieldsMixin, serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Task.Status.choices, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    goal = serializers.UUIDField(required=False, allow_null=True)
    client_company = serializers.UUIDField(required=False, allow_null=True)
    assignee = serializers.UUIDField(required=False, allow_null=True)
    client_owner_contact = serializers.UUIDField(required=False, allow_null=True)
    is_client_visible = serializers.BooleanField(required=False)
    # FR-3.16 — prompted, never forced. Not a model field.
    client_facing_line = serializers.CharField(required=False, allow_blank=True)

    def validate_project(self, value):
        return self._scoped(Project, value, work_perms.project_queryset_for,
                            deleted_at__isnull=True)

    def validate_goal(self, value):
        return self._scoped(Goal, value, work_perms.goal_queryset_for,
                            deleted_at__isnull=True)

    def validate_assignee(self, value):
        from apps.accounts.models import User
        from apps.tenancy.models import Membership

        request = self.context["request"]
        if value is None:
            return None
        member = Membership.all_objects.filter(
            tenant=request.tenant, user_id=value, revoked_at__isnull=True
        ).first()
        if member is None:
            raise serializers.ValidationError("That person is not in this practice.")
        if work_perms.is_client(request) and not work_perms.client_may_assign_to(request, value):
            # FR-3.9a.2 — a colleague, never a fractional, never outside the company.
            raise serializers.ValidationError(
                "You can assign this only to someone at your own company."
            )
        return User.objects.get(pk=value)

    def validate_is_client_visible(self, value):
        # Matrix 7.7 — a client cannot hide work from their own company.
        if work_perms.is_client(self.context["request"]):
            raise serializers.ValidationError("Only the practice sets client visibility.")
        return value

    def validate(self, attrs):
        if self.instance is None and not (attrs.get("title") or "").strip():
            raise serializers.ValidationError({"title": "A task needs a title."})
        return attrs


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField()
    visibility = serializers.ChoiceField(choices=Comment.Visibility.choices,
                                         required=False)
    task = serializers.UUIDField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    goal = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        targets = [attrs.get(k) for k in ("task", "project", "goal")]
        if sum(1 for t in targets if t) != 1:
            raise serializers.ValidationError(
                "A comment belongs to exactly one task, project or goal."
            )
        if not attrs["body"].strip():
            raise serializers.ValidationError({"body": "Write something first."})
        return attrs


class ChecklistItemSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False)
    is_done = serializers.BooleanField(required=False)
    position = serializers.IntegerField(required=False, min_value=0, max_value=32767)
