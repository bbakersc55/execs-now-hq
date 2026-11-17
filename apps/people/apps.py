from django.apps import AppConfig


class PeopleConfig(AppConfig):
    """The People Command Center's security foundation (2026-11-17,
    `docs/p9_people_hris.md`): HR permissions by person, a placeholder
    person record with its sensitive fields encrypted, and the access log.
    The employee records themselves arrive in the next build."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.people"
    label = "people"
