"""People: HR permissions, the person record and its access log (2026-11-17).

**HR permissions** are held by person, whatever their role: **HR Director**
sees everything the app holds; **HR Generalist** sees the sensitive fields
masked. The practice owner is HR Director for the practice and every client
by being its owner, and grants either level to anyone on the practice team,
for one client company, for the practice's own people, or for all. A client
owner is HR Director for their own company by being its owner, and grants
either level to their own people.

**The person record** is a placeholder in this build: enough to prove who
reaches what. Its directory fields (name, title, team, work email, manager)
are plain; its **sensitive fields** (pay rate, home address, date of birth,
personal phone and email, emergency contact, documents) are encrypted at
rest, together, under the same key as the other secrets.

**The access log** records every view, change and export of a person's
sensitive data: who, when, which person, which fields, from where. Nobody can
edit it: rows are written once, and changing or deleting one is refused.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.managers import AllTenantsManager, TenantManager, TenantQuerySet
from apps.tenancy.models import TenantScopedModel


class Level(models.TextChoices):
    DIRECTOR = "director", "HR Director"
    GENERALIST = "generalist", "HR Generalist"


class HRGrant(TenantScopedModel):
    """One person's HR permission: for one client company (`client_company`),
    for the practice's own people (neither set), or for all (`all_companies`).
    Revoked, it is kept."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="hr_grants")
    level = models.CharField(max_length=12, choices=Level.choices)
    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.CASCADE, related_name="hr_grants")
    all_companies = models.BooleanField(default=False, db_default=False)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "hr_grant"
        constraints = [
            models.CheckConstraint(condition=~Q(all_companies=True, client_company__isnull=False),
                                   name="hr_grant_one_scope"),
            models.UniqueConstraint(fields=["tenant", "user", "client_company", "all_companies"],
                                    condition=Q(revoked_at__isnull=True),
                                    nulls_distinct=False, name="hr_grant_once_per_scope"),
        ]


#: The directory fields: anyone who reaches a person sees these.
DIRECTORY = ("name", "title", "department", "team", "work_email", "work_phone", "manager")
DIRECTORY_LABELS = {"name": "Name", "title": "Title", "department": "Department", "team": "Team",
                    "work_email": "Work email", "work_phone": "Work phone",
                    "manager": "Manager"}
#: The employment fields (2026-11-17, the records): HR permissions and the
#: person themself see these, unmasked; they are not among the sensitive ones.
EMPLOYMENT = ("status", "employment_type", "work_state", "start_date")
EMPLOYMENT_LABELS = {"status": "Status", "employment_type": "Employment type",
                     "work_state": "Work state", "start_date": "Start date"}
#: The sensitive fields: an HR Director sees them; an HR Generalist masked.
SENSITIVE = ("pay_rate", "pay_unit", "pay_effective_on", "home_address", "date_of_birth",
             "personal_phone", "personal_email", "emergency_contact", "documents")
SENSITIVE_LABELS = {
    "pay_rate": "Pay rate", "pay_unit": "Pay unit", "pay_effective_on": "Pay effective",
    "home_address": "Home address", "date_of_birth": "Date of birth",
    "personal_phone": "Personal phone", "personal_email": "Personal email",
    "emergency_contact": "Emergency contact", "documents": "Documents",
}
#: Never stored, and no field for them: given to the payroll provider directly.
NEVER_STORED = ("Social Security numbers", "bank details", "I-9 documents",
                "medical and leave paperwork", "background checks", "benefits")
HELD_IN_PAYROLL = ("Social Security number, bank details, I-9 documents, medical and leave "
                   "paperwork, background checks and benefits are held in payroll, not here.")


class Status(models.TextChoices):
    OFFER_OUT = "offer_out", "Offer out"
    ONBOARDING = "onboarding", "Onboarding"
    ACTIVE = "active", "Active"
    ON_LEAVE = "on_leave", "On leave"
    OFFBOARDING = "offboarding", "Offboarding"
    ENDED = "ended", "Ended"


class EmploymentType(models.TextChoices):
    FULL_TIME = "full_time", "Employee, full-time"
    PART_TIME = "part_time", "Employee, part-time"
    CONTRACTOR = "contractor", "Contractor"


class PayUnit(models.TextChoices):
    HOUR = "hour", "an hour"
    WEEK = "week", "a week"
    MONTH = "month", "a month"
    YEAR = "year", "a year"
    PROJECT = "project", "a project"


class PersonRecord(TenantScopedModel):
    """A person, at a client company or (no company) the practice itself.

    The employee record (2026-11-17): directory fields plain, employment
    fields plain, the sensitive ones encrypted together. `user` is their
    portal sign-in, where they have one; a person without one still has a
    record. `made_contact` is the contact People made to send them something
    to sign (an offer letter): it never reaches an AI app or search."""

    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="people")
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, blank=True, default="", db_default="")
    title = models.CharField(max_length=120, blank=True, default="", db_default="")
    department = models.CharField(max_length=120, blank=True, default="", db_default="")
    team = models.CharField(max_length=120, blank=True, default="", db_default="")
    work_email = models.EmailField(blank=True, default="", db_default="")
    work_phone = models.CharField(max_length=40, blank=True, default="", db_default="")
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="reports")
    employment_type = models.CharField(max_length=12, choices=EmploymentType.choices,
                                       default=EmploymentType.FULL_TIME,
                                       db_default=EmploymentType.FULL_TIME)
    #: The two-letter state they work in.
    work_state = models.CharField(max_length=2, blank=True, default="", db_default="")
    start_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE,
                              db_default=Status.ACTIVE)
    #: Their last day, once offboarding has ended them.
    ended_on = models.DateField(null=True, blank=True)
    #: The company's own fields: {field id: value} (`PeopleCustomField`).
    custom_values = models.JSONField(default=dict, blank=True)
    #: Their own sign-in, so they see their own record.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="person_records")
    made_contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="people_made")
    #: The sensitive fields, as one encrypted JSON object (Fernet).
    sensitive_ciphertext = models.BinaryField(null=True, blank=True)
    is_placeholder = models.BooleanField(default=True, db_default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "person_record"
        indexes = [models.Index(fields=["tenant", "client_company"])]

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# ------------------------------------------------------------ custom fields

class Target(models.TextChoices):
    RECORD = "record", "The record"
    ONBOARDING = "onboarding", "Onboarding"
    OFFBOARDING = "offboarding", "Offboarding"


class PeopleCustomField(TenantScopedModel):
    """A field of the company's own, on its records or on a checklist. One
    whose label names something never stored is refused (`NEVER_STORED`)."""

    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.CASCADE, related_name="+")
    target = models.CharField(max_length=12, choices=Target.choices)
    label = models.CharField(max_length=80)
    position = models.PositiveIntegerField(default=0, db_default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "people_custom_field"
        indexes = [models.Index(fields=["tenant", "client_company", "target"])]


# ------------------------------------------------------------ checklists

class Kind(models.TextChoices):
    ONBOARDING = "onboarding", "Onboarding"
    OFFBOARDING = "offboarding", "Offboarding"


class Section(models.TextChoices):
    PEOPLE = "people", "People"
    IT = "it", "IT"
    MANAGER = "manager", "Manager"


class OwnerRole(models.TextChoices):
    HR = "hr", "Whoever starts it"
    IT = "it", "The IT owner"
    MANAGER = "manager", "Their manager"
    EMPLOYEE = "employee", "The person themself"


class TemplateItem(TenantScopedModel):
    """One item of a company's onboarding or offboarding checklist. The
    People Command Center's standard items are copied in the first time a
    company's checklists are opened; each company adds, edits and reorders
    its own from there."""

    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    section = models.CharField(max_length=8, choices=Section.choices)
    title = models.CharField(max_length=200)
    owner_role = models.CharField(max_length=8, choices=OwnerRole.choices)
    #: Days from the start date (onboarding) or the last day (offboarding).
    due_days = models.IntegerField(default=0, db_default=0)
    position = models.PositiveIntegerField(default=0, db_default=0)
    #: The shipped item it was copied from, if any.
    standard_key = models.CharField(max_length=60, blank=True, default="", db_default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "people_template_item"
        indexes = [models.Index(fields=["tenant", "client_company", "kind"])]


class Checklist(TenantScopedModel):
    """One onboarding or offboarding of one person. Offboarding closes only
    when each item is done, or waived with a note; it never ends anyone in a
    payroll system."""

    class Reason(models.TextChoices):
        RESIGNATION = "resignation", "Resignation"
        TERMINATION = "termination", "Termination"
        LAYOFF = "layoff", "Layoff"
        RETIREMENT = "retirement", "Retirement"
        CONTRACT_END = "contract_end", "Contract ended"
        OTHER = "other", "Other"

    person = models.ForeignKey(PersonRecord, on_delete=models.CASCADE, related_name="checklists")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    #: The start date (onboarding) or the last day (offboarding).
    anchor_date = models.DateField()
    reason = models.CharField(max_length=14, choices=Reason.choices, blank=True, default="",
                              db_default="")
    note = models.TextField(blank=True, default="", db_default="")
    hr_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    it_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    manager_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    custom_values = models.JSONField(default=dict, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "people_checklist"
        constraints = [
            models.UniqueConstraint(fields=["person", "kind"], condition=Q(closed_at__isnull=True),
                                    name="people_checklist_one_open_each"),
        ]


class ChecklistItem(TenantScopedModel):
    """One item, and its task in Work. Done in Work is done here."""

    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="items")
    section = models.CharField(max_length=8, choices=Section.choices)
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    due_date = models.DateField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0, db_default=0)
    task = models.OneToOneField("crm.Task", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="people_item")
    #: An offboarding's revoke item: the access it takes back.
    access_entry = models.ForeignKey("AccessEntry", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="revoke_items")
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    waived_at = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    waive_note = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "people_checklist_item"
        constraints = [
            models.CheckConstraint(condition=Q(waived_at__isnull=True) | ~Q(waive_note=""),
                                   name="people_checklist_item_waived_with_a_note"),
        ]


# ------------------------------------------------------------ the access list

class AccessEntry(TenantScopedModel):
    """Something a person was given: a system, an email account, a phone
    number, a piece of equipment or a key; when, and by whom."""

    class Kind(models.TextChoices):
        SYSTEM = "system", "System"
        EMAIL = "email", "Email account"
        PHONE = "phone", "Phone number"
        EQUIPMENT = "equipment", "Equipment"
        KEY = "key", "Key"

    person = models.ForeignKey(PersonRecord, on_delete=models.CASCADE, related_name="access")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=200)
    detail = models.CharField(max_length=300, blank=True, default="", db_default="")
    given_on = models.DateField(null=True, blank=True)
    given_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    #: By whom, in words, when it was someone without a sign-in.
    given_by_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "people_access_entry"


# ------------------------------------------------------------ documents

class PersonDocument(TenantScopedModel):
    """A document on a person's record: uploaded, or sent for signature
    (`esign_document`, which keeps it out of the Documents list for anyone
    without HR Director, and out of AI apps). Never Social Security numbers,
    bank details, I-9s, medical or leave paperwork, background checks or
    benefits."""

    class Kind(models.TextChoices):
        OFFER_LETTER = "offer_letter", "Offer letter"
        HANDBOOK = "handbook", "Handbook acknowledgment"
        REVIEW = "review", "Review"
        EXIT_INTERVIEW = "exit_interview", "Exit interview"
        OTHER = "other", "Other"

    person = models.ForeignKey(PersonRecord, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    title = models.CharField(max_length=160)
    stored_file = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    esign_document = models.ForeignKey("esign.Document", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="people_files")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "people_document"


class _WriteOnce(TenantQuerySet):
    """Refuses to change or delete any row it holds; one that holds none (the
    rows of another practice, say) changes nothing, as any query would."""

    def update(self, **kwargs):
        if self.exists():
            raise PermissionError("The access log can't be changed.")
        return 0

    def delete(self):
        if self.exists():
            raise PermissionError("The access log can't be deleted.")
        return 0, {}


class _LogManager(TenantManager.from_queryset(_WriteOnce)):
    pass


class _AllLogManager(AllTenantsManager.from_queryset(_WriteOnce)):
    pass


class PeopleAccessLog(TenantScopedModel):
    """One view, change or export of a person's sensitive data. Written
    once; nobody can edit or delete it (`_WriteOnce`, and `save` refuses a
    row already written)."""

    class Action(models.TextChoices):
        VIEW = "view", "Viewed"
        CHANGE = "change", "Changed"
        EXPORT = "export", "Exported"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                              related_name="+")
    actor_name = models.CharField(max_length=200)
    person = models.ForeignKey(PersonRecord, on_delete=models.PROTECT, related_name="access_log")
    person_name = models.CharField(max_length=200)
    #: Whose scope it is read in: the company, or none for the practice.
    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=8, choices=Action.choices)
    fields = models.JSONField(default=list)
    #: From where: the address and the browser.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="", db_default="")

    objects = _LogManager()
    all_objects = _AllLogManager()

    class Meta(TenantScopedModel.Meta):
        db_table = "people_access_log"
        indexes = [models.Index(fields=["tenant", "client_company", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("The access log can't be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("The access log can't be deleted.")
