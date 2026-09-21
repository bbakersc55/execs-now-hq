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
from apps.work.models import (
    Cadence, Comment, Goal, GoalResolution, Priority, Project, TaskChecklistItem,
    TaskUpdate,
)


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
        # FR-3.42 — "by <acting_user> on behalf of <actor>" when written while
        # someone acted as another user. Null otherwise.
        "acting_user": _person(update.acting_user) if update.acting_user_id else None,
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
        "acting_user": _person(comment.acting_user) if comment.acting_user_id else None,
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
    if kind == "goal":
        # Module 4B — the measurable travels with the goal everywhere, so the
        # Work screen and the report cannot disagree about it.
        data.update({
            "measurable_kind": entity.measurable_kind or None,
            "kind_is_undecided": entity.kind_is_undecided,
            "measurable": entity.measurable,
            "measurable_unit": entity.measurable_unit,
            "how_we_will_know": entity.how_we_will_know,
            "direction": entity.direction,
            "baseline_value": (str(entity.baseline_value)
                               if entity.baseline_value is not None else None),
            "baseline_at": entity.baseline_at.isoformat() if entity.baseline_at else None,
            "target_value": (str(entity.target_value)
                             if entity.target_value is not None else None),
            "horizon_days": entity.horizon_days,
            "outcome_statement": entity.outcome_statement,
        })
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
            # Said in words: this reaches a client as the whole explanation.
            raise serializers.ValidationError(
                f"That {model._meta.verbose_name} is not available to you.")
        return found

    def validate_client_company(self, value):
        request = self.context["request"]
        if work_perms.is_client(request):
            # A client has no CRM scope (matrix 4.18), so the company lookup
            # below finds nothing for them — even their own company, which the
            # goal page sends when adding a task. Their own company is the only
            # answer, and the view sets it regardless.
            if value is None or str(value) == str(request.membership.client_company_id):
                return request.membership.client_company
            raise serializers.ValidationError("You can only add work for your own company.")
        return self._scoped(Company, value, crm_perms.company_queryset_for,
                            deleted_at__isnull=True)

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

    # --- Module 4B: the measurable prompt, asked at creation (FR-4B.13) ------
    measurable_kind = serializers.ChoiceField(
        choices=Goal.MeasurableKind.choices, required=False, allow_blank=True)
    measurable = serializers.CharField(max_length=255, required=False, allow_blank=True)
    measurable_unit = serializers.CharField(max_length=40, required=False,
                                            allow_blank=True)
    how_we_will_know = serializers.CharField(required=False, allow_blank=True)
    direction = serializers.ChoiceField(choices=Goal.Direction.choices, required=False,
                                        allow_blank=True)
    baseline_value = serializers.DecimalField(max_digits=14, decimal_places=4,
                                              required=False, allow_null=True)
    baseline_at = serializers.DateField(required=False, allow_null=True)
    target_value = serializers.DecimalField(max_digits=14, decimal_places=4,
                                            required=False, allow_null=True)
    horizon_days = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    outcome_statement = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if self.instance is None and not (attrs.get("title") or "").strip():
            raise serializers.ValidationError({"title": "A goal needs a title."})
        # Ruling H — the outcome statement is the sentence that goes out under
        # the fractional's name. A VA may record a reading and may not write it.
        request = self.context["request"]
        if "outcome_statement" in attrs:
            company = attrs.get("client_company") or getattr(
                self.instance, "client_company_id", None)
            if not work_perms.may_judge(request, company):
                raise serializers.ValidationError({
                    "outcome_statement":
                        "The outcome statement is the fractional's sentence about "
                        "what this goal is for. Recording a reading is yours; this "
                        "is not."})
        # Ruling 2 — direction is required on a numeric measurable and never
        # inferred, because inference is silently wrong when baseline and target
        # are equal and has nothing to work from before a target is set.
        kind = attrs.get("measurable_kind",
                         getattr(self.instance, "measurable_kind", ""))
        direction = attrs.get("direction", getattr(self.instance, "direction", ""))
        if kind == Goal.MeasurableKind.NUMERIC and not direction:
            raise serializers.ValidationError({
                "direction": "A number needs a direction: say whether up is good or "
                             "down is good. It is never inferred from the baseline "
                             "and the target — a goal can be to hold a number steady."})
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

    ONE_PARENT = ("File a task under a project or directly on a goal, not both — "
                  "a project already belongs to its goal.")

    def validate(self, attrs):
        if self.instance is None and not (attrs.get("title") or "").strip():
            raise serializers.ValidationError({"title": "A task needs a title."})
        # Checked against what the task WILL hold, not just what was sent, so a
        # PATCH naming one parent cannot join it to the one already stored. The
        # database carries the same rule (task_one_parent_not_both); this is the
        # half that answers with a sentence instead of an IntegrityError.
        goal = attrs["goal"] if "goal" in attrs else getattr(self.instance, "goal", None)
        project = (attrs["project"] if "project" in attrs
                   else getattr(self.instance, "project", None))
        if goal is not None and project is not None:
            raise serializers.ValidationError({"project": self.ONE_PARENT})
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


def represent_stakeholder(row, *, effective=False) -> dict:
    level = "task" if row.task_id else "project" if row.project_id else "goal"
    return {
        "id": str(row.pk),
        "contact": _contact(row.contact),
        "cadence": row.cadence,
        "is_muted": row.is_muted,
        "level": level,
        "attached_to": str(getattr(row, f"{level}_id")),
        # True when this row won most-specific-wins for the task being asked about.
        "effective": effective,
        "last_notified_at": row.last_notified_at.isoformat() if row.last_notified_at else None,
    }


def represent_digest(digest, *, full=False) -> dict:
    data = {
        "id": str(digest.pk),
        "contact": _contact(digest.contact),
        "to_address": digest.contact.primary_email,
        "cadence": digest.cadence,
        "state": digest.state,
        "is_ai_generated": digest.is_ai_generated,
        "is_stale": digest.is_stale,
        "stale_reason": digest.stale_reason,
        "period_start": digest.period_start.isoformat(),
        "period_end": digest.period_end.isoformat(),
        "send_window_at": digest.send_window_at.isoformat(),
        "generated_at": digest.generated_at.isoformat(),
        "approved_by": _person(digest.approved_by),
        "approved_at": digest.approved_at.isoformat() if digest.approved_at else None,
        "item_count": digest.items.count(),
        # The whole rendered content, because FR-3.29 says the approval screen
        # shows what will actually go out — not a summary of it.
        "body_text": digest.body_text,
    }
    if full:
        data["body_html"] = digest.body_html
        data["outbox_message"] = (str(digest.outbox_message_id)
                                  if digest.outbox_message_id else None)
    return data


def represent_access(membership) -> dict:
    return {
        "id": str(membership.pk),
        "role": membership.role,
        "email": membership.user.email,
        "name": membership.user.full_name or membership.user.email,
        "contact": str(membership.contact_id) if membership.contact_id else None,
        "invited_at": membership.invited_at.isoformat() if membership.invited_at else None,
    }


class StakeholderSerializer(ScopedFieldsMixin, serializers.Serializer):
    contact = serializers.UUIDField(required=False)
    task = serializers.UUIDField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    goal = serializers.UUIDField(required=False, allow_null=True)
    cadence = serializers.ChoiceField(choices=Cadence.choices, required=False)
    is_muted = serializers.BooleanField(required=False)

    def validate_contact(self, value):
        return self._scoped(Contact, value, crm_perms.contact_queryset_for,
                            deleted_at__isnull=True)

    def validate_task(self, value):
        from apps.work import permissions as perms

        return self._scoped(Task, value, perms.task_queryset_for, deleted_at__isnull=True)

    def validate_project(self, value):
        from apps.work import permissions as perms

        return self._scoped(Project, value, perms.project_queryset_for,
                            deleted_at__isnull=True)

    def validate_goal(self, value):
        from apps.work import permissions as perms

        return self._scoped(Goal, value, perms.goal_queryset_for, deleted_at__isnull=True)

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get("contact"):
                raise serializers.ValidationError({"contact": "Who is being told?"})
            levels = [attrs.get(k) for k in ("task", "project", "goal")]
            if sum(1 for level in levels if level) != 1:
                raise serializers.ValidationError(
                    "Attach a stakeholder to exactly one task, project or goal."
                )
            contact = attrs["contact"]
            if not contact.primary_email:
                raise serializers.ValidationError(
                    {"contact": f"{contact.first_name} has no email address, so there is "
                                f"nowhere to send their updates."}
                )
        return attrs


# ================================================== Module 4B — the value report

def represent_measurement(row) -> dict:
    return {
        "id": str(row.pk),
        "goal": str(row.goal_id),
        "value": str(row.value),
        "measured_at": row.measured_at.isoformat(),
        "note": row.note,
        "recorded_by": _person(row.recorded_by),
        "created_at": row.created_at.isoformat(),
    }


def represent_milestone(row) -> dict:
    from django.utils import timezone

    from apps.work import milestones as milestone_service

    occurred = milestone_service.occurred_on(row)
    return {
        "id": str(row.pk),
        "goal": str(row.goal_id),
        "title": row.title,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        # Derived for a task, stored otherwise — and un-completing the task
        # clears it, because a milestone must never claim a date that did not
        # happen (FR-4B.25).
        "occurred_at": occurred.isoformat() if occurred else None,
        "state": milestone_service.state_of(row, today=timezone.localdate()),
        "position": row.position,
        "is_derived": row.is_derived,
        "source_task": str(row.source_task_id) if row.source_task_id else None,
        "visible_to_client": milestone_service.is_visible_to_client(row),
    }


def represent_resolution(row) -> dict:
    return {
        "id": str(row.pk),
        "goal": str(row.goal_id),
        "resolution": row.resolution,
        "resolution_label": row.get_resolution_display(),
        # Ruling G — the client reads this.
        "reason": row.reason,
        "resolved_by": _person(row.resolved_by),
        "resolved_at": row.resolved_at.isoformat(),
    }


def represent_export(row) -> dict:
    return {
        "id": str(row.pk),
        "goal": str(row.goal_id) if row.goal_id else None,
        "goal_title": row.goal.title if row.goal_id else "",
        "client_company": str(row.client_company_id),
        "scope": "goal" if row.goal_id else "all-goals",
        "byte_size": row.stored_file.byte_size,
        "narrative_version": (str(row.narrative_version_id)
                              if row.narrative_version_id else None),
        "exported_at": row.exported_at.isoformat(),
        "exported_by": _person(row.exported_by),
    }


class GoalMeasurementSerializer(serializers.Serializer):
    """A reading. `measured_at` is the date of the reading, not of the typing
    (FR-4B.16) — a reading entered on Friday for Monday is Monday's."""

    value = serializers.DecimalField(max_digits=14, decimal_places=4)
    measured_at = serializers.DateField(required=False)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        from django.utils import timezone

        # Only on the way in. Defaulting it on a partial update would silently
        # re-date a reading to today because somebody corrected its value —
        # which moves a point on the chart and can change what is current.
        if self.instance is None:
            attrs.setdefault("measured_at", timezone.localdate())
        return attrs


class GoalMilestoneSerializer(ScopedFieldsMixin, serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    occurred_at = serializers.DateField(required=False, allow_null=True)
    position = serializers.IntegerField(required=False, min_value=0)
    source_task = serializers.UUIDField(required=False, allow_null=True)

    def validate_source_task(self, value):
        """Scoped like every other FK a caller can set: a task they cannot see
        is not a task they can pin to a timeline."""
        return self._scoped(Task, value, scoper=work_perms.task_queryset_for,
                            deleted_at__isnull=True)

    def validate(self, attrs):
        if self.instance is None and not attrs.get("source_task") and not (
                attrs.get("title") or "").strip():
            raise serializers.ValidationError(
                {"title": "A milestone needs a title, or a task to take one from."})
        return attrs


class GoalResolutionSerializer(serializers.Serializer):
    """Ruling 7 — append-only, and the reason is required at the database as
    well as here. It is the whole mechanism that makes "changed course" read as
    judgement rather than as giving up (FR-4B.29)."""

    REASON_REQUIRED = (
        "Say why in one line. The client reads it, and it is what makes a change of "
        "course read as a judgement rather than as giving up.")

    resolution = serializers.ChoiceField(choices=GoalResolution.Resolution.choices)
    # The message is on the field, not in `validate_reason`: DRF trims
    # whitespace first, so "   " is refused as blank before any validator of
    # ours would run — and "This field may not be blank" says nothing useful
    # about why the line matters.
    reason = serializers.CharField(error_messages={
        "blank": REASON_REQUIRED, "required": REASON_REQUIRED,
        "null": REASON_REQUIRED})

    def validate_reason(self, value):
        return value.strip()
