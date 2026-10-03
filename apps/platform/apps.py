from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform"
    label = "platform"

    def ready(self):
        from apps.platform import signals  # noqa: F401  (registers the receiver)
