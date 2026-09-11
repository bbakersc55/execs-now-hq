from rest_framework.routers import DefaultRouter

from apps.tenancy import views

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("ai-usage", views.AiUsageViewSet, basename="ai-usage")
router.register("ai-key", views.AnthropicKeyView, basename="ai-key")

urlpatterns = router.urls
