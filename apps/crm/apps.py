from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crm"
    label = "crm"

    def ready(self):
        from apps.crm import signals  # noqa: F401  (registers the receivers)
