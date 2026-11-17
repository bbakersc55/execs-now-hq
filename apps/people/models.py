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
DIRECTORY = ("name", "title", "team", "work_email", "manager")
#: The sensitive fields: an HR Director sees them; an HR Generalist masked.
SENSITIVE = ("pay_rate", "home_address", "date_of_birth", "personal_phone", "personal_email",
             "emergency_contact", "documents")
SENSITIVE_LABELS = {
    "pay_rate": "Pay rate", "home_address": "Home address", "date_of_birth": "Date of birth",
    "personal_phone": "Personal phone", "personal_email": "Personal email",
    "emergency_contact": "Emergency contact", "documents": "Documents",
}


class PersonRecord(TenantScopedModel):
    """A person, at a client company or (no company) the practice itself.
    A placeholder until the employee records arrive: the fields that prove
    who reaches what."""

    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="people")
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, blank=True, default="", db_default="")
    title = models.CharField(max_length=120, blank=True, default="", db_default="")
    team = models.CharField(max_length=120, blank=True, default="", db_default="")
    work_email = models.EmailField(blank=True, default="", db_default="")
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="reports")
    #: Their own sign-in, so they see their own record.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="person_records")
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
