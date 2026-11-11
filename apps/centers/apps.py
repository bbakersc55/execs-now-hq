from django.apps import AppConfig


class CentersConfig(AppConfig):
    """Command Centers (P8, 2026-11-10; docs/p8_command_centers.md): modules a
    practice turns on, one per discipline, each shipping session templates,
    KPI library entries, playbooks, document templates, recommended feeds
    and AI actions, copied into the practice on first use."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.centers"
    label = "centers"

    def ready(self):
        from apps.centers import recorder  # noqa: F401  (the practice library's signals)
