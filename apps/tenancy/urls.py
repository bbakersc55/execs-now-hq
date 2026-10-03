from django.urls import path, re_path
from rest_framework.routers import DefaultRouter

from apps.tenancy import views, views_acting

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("ai-usage", views.AiUsageViewSet, basename="ai-usage")
router.register("ai-key", views.AnthropicKeyView, basename="ai-key")
router.register("ai-budget", views.AiBudgetView, basename="ai-budget")
router.register("ai-guard", views.AiGuardView, basename="ai-guard")
router.register("act-as", views_acting.ActAsViewSet, basename="act-as")

urlpatterns = router.urls + [
    path("settings/branding", views.BrandingSettingsView.as_view(), name="branding-settings"),
    path("settings/branding/reset", views.BrandingResetView.as_view(), name="branding-reset"),
    re_path(r"^settings/branding/(?P<kind>logo|mark)$", views.BrandingImageView.as_view(),
            name="branding-image"),
]
