from __future__ import annotations

from django.conf import settings as dj_settings
from django.db import transaction
from rest_framework import serializers

from apps.crm.models import (
    Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactType, ContactTypeLink, DevSendAllowlistEntry, EmailTemplate, ImportBatch,
    MailPreference, OutboxAttachment,
    ImportMappingProfile, ImportRow, OutboxMessage, Pipeline, PipelineStage,
    ServiceCategory, StageAutomation, StageChange, Task,
)


def _company_by_name(tenant, name):
    """Match an existing company case-insensitively before creating one.

    Typing "Acme" for the second person at Acme must not produce a second
    company row — that is precisely the duplicate the import's matching rules
    exist to avoid, and a hand-typed name is no different.
    """
    existing = Company.all_objects.filter(
        tenant=tenant, name__iexact=name, deleted_at__isnull=True
    ).first()
    if existing is not None:
        return existing
    return Company.all_objects.create(tenant=tenant, name=name)


def _write_contact_children(tenant, contact, emails, phones, type_codes):
    """Emails, phones and types. First entry is primary unless one is marked."""
    for index, entry in enumerate(emails):
        address = (entry.get("address") or "").strip()
        if not address:
            continue
        ContactEmail.all_objects.create(
            tenant=tenant, contact=contact, address=address,
            is_primary=bool(entry.get("is_primary"))
            or (index == 0 and not any(e.get("is_primary") for e in emails)),
        )
    for index, entry in enumerate(phones):
        number = (entry.get("number") or "").strip()
        if not number:
            continue
        ContactPhone.all_objects.create(
            tenant=tenant, contact=contact, number=number,
            is_primary=bool(entry.get("is_primary"))
            or (index == 0 and not any(p.get("is_primary") for p in phones)),
        )
    if type_codes is None:
        return
    from apps.crm.services import referral

    wanted = {c for c in type_codes if c}
    ContactTypeLink.all_objects.filter(tenant=tenant, contact=contact).exclude(
        contact_type__code__in=wanted
    ).delete()
    for code in sorted(wanted):
        # Routed through referral.add_type so tagging someone a referral partner
        # here fires FR-1.23 onboarding exactly as it does on the contact page.
        referral.add_type(contact, code)


def _place(tenant, contact, placement, *, actor=None):
    """Optional initial pipeline placement (FR-1.6d). Silently skipped if the
    pipeline or stage cannot be resolved — a bad placement must not cost the
    user the contact they just typed."""
    if not placement:
        return None
    from apps.crm.services import importer, pipeline as pipeline_service

    pipeline_row = importer.resolve_pipeline(tenant, placement.get("pipeline"))
    stage = importer.resolve_stage(pipeline_row, placement.get("stage"))
    if stage is None:
        return None
    return pipeline_service.change_stage(contact, stage, actor=actor,
                                         reason="added by hand")


class ContactEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactEmail
        fields = ["id", "address", "is_primary"]


class ContactPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPhone
        fields = ["id", "number", "is_primary"]


class ContactSerializer(serializers.ModelSerializer):
    """FR-1.1/1.2 — reads flat, writes nested.

    Creating a contact by hand has to do in one request what the CSV importer
    does per row: the emails, the phones, the types and an optional pipeline
    placement are all part of "a contact", and asking the user to save four
    times to build one person would be a worse form than the spreadsheet they
    are leaving behind.
    """

    emails = ContactEmailSerializer(many=True, required=False)
    phones = ContactPhoneSerializer(many=True, required=False)
    type_codes = serializers.SerializerMethodField()
    # FR-1.6 — one entry per pipeline this contact is in. A referral partner who
    # is also a live prospect has two, and both matter.
    pipeline_positions = serializers.SerializerMethodField()

    # ---- write-only inputs
    types = serializers.ListField(
        child=serializers.CharField(), required=False, write_only=True,
        help_text="Contact type codes. Read them back as `type_codes`.",
    )
    #: FR-1.3 — a company typed in the form that does not exist yet. Matched
    #: case-insensitively first, so adding two people at one company does not
    #: silently create the company twice.
    company_name = serializers.CharField(
        required=False, allow_blank=True, write_only=True,
    )
    #: Optional initial placement: {"pipeline": id-or-name, "stage": id-or-code}.
    placement = serializers.DictField(required=False, write_only=True)

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "title", "company", "owner",
            "source", "background", "tags",
            "emails", "phones", "type_codes", "pipeline_positions",
            "types", "company_name", "placement",
            "referral_fee_terms", "referral_cadence", "referral_touch_mode",
            "referral_next_touch_at", "referral_onboarded_at",
            "merged_into", "created_at", "updated_at",
        ]
        read_only_fields = ["merged_into", "referral_onboarded_at"]

    def validate(self, attrs):
        if not (attrs.get("first_name") or attrs.get("last_name")
                or getattr(self.instance, "first_name", "")
                or getattr(self.instance, "last_name", "")):
            raise serializers.ValidationError(
                {"last_name": "A contact needs a first or a last name."}
            )
        emails = attrs.get("emails") or []
        if sum(1 for e in emails if e.get("is_primary")) > 1:
            raise serializers.ValidationError(
                {"emails": "Only one email address can be the primary one."}
            )
        phones = attrs.get("phones") or []
        if sum(1 for p in phones if p.get("is_primary")) > 1:
            raise serializers.ValidationError(
                {"phones": "Only one phone number can be the primary one."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        emails = validated_data.pop("emails", [])
        phones = validated_data.pop("phones", [])
        type_codes = validated_data.pop("types", [])
        company_name = (validated_data.pop("company_name", "") or "").strip()
        placement = validated_data.pop("placement", None)
        tenant = validated_data.get("tenant") or self.context["request"].tenant

        if validated_data.get("company") is None and company_name:
            validated_data["company"] = _company_by_name(tenant, company_name)
        # FR-1.1 — owner defaults to whoever is creating the record, which is
        # what drives a CF's own visibility (FR-1.9c).
        if not validated_data.get("owner"):
            validated_data["owner"] = self.context["request"].user

        contact = Contact.all_objects.create(**validated_data)
        _write_contact_children(tenant, contact, emails, phones, type_codes)
        _place(tenant, contact, placement, actor=self.context["request"].user)
        return contact

    @transaction.atomic
    def update(self, instance, validated_data):
        emails = validated_data.pop("emails", None)
        phones = validated_data.pop("phones", None)
        type_codes = validated_data.pop("types", None)
        company_name = (validated_data.pop("company_name", "") or "").strip()
        placement = validated_data.pop("placement", None)
        tenant = instance.tenant

        if validated_data.get("company") is None and company_name:
            validated_data["company"] = _company_by_name(tenant, company_name)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if emails is not None:
            instance.emails.all().delete()
        if phones is not None:
            instance.phones.all().delete()
        _write_contact_children(
            tenant, instance, emails or [], phones or [], type_codes,
        )
        _place(tenant, instance, placement, actor=self.context["request"].user)
        return instance

    def get_type_codes(self, obj):
        return sorted(link.contact_type.code for link in obj.type_links.all())

    def get_pipeline_positions(self, obj):
        return [
            {
                "pipeline": str(p.pipeline_id), "pipeline_name": p.pipeline.name,
                "pipeline_kind": p.pipeline.kind,
                "stage": str(p.stage_id), "stage_code": p.stage.code,
                "stage_label": p.stage.label, "semantic": p.stage.semantic,
                "entered_at": p.entered_at,
            }
            for p in sorted(
                obj.pipeline_positions.all(), key=lambda p: p.pipeline.position
            )
        ]


class CompanySerializer(serializers.ModelSerializer):
    seats_in_use = serializers.IntegerField(read_only=True)
    seats_available = serializers.IntegerField(read_only=True)
    # Write-only: `Company.domains` is the reverse manager, which a ListField
    # cannot read. Reads are served by `to_representation` below.
    domains = serializers.ListField(
        child=serializers.CharField(), required=False, write_only=True,
        help_text="FR-1.3 — email domains that identify this company.",
    )

    class Meta:
        model = Company
        fields = [
            "id", "name", "industry", "address", "primary_contact",
            "is_client_company", "seat_count", "digest_ai_prose", "domains",
            "seats_in_use", "seats_available", "created_at",
        ]
        # FR-1.6a — derived from a `won` stage in a sales pipeline, never set
        # directly.
        read_only_fields = ["is_client_company"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["domains"] = sorted(
            d.domain for d in CompanyDomain.all_objects.filter(
                tenant_id=instance.tenant_id, company=instance
            )
        )
        return data

    def validate_name(self, value):
        """FR-1.3 — a duplicate company by name is the thing the merge screen
        exists to clean up. Refusing here is cheaper than merging later."""
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("A company needs a name.")
        tenant = self.context["request"].tenant
        clash = Company.all_objects.filter(
            tenant=tenant, name__iexact=name, deleted_at__isnull=True
        ).exclude(pk=getattr(self.instance, "pk", None)).first()
        if clash is not None:
            raise serializers.ValidationError(
                f"“{clash.name}” already exists. Open it instead of creating a second one."
            )
        return name

    @transaction.atomic
    def create(self, validated_data):
        domains = validated_data.pop("domains", [])
        company = Company.all_objects.create(**validated_data)
        self._write_domains(company, domains)
        return company

    @transaction.atomic
    def update(self, instance, validated_data):
        domains = validated_data.pop("domains", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if domains is not None:
            CompanyDomain.all_objects.filter(
                tenant_id=instance.tenant_id, company=instance
            ).delete()
            self._write_domains(instance, domains)
        return instance

    @staticmethod
    def _write_domains(company, domains):
        seen = set()
        for raw in domains or []:
            domain = (raw or "").strip().lower().lstrip("@")
            if not domain or domain in seen:
                continue
            seen.add(domain)
            CompanyDomain.all_objects.get_or_create(
                tenant_id=company.tenant_id, company=company, domain=domain
            )


class CompanyDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyDomain
        fields = ["id", "company", "domain"]


class CompanyLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyLocation
        fields = ["id", "company", "name", "position"]


class PipelineStageSerializer(serializers.ModelSerializer):
    # Derived from `semantic`; there is no second column to drift.
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = PipelineStage
        fields = ["id", "pipeline", "code", "label", "semantic", "position",
                  "is_terminal"]


class PipelineSerializer(serializers.ModelSerializer):
    stages = PipelineStageSerializer(many=True, read_only=True)
    contact_count = serializers.SerializerMethodField()

    class Meta:
        model = Pipeline
        fields = ["id", "name", "kind", "position", "stages", "contact_count"]

    def get_contact_count(self, obj):
        return obj.positions.count()


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
    pipeline_name = serializers.CharField(source="pipeline.name", read_only=True)

    class Meta:
        model = StageChange
        fields = ["id", "contact", "pipeline", "pipeline_name", "from_code",
                  "to_code", "reason", "actor", "created_at"]


class StageAutomationSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()

    class Meta:
        model = StageAutomation
        fields = [
            "id", "pipeline", "from_stage", "to_stage", "action_type", "task_title_template",
            "task_due_offset_days", "email_template", "send_by_offset_days",
            "is_active", "summary",
        ]

    def get_summary(self, obj):
        """FR-1.13 — a plain-English summary of each rule."""
        where = f" in {obj.pipeline.name}"
        trigger = (
            f"When a contact reaches {obj.to_stage.label}{where}"
            if obj.from_stage is None
            else f"When a contact moves from {obj.from_stage.label} "
                 f"to {obj.to_stage.label}{where}"
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


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["id", "name", "kind", "subject", "body"]


class OutboxAttachmentSerializer(serializers.ModelSerializer):
    """FR-1.23b — the flyer WAS being attached; the Outbox just never showed it,
    which read as "no attachment" to the one person who needed to know."""

    byte_size = serializers.IntegerField(source="stored_file.byte_size", read_only=True)
    content_type = serializers.CharField(
        source="stored_file.content_type", read_only=True,
    )
    content_present = serializers.SerializerMethodField()

    class Meta:
        model = OutboxAttachment
        fields = ["id", "filename", "byte_size", "content_type", "content_present"]

    def get_content_present(self, obj):
        """Whether the bytes are actually in storage.

        The send now refuses rather than delivering an empty file, but finding
        that out at approval time is late. Files uploaded before storage wrote
        content exist as rows with nothing behind them, and this is what lets
        the Outbox say so first.
        """
        from apps.tenancy import storage

        return storage.exists(obj.stored_file)


class OutboxMessageSerializer(serializers.ModelSerializer):
    delivery = serializers.SerializerMethodField()
    attachments = OutboxAttachmentSerializer(many=True, read_only=True)
    sender_options = serializers.SerializerMethodField()

    class Meta:
        model = OutboxMessage
        fields = [
            "id", "state", "producer", "to_contact", "to_address", "from_address",
            "subject", "body_text", "body_html", "is_ai_generated", "warning",
            "send_by", "approved_by", "approved_at", "sent_at", "sent_via",
            "dev_real_send", "delivery", "attachments", "sender_options",
            "created_at",
        ]
        read_only_fields = ["state", "approved_by", "approved_at", "sent_at", "dev_real_send"]

    def get_sender_options(self, obj):
        """FR-1.15c — the addresses this draft may be sent from.

        Only verified send-as addresses appear: Gmail refuses anything else, and
        offering a choice that fails at send time is worse than not offering it.
        """
        request = self.context.get("request")
        if request is None or obj.state not in (
            OutboxMessage.State.PENDING_APPROVAL, OutboxMessage.State.DRAFT
        ):
            return []
        from apps.crm.services import sender as sender_service

        alias, own = sender_service.verified_addresses(obj.tenant, request.user)
        options = [{"value": "alias", "address": alias, "label": "The practice alias"}]
        if own:
            options.append({"value": "self", "address": own, "label": "My own address"})
        return options

    def get_delivery(self, obj):
        """FR-0.7 — where this will actually go, decided BEFORE approval.

        The `dev_real_send` flag only exists once a message has been sent, which
        is too late to be useful to the person deciding whether to approve it.
        This answers the question they are actually asking: is a real human
        about to receive this?
        """
        from apps.accounts.mailer import is_real_send_allowed

        if not dj_settings.IS_LOCAL:
            return {"target": "real", "label": "Real delivery", "is_local_build": False}
        real = is_real_send_allowed(obj.to_address, obj.tenant)
        return {
            "target": "real" if real else "dev",
            "label": "Real delivery" if real else "Dev mailbox (Mailpit)",
            "is_local_build": True,
            "detail": (
                f"{obj.to_address} is on this build's allow-list, so approving "
                "this sends a real email to a real person."
                if real else
                f"{obj.to_address} is not on this build's allow-list, so this "
                "goes to Mailpit and never reaches them."
            ),
        }


class MailPreferenceSerializer(serializers.ModelSerializer):
    """FR-1.15c/d — per-user sender defaults and signature."""

    effective = serializers.SerializerMethodField()
    available = serializers.SerializerMethodField()

    class Meta:
        model = MailPreference
        fields = ["id", "sender_by_producer", "signature_text", "signature_html",
                  "effective", "available"]

    def get_effective(self, obj):
        """What each producer resolves to today, defaults included — so the
        screen shows the rule in force, not just the overrides."""
        return {
            producer: obj.sender_for(producer)
            for producer in MailPreference.DEFAULTS
        }

    def get_available(self, obj):
        from apps.crm.services import sender as sender_service

        alias, own = sender_service.verified_addresses(obj.tenant, obj.user)
        return {"alias": alias, "self": own}

    def validate_sender_by_producer(self, value):
        allowed = set(MailPreference.Sender.values)
        for producer, choice in (value or {}).items():
            if producer not in MailPreference.DEFAULTS:
                raise serializers.ValidationError(f"Unknown producer {producer!r}.")
            if choice not in allowed:
                raise serializers.ValidationError(
                    f"{choice!r} is not a sender choice; use one of {sorted(allowed)}."
                )
        return value


class DevSendAllowlistEntrySerializer(serializers.ModelSerializer):
    """H6 — exact addresses only, validated in one shared place."""

    # A plain CharField on purpose: EmailField's own validator runs first and
    # would answer "Enter a valid email address" to a wildcard, burying the one
    # thing the person needs to be told — WHY a domain is refused here.
    address = serializers.CharField()

    class Meta:
        model = DevSendAllowlistEntry
        fields = ["id", "address", "note", "added_by", "created_at"]
        read_only_fields = ["added_by"]

    def validate_address(self, value):
        from apps.accounts.mailer import AllowlistEntryInvalid, normalise_allowlist_entry

        try:
            address = normalise_allowlist_entry(value)
        except AllowlistEntryInvalid as exc:
            raise serializers.ValidationError(str(exc)) from exc
        tenant = self.context["request"].tenant
        if DevSendAllowlistEntry.all_objects.filter(
            tenant=tenant, address=address
        ).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError(f"{address} is already on the list.")
        return address


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "due_date", "owner",
                  "contact", "source_automation", "created_at"]


class ImportRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportRow
        fields = ["id", "row_number", "raw", "outcome", "error_text", "contact",
                  "candidate_ids", "preview"]


class ImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportBatch
        fields = ["id", "filename", "status", "counts", "created_by",
                  "rolled_back_at", "created_at", "mapping", "value_mapping"]


class ImportMappingProfileSerializer(serializers.ModelSerializer):
    """FR-1.27 — the remembered mapping, columns and values together."""

    class Meta:
        model = ImportMappingProfile
        fields = ["id", "name", "mapping", "value_mapping", "updated_at"]
