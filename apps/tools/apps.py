from django.apps import AppConfig


class ToolsConfig(AppConfig):
    """The worksheet engine (P12, 2026-11-13; docs/p12_tools.md): tools as
    definitions of sections, fields, tables and formulas; runs for a company
    that keep a snapshot of the definition; the four Operations tools; and the
    tool builder. Available while any Command Center is on."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tools"
    label = "tools"
