"""The worksheet engine (P12, docs/p12_tools.md).

A **tool** is a definition: sections of fields, tables with typed columns,
computed fields and result cards, with formulas in the small language of
`apps.tools.formula`. The four Operations tools ship in code
(`apps.tools.shipped`); a practice's own tools, made with the builder or
duplicated from a shipped one, are `Tool` rows and never reach another
practice.

A **run** is a saved, named, dated copy of a tool for one company (or the
practice's own row). It keeps a **snapshot** of the definition it was made
from, so a later edit to the tool never changes an old run.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class Tool(TenantScopedModel):
    """A practice's own tool."""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="", db_default="")
    definition = models.JSONField(default=dict)
    #: The shipped tool it was duplicated from, if it was.
    source_key = models.CharField(max_length=40, blank=True, default="", db_default="")
    #: Proposed by Claude in the builder, then saved by a person.
    from_ai = models.BooleanField(default=False, db_default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_tool"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ToolRun(TenantScopedModel):
    """One run of a tool for one company: its values, and the definition as it
    was when the run was made."""

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE,
                                related_name="tool_runs")
    #: A practice's tool, or none for a shipped one (`tool_key`).
    tool = models.ForeignKey(Tool, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="runs")
    tool_key = models.CharField(max_length=40, blank=True, default="", db_default="")
    tool_name = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    run_date = models.DateField()
    definition = models.JSONField(default=dict)
    values = models.JSONField(default=dict, blank=True)
    #: Shown read-only in the portal to the client owner and senior leadership.
    shared_with_client = models.BooleanField(default=False, db_default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "tool_run"
        ordering = ["-run_date", "-created_at"]
        indexes = [models.Index(fields=["company", "run_date"], name="tool_run_by_company")]

    def __str__(self):
        return self.name
