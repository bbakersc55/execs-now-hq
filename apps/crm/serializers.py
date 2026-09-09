from __future__ import annotations

from rest_framework import serializers

from apps.crm.models import (
    Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactType, ImportBatch, ImportRow, OutboxMessage, PipelineStage,
    ServiceCategory, StageAutomation, StageChange, Task,
)


class ContactEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactEmail
        fields = ["id", "address", "is_primary"]


class ContactPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPhone
        fields = ["id", "number", "is_primary"]


class ContactSerializer(serializers.ModelSerializer):
    emails = ContactEmailSerializer(many=True, read_only=True)
    phones = ContactPhoneSerializer(many=True, read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    type_codes = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "title", "company", "owner",
            "stage", "stage_code", "source", "background", "tags",
            "emails", "phones", "type_codes",
            "referral_fee_terms", "referral_cadence", "referral_touch_mode",
            "referral_next_touch_at", "referral_onboarded_at",
            "merged_into", "created_at", "updated_at",
        ]
        read_only_fields = ["stage", "merged_into", "referral_onboarded_at"]

    def get_type_codes(self, obj):
        return sorted(link.contact_type.code for link in obj.type_links.all())


class CompanySerializer(serializers.ModelSerializer):
    seats_in_use = serializers.IntegerField(read_only=True)
    seats_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = [
            "id", "name", "industry", "address", "primary_contact",
            "is_client_company", "seat_count", "digest_ai_prose",
            "seats_in_use", "seats_available", "created_at",
        ]
        # FR-1.6a — derived from pipeline stage, never set directly.
        read_only_fields = ["is_client_company"]


class CompanyDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyDomain
        fields = ["id", "company", "domain"]


class CompanyLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyLocation
        fields = ["id", "company", "name", "position"]


class PipelineStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineStage
        fields = ["id", "code", "label", "position", "is_terminal"]


class ContactTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactType
        fields = ["id", "code", "label", "position"]


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name"]


class StageChangeSerializer(serializers.ModelSerializer):
    from_code = serializers.CharField(source="from_stage.code", read_only=True)
    to_code = serializers.CharField(source="to_stage.code", read_only=True)

    class Meta:
        model = StageChange
        fields = ["id", "contact", "from_code", "to_code", "reason", "actor", "created_at"]


class StageAutomationSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()

    class Meta:
        model = StageAutomation
        fields = [
            "id", "from_stage", "to_stage", "action_type", "task_title_template",
            "task_due_offset_days", "email_template", "send_by_offset_days",
            "is_active", "summary",
        ]

    def get_summary(self, obj):
        """FR-1.13 — a plain-English summary of each rule."""
        trigger = (
            f"When a contact becomes {obj.to_stage.label.lower()}"
            if obj.from_stage is None
            else f"When a contact moves from {obj.from_stage.label.lower()} "
                 f"to {obj.to_stage.label.lower()}"
        )
        if obj.action_type == StageAutomation.Action.CREATE_TASK:
            due = (
                f" due in {obj.task_due_offset_days} days"
                if obj.task_due_offset_days is not None else ""
            )
            return f"{trigger}, create task '{obj.task_title_template}'{due}."
        return (
            f"{trigger}, draft an email into the Outbox for approval "
            f"(expires after {obj.send_by_offset_days} days)."
        )


class OutboxMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboxMessage
        fields = [
            "id", "state", "producer", "to_contact", "to_address", "from_address",
            "subject", "body_text", "is_ai_generated", "warning", "send_by",
            "approved_by", "approved_at", "sent_at", "sent_via", "dev_real_send",
            "created_at",
        ]
        read_only_fields = ["state", "approved_by", "approved_at", "sent_at", "dev_real_send"]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "due_date", "owner",
                  "contact", "source_automation", "created_at"]


class ImportRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportRow
        fields = ["id", "row_number", "raw", "outcome", "error_text", "contact"]


class ImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportBatch
        fields = ["id", "filename", "status", "counts", "created_by",
                  "rolled_back_at", "created_at"]
