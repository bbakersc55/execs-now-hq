from rest_framework.routers import DefaultRouter

from apps.tenancy import views, views_acting

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("ai-usage", views.AiUsageViewSet, basename="ai-usage")
router.register("ai-key", views.AnthropicKeyView, basename="ai-key")
router.register("ai-budget", views.AiBudgetView, basename="ai-budget")
router.register("act-as", views_acting.ActAsViewSet, basename="act-as")

urlpatterns = router.urls
