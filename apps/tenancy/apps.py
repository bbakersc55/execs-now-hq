from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenancy"
    label = "tenancy"

    def ready(self):
        from apps.tenancy import acting  # noqa: F401  (registers the receivers)

        # Registers the startup check that `runserver` and `qcluster` run
        # before they begin. Importing it is what registers it.
        from config import checks  # noqa: F401
