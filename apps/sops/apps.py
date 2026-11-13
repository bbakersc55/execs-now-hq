from django.apps import AppConfig


class SopsConfig(AppConfig):
    """The SOP studio (P10, 2026-11-13; docs/p10_sop_studio.md): a company's
    standard operating procedures, published in numbered versions to an
    audience who acknowledge them; brainstorms with Claude that propose the
    record, its process map, a checklist and its measures; and the Notebook
    pack. Available while any Command Center is on."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sops"
    label = "sops"
