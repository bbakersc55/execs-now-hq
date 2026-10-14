from django.apps import AppConfig


class WorkConfig(AppConfig):
    name = "apps.work"
    label = "work"
    verbose_name = "Task engine"

    def ready(self):
        from apps.work import signals  # noqa: F401  (registers the receiver)
