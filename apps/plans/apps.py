from django.apps import AppConfig


class PlansConfig(AppConfig):
    """The plans engine (P11, 2026-11-13; docs/p11_plans_engine.md): one plan
    per company and one for the practice, in five horizons from the
    three-year picture to the week's sprint, linking the goals, projects,
    tasks and KPIs that already exist. Available while any Command Center is on."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.plans"
    label = "plans"
