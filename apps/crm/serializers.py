from __future__ import annotations

from django.conf import settings as dj_settings
from django.db import transaction
from rest_framework import serializers

from apps.crm.models import (
    Company, CompanyDomain, CompanyLocation, Contact, ContactEmail, ContactPhone,
    ContactType, ContactTypeLink, DevSendAllowlistEntry, EmailTemplate, ImportBatch,
    MailPreference, OutboxAttachment,
    ImportMappingProfile, ImportRow, OutboxMessage, Pipeline, PipelineStage,
    ServiceCategory, StageAutomation, StageChange, StageSemantic, Task,
)


class PageUrlField(serializers.CharField):
    """A person's or a company's page on one network (owner, 2026-10-12).

    Pasted as people paste them: with or without `https://`. Kept only when it
    is an address on that network, because it is shown as a link under the
    network's name."""

    def __init__(self, *, network: str, host: str, **kwargs):
        self.network, self.host = network, host
        super().__init__(required=False, allow_blank=True, max_length=500, **kwargs)

    def to_internal_value(self, data):
        from urllib.parse import urlsplit

        from django.core.exceptions import ValidationError
        from django.core.validators import URLValidator

        value = super().to_internal_value(data).strip()
        if not value:
            return ""
        if "://" not in value:
            value = f"https://{value}"
        try:
            URLValidator(schemes=["http", "https"])(value)
        except ValidationError:
            raise serializers.ValidationError(f"That is not a {self.network} address.")
        host = (urlsplit(value).hostname or "").lower()
        if host != self.host and not host.endswith(f".{self.host}"):
            raise serializers.ValidationError(
                f"That is not a {self.network} address: it should be on {self.host}.")
        return value


def _company_by_name(tenant, name):
    """Match an existing company case-insensitively before creating one.

    Typing "Acme" for the second person at Acme must not produce a second
    company row — that is precisely the duplicate the import's matching rules
    exist to avoid, and a hand-typed name is no different.
    """
    existing = Company.all_objects.filter(
        tenant=tenant, name__iexact=name, deleted_at__isnull=True, is_practice=False
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


#: "How I'd introduce them": a line or two.
INTRO_BLURB_LONGEST = 600


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
    linkedin_url = PageUrlField(network="LinkedIn", host="linkedin.com")
    alignable_url = PageUrlField(network="Alignable", host="alignable.com")

    #: Who referred them into the sales pipeline (owner, 2026-10-20), and on
    #: create, the contact to record as having referred them.
    discipline_label = serializers.SerializerMethodField()
    specialties = serializers.ListField(child=serializers.CharField(max_length=200, allow_blank=True),
                                        required=False)
    referred_by = serializers.SerializerMethodField()
    referrer = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    def get_referred_by(self, obj):
        from apps.crm.models import Pipeline, Referral

        row = next((r for r in obj.referrals_received.all()
                    if r.direction == Referral.Direction.INBOUND
                    and r.pipeline.kind == Pipeline.Kind.SALES), None)
        if row is None:
            return None
        # An associate sees only their own universe (FR-1.9c): a referrer
        # outside it is not named.
        from apps.crm import permissions as crm_perms

        request = self.context.get("request")
        if request is None:
            return None  # fails closed: nobody to say who may see the name
        if (crm_perms.role_of(request) == "CF"
                and not crm_perms.contact_queryset_for(
                request, Contact.objects.filter(pk=row.referrer_id,
                                                deleted_at__isnull=True)).exists()):
            return None
        referrer = row.referrer
        return {"id": str(row.pk), "referrer": str(referrer.pk),
                "referrer_name": f"{referrer.first_name} {referrer.last_name}".strip(),
                "referred_on": row.referred_on.isoformat(), "note": row.note,
                "outcome": row.outcome}

    #: Whether a touch will ever be drafted for them (owner, 2026-09-28).
    #: Annotated on the list, looked up for a single contact.
    referral_enrolled = serializers.SerializerMethodField()

    def get_referral_enrolled(self, obj):
        annotated = getattr(obj, "referral_enrolled_annotated", None)
        if annotated is not None:
            return annotated
        return obj.enrollments.filter(program="referral_touches",
                                      ended_at__isnull=True).exists()

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "title", "company", "owner",
            "source", "background", "tags", "linkedin_url", "alignable_url",
            "emails", "phones", "type_codes", "pipeline_positions",
            "types", "company_name", "placement", "referred_by", "referrer",
            "referral_fee_terms", "referral_cadence", "referral_touch_mode",
            "referral_template", "referral_next_touch_at", "referral_onboarded_at", "referral_enrolled",
            "merged_into", "created_at", "updated_at",
            # R3b: what a partner does.
            "discipline", "discipline_label", "specialties", "pronouns", "intro_blurb",
        ]
        read_only_fields = ["merged_into", "referral_onboarded_at"]

    def get_discipline_label(self, obj):
        return obj.get_discipline_display() if obj.discipline else ""

    def validate_intro_blurb(self, value):
        value = (value or "").strip()
        if len(value) > INTRO_BLURB_LONGEST:
            raise serializers.ValidationError(
                f"Keep it to {INTRO_BLURB_LONGEST} characters: a line or two.")
        return value

    def validate_specialties(self, value):
        from apps.crm.services import introductions

        try:
            return introductions.clean_specialties(value)
        except introductions.IntroductionRefused as exc:
            raise serializers.ValidationError(str(exc)) from exc

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
        referrer_id = validated_data.pop("referrer", None)
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
        if referrer_id:
            _record_referral(contact, referrer_id, request=self.context["request"])
        return contact

    @transaction.atomic
    def update(self, instance, validated_data):
        emails = validated_data.pop("emails", None)
        phones = validated_data.pop("phones", None)
        type_codes = validated_data.pop("types", None)
        company_name = (validated_data.pop("company_name", "") or "").strip()
        placement = validated_data.pop("placement", None)
        # Changed on the contact page, through /api/referrals/.
        validated_data.pop("referrer", None)
        tenant = instance.tenant

        if validated_data.get("company") is None and company_name:
            validated_data["company"] = _company_by_name(tenant, company_name)
        before = (instance.discipline, list(instance.specialties or []))
        intro_before = (instance.pronouns, instance.intro_blurb)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if (instance.pronouns, instance.intro_blurb) != intro_before:
            from apps.tenancy.models import AuditEvent

            AuditEvent.all_objects.create(
                tenant=tenant, actor=self.context["request"].user,
                verb="contact.introduction_words_changed", target_type="contact",
                target_id=instance.pk,
                payload={"pronouns": instance.get_pronouns_display() or "they",
                         "intro_blurb": instance.intro_blurb})
        if (instance.discipline, list(instance.specialties or [])) != before:
            # R3b: what a partner does, on Activity.
            from apps.tenancy.models import AuditEvent

            AuditEvent.all_objects.create(
                tenant=tenant, actor=self.context["request"].user,
                verb="contact.specialties_changed", target_type="contact",
                target_id=instance.pk,
                payload={"discipline": instance.discipline,
                         "specialties": list(instance.specialties or [])})

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
        from apps.crm.services import follow_ups

        # Part 3: the follow-up running in each pipeline, as a line to show.
        runs = {r.stage.pipeline_id: follow_ups.line_for(r) for r in follow_ups.running(obj)}
        return [
            {
                "pipeline": str(p.pipeline_id), "pipeline_name": p.pipeline.name,
                "pipeline_kind": p.pipeline.kind,
                "stage": str(p.stage_id), "stage_code": p.stage.code,
                "stage_label": p.stage.label, "semantic": p.stage.semantic,
                # Since they entered the stage they are in (part 2); older
                # rows have only when they joined the pipeline.
                "entered_at": p.stage_entered_at or p.entered_at,
                "follow_up": runs.get(p.pipeline_id),
            }
            for p in sorted(
                obj.pipeline_positions.all(), key=lambda p: p.pipeline.position
            )
        ]


def _record_referral(contact, referrer_id, *, request):
    """The referrer chosen on the new-contact form, recorded in the same
    request; one the person saving cannot see is refused, not guessed."""
    from apps.crm import permissions as crm_perms
    from apps.crm.services import referrals

    referrer = crm_perms.contact_queryset_for(
        request, Contact.objects.filter(pk=referrer_id, deleted_at__isnull=True)).first()
    if referrer is None:
        raise serializers.ValidationError({"referrer": "That contact is not available."})
    try:
        referrals.record(contact, referrer, actor=request.user)
    except referrals.ReferralRefused as exc:
        raise serializers.ValidationError({"referrer": str(exc)})


class CompanySerializer(serializers.ModelSerializer):
    linkedin_url = PageUrlField(network="LinkedIn", host="linkedin.com")
    alignable_url = PageUrlField(network="Alignable", host="alignable.com")
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
            "id", "name", "industry", "address", "linkedin_url", "alignable_url",
            "primary_contact",
            "is_client_company", "seat_count", "digest_ai_prose", "domains",
            "seats_in_use", "seats_available", "created_at",
        ]
        # FR-1.6a — derived from a `won` stage in a sales pipeline, never set
        # directly.
        read_only_fields = ["is_client_company"]

    def to_representation(self, instance):
        from apps.tenancy.models import Role

        data = super().to_representation(instance)
        data["domains"] = sorted(
            d.domain for d in CompanyDomain.all_objects.filter(
                tenant_id=instance.tenant_id, company=instance
            )
        )
        # Matrix 9.5 — seat usage is the FF's, or a CF's on companies they can
        # reach. A VA sees companies but not how many seats are in use. Fails
        # closed: with no request to say who is asking, nobody gets it.
        membership = getattr(self.context.get("request"), "membership", None)
        if membership is None or membership.role not in (Role.FF, Role.CF):
            data.pop("seats_in_use", None)
            data.pop("seats_available", None)
        return data

    def validate_primary_contact(self, value):
        """FR-1.3a / matrix 4.8 — one of this company's own contacts, set by the
        FF or a CF (who only reaches companies they are assigned). It changes the
        FCC default for the *next* grant and nothing else: an existing portal
        user's role changes only through portal access (matrix 9.2a)."""
        from rest_framework.exceptions import PermissionDenied

        from apps.tenancy.models import Role

        # Resending the current value (a VA saving other fields) is not setting it.
        if getattr(value, "pk", None) == getattr(self.instance, "primary_contact_id", None):
            return value
        membership = getattr(self.context["request"], "membership", None)
        if membership is None or membership.role not in (Role.FF, Role.CF):
            raise PermissionDenied(
                "Only the practice owner or an associate sets the primary contact.")
        if value is not None and (self.instance is None
                                  or value.company_id != self.instance.pk
                                  or value.deleted_at is not None):
            raise serializers.ValidationError(
                f"{value.first_name} {value.last_name}".strip()
                + " is not one of this company's contacts.")
        return value

    def validate_name(self, value):
        """FR-1.3 — a duplicate company by name is the thing the merge screen
        exists to clean up. Refusing here is cheaper than merging later."""
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("A company needs a name.")
        tenant = self.context["request"].tenant
        clash = Company.all_objects.filter(
            tenant=tenant, name__iexact=name, deleted_at__isnull=True, is_practice=False
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
        from apps.tenancy.models import AuditEvent

        domains = validated_data.pop("domains", None)
        old_primary = instance.primary_contact
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        # The primary contact decides who is offered as the founder user
        # (FR-3.33d), so who changed it, from whom and to whom, is on record.
        new_primary = instance.primary_contact
        if "primary_contact" in validated_data and \
                getattr(old_primary, "pk", None) != getattr(new_primary, "pk", None):
            def who(contact):
                return (None if contact is None else
                        {"id": str(contact.pk),
                         "name": f"{contact.first_name} {contact.last_name}".strip()})

            AuditEvent.all_objects.create(
                tenant_id=instance.tenant_id, actor=self.context["request"].user,
                verb="company.primary_contact_changed",
                target_type="company", target_id=instance.pk,
                payload={"from": who(old_primary), "to": who(new_primary)},
            )
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
    contacts = serializers.SerializerMethodField()

    class Meta:
        model = PipelineStage
        fields = ["id", "pipeline", "code", "label", "semantic", "position",
                  "is_terminal", "contacts"]
        extra_kwargs = {"code": {"required": False}, "position": {"required": False}}

    def get_contacts(self, obj):
        return obj.positions.count()

    def create(self, validated_data):
        """A stage added on the rules screen is named, not coded: its code is
        made from the name, unique in its pipeline, and it goes last."""
        from django.db.models import Max
        from django.utils.text import slugify

        pipeline = validated_data["pipeline"]
        if not validated_data.get("code"):
            base = slugify(validated_data.get("label") or "stage").replace("-", "_")[:28] or "stage"
            code, n = base, 2
            while PipelineStage.all_objects.filter(pipeline=pipeline, code=code).exists():
                code, n = f"{base}_{n}", n + 1
            validated_data["code"] = code
        if "position" not in validated_data:
            last = PipelineStage.all_objects.filter(pipeline=pipeline).aggregate(
                n=Max("position"))["n"]
            validated_data["position"] = 0 if last is None else last + 1
        return super().create(validated_data)


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
    """A stage rule (FR-1.10 to 1.14; part 2, 2026-10-24): a trigger on one
    pipeline, and one action. Checked here so a rule that could never fire,
    or fire into another pipeline, is refused in words."""

    summary = serializers.SerializerMethodField()

    class Meta:
        model = StageAutomation
        fields = [
            "id", "pipeline", "trigger", "from_stage", "to_stage", "idle_days", "action_type",
            "task_title_template", "task_due_offset_days", "task_client_visible", "task_for",
            "task_assignee", "email_template", "send_by_offset_days", "move_to_stage",
            "touch_cadence", "notice_text", "event_minutes", "is_active", "position", "summary",
            "document_template",
        ]
        extra_kwargs = {"task_client_visible": {"required": False},
                        "to_stage": {"required": False}, "position": {"required": False}}

    def validate(self, attrs):
        from apps.crm.services import stage_rules
        from apps.tenancy.models import Membership

        merged = {f: getattr(self.instance, f) for f in (
            "pipeline", "trigger", "from_stage", "to_stage", "idle_days", "action_type",
            "task_title_template", "move_to_stage", "touch_cadence", "notice_text",
            "task_for", "task_assignee", "email_template", "document_template")} \
            if self.instance else {}
        merged.update(attrs)
        get = merged.get
        pipeline = get("pipeline")
        trigger = get("trigger") or StageAutomation.Trigger.ENTERS
        R = StageAutomation
        for key in ("from_stage", "to_stage", "move_to_stage"):
            stage = get(key)
            if stage is not None and pipeline is not None and stage.pipeline_id != pipeline.pk:
                raise serializers.ValidationError(
                    {key: f"{stage.label} is on another pipeline; a rule stays on its own."})
        if trigger in (R.Trigger.ENTERS, R.Trigger.IDLE) and get("to_stage") is None:
            raise serializers.ValidationError({"to_stage": "Choose the stage."})
        if trigger in (R.Trigger.WON, R.Trigger.LOST, R.Trigger.DOC_SENT, R.Trigger.DOC_SIGNED):
            attrs["to_stage"] = None
            attrs["from_stage"] = None
        if trigger == R.Trigger.IDLE:
            if not get("idle_days") or get("idle_days") < 1:
                raise serializers.ValidationError({"idle_days": "How many days, 1 or more?"})
            attrs["from_stage"] = None
        action = get("action_type")
        if action == R.Action.MOVE_STAGE:
            target = get("move_to_stage")
            if target is None:
                raise serializers.ValidationError({"move_to_stage": "Choose where to move them."})
            if trigger == R.Trigger.ENTERS and target == get("to_stage"):
                raise serializers.ValidationError(
                    {"move_to_stage": "They are already there when this rule fires."})
        if action == R.Action.ENROLL_TOUCHES and get("touch_cadence") not in (
                "", None, "monthly", "bimonthly", "quarterly"):
            raise serializers.ValidationError(
                {"touch_cadence": "Monthly, every two months or quarterly."})
        if action == R.Action.NOTIFY and not (get("notice_text") or "").strip():
            raise serializers.ValidationError({"notice_text": "Say what the notice says."})
        if action == R.Action.START_FOLLOW_UP and trigger in (R.Trigger.ENTERS, R.Trigger.IDLE):
            from apps.crm.services import follow_ups

            if follow_ups.follow_up_of(get("to_stage")) is None:
                raise serializers.ValidationError({"action_type": (
                    f"{get('to_stage').label} has no follow-up yet: set one on its card first.")})
        if action == R.Action.CALENDAR_EVENT:
            if trigger != R.Trigger.ENTERS:
                raise serializers.ValidationError({"trigger": (
                    "A calendar event is offered to the person moving the card, so it is for "
                    "a contact entering a stage.")})
            if not (get("task_title_template") or "").strip():
                raise serializers.ValidationError({"task_title_template": "Give the event a title."})
            minutes = get("event_minutes")
            if minutes is not None and not 5 <= minutes <= 480:
                raise serializers.ValidationError(
                    {"event_minutes": "Between 5 minutes and 8 hours."})
        if action == R.Action.CREATE_TASK and not (get("task_title_template") or "").strip():
            raise serializers.ValidationError({"task_title_template": "Give the task a title."})
        if action == R.Action.DRAFT_EMAIL and get("email_template") is None:
            raise serializers.ValidationError({"email_template": "Choose a template."})
        if action == R.Action.SEND_SIGNATURE:
            if get("document_template") is None:
                raise serializers.ValidationError(
                    {"document_template": "Choose a document template."})
            if trigger == R.Trigger.DOC_SENT:
                raise serializers.ValidationError({"action_type": (
                    "Sending a document when one is sent would never stop. Choose another "
                    "trigger.")})
        if get("task_for") == R.For.MEMBER:
            who = get("task_assignee")
            if who is None or not Membership.all_objects.filter(
                    tenant_id=pipeline.tenant_id, user=who, revoked_at__isnull=True,
                    role__in=("FF", "CF", "VA")).exists():
                raise serializers.ValidationError(
                    {"task_assignee": "Choose someone on the practice's team."})
        for key in ("task_title_template", "notice_text"):
            try:
                stage_rules.check_fields(get(key) or "")
            except stage_rules.RuleRefused as exc:
                raise serializers.ValidationError({key: str(exc)}) from exc
        return attrs

    def create(self, validated_data):
        """A new rule is internal unless the FF says otherwise — except on a
        sales `won` stage (or a won rule), whose task is for the new client.
        Only the default differs: whatever the FF sent is kept."""
        if "task_client_visible" not in validated_data:
            stage = validated_data.get("to_stage")
            pipeline = validated_data["pipeline"]
            validated_data["task_client_visible"] = pipeline.kind == Pipeline.Kind.SALES and (
                validated_data.get("trigger") == StageAutomation.Trigger.WON
                or (stage is not None and stage.semantic == StageSemantic.WON))
        return super().create(validated_data)

    def get_summary(self, obj):
        """FR-1.13 — a plain-English summary of each rule."""
        from apps.crm.services import stage_rules

        return stage_rules.summary(obj)


class EmailTemplateSerializer(serializers.ModelSerializer):
    """The library (owner, 2026-10-20): plain text, merge fields checked on
    save, a built-in one marked with whether it still reads as the original."""

    is_original = serializers.SerializerMethodField()
    changed = serializers.SerializerMethodField()
    used_for = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = ["id", "name", "kind", "subject", "body", "first_name_fallback",
                  "original", "is_original", "changed", "used_for", "updated_at"]
        read_only_fields = ["kind", "original", "updated_at"]
        extra_kwargs = {"first_name_fallback": {"allow_blank": True}}

    def get_is_original(self, obj):
        return bool(obj.original)

    def get_changed(self, obj):
        from apps.crm.services import templates

        return templates.is_changed(obj)

    def get_used_for(self, obj):
        from apps.crm.services import templates

        return templates.used_for(obj)

    def validate(self, attrs):
        from apps.crm.services import templates

        subject = attrs.get("subject", getattr(self.instance, "subject", ""))
        body = attrs.get("body", getattr(self.instance, "body", ""))
        try:
            templates.check(subject, body)
        except templates.TemplateRefused as refused:
            raise serializers.ValidationError({"body": str(refused)}) from None
        if "first_name_fallback" in attrs:
            attrs["first_name_fallback"] = (attrs["first_name_fallback"] or "").strip() \
                or templates.DEFAULT_FALLBACK
        return attrs


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

        return storage.present_or_unknown(obj.stored_file)


class OutboxMessageSerializer(serializers.ModelSerializer):
    delivery = serializers.SerializerMethodField()
    attachments = OutboxAttachmentSerializer(many=True, read_only=True)
    sender_options = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    mailbox_label = serializers.SerializerMethodField()

    class Meta:
        model = OutboxMessage
        fields = [
            "id", "state", "producer", "label", "to_contact", "to_address", "also_to_address",
            "from_address",
            "subject", "body_text", "body_html", "is_ai_generated", "warning",
            "send_by", "approved_by", "approved_at", "sent_at", "sent_via",
            "dev_real_send", "delivery", "attachments", "sender_options",
            "mailbox_label", "created_at",
        ]
        read_only_fields = ["state", "approved_by", "approved_at", "sent_at", "dev_real_send"]

    def get_mailbox_label(self, obj):
        """Which mailbox it goes through, in words, when it is not someone's
        own (2026-10-28)."""
        mailbox = obj.mailbox
        if mailbox is None or mailbox.is_own:
            return ""
        return mailbox.label or mailbox.email_address

    def get_label(self, obj):
        """What the email is, in words: for a referral thank-you, which moment
        and whose introduction, since two can share a subject."""
        if obj.producer == OutboxMessage.Producer.REFERRAL_THANKS:
            from apps.crm.services import referrals

            return referrals.label_of(obj)
        return obj.get_producer_display()

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

        from apps.crm.services import mailboxes

        alias, own = sender_service.verified_addresses(obj.tenant, request.user)
        options = [{"value": "alias", "address": alias, "label": "The practice alias"}]
        if own:
            options.append({"value": "self", "address": own, "label": "My own address"})
        # Every other connected mailbox (2026-10-28), by its own address.
        seen = {alias.lower(), own.lower()}
        for option in mailboxes.options(obj.tenant, request.user):
            if option["address"] not in seen:
                seen.add(option["address"])
                options.append({"value": option["value"], "address": option["address"],
                                "label": option["label"]})
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
        from apps.crm.services.outbox import recipients_of

        # One check per address: real only when every one is on the list.
        addresses = recipients_of(obj)
        off = [a for a in addresses if not is_real_send_allowed(a, obj.tenant, obj.mailbox)]
        real = not off
        named = " and ".join(addresses)
        return {
            "target": "real" if real else "dev",
            "label": "Real delivery" if real else "Dev mailbox (Mailpit)",
            "is_local_build": True,
            "detail": (
                f"{named} {'is' if len(addresses) == 1 else 'are'} on this build's "
                "allow-list, so approving this sends a real email to a real person."
                if real else
                f"{' and '.join(off)} {'is' if len(off) == 1 else 'are'} not on this "
                "build's allow-list, so this goes to Mailpit and never reaches "
                f"{'them' if len(addresses) == 1 else 'either of them'}."
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
        fields = ["id", "address", "note", "mailbox", "added_by", "created_at"]
        read_only_fields = ["added_by"]

    def validate_mailbox(self, value):
        # Only for mail from one of this practice's mailboxes (2026-10-28).
        if value is not None and value.tenant_id != self.context["request"].tenant.pk:
            raise serializers.ValidationError("Choose one of the practice's mailboxes.")
        return value

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
