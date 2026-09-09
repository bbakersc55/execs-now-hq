from rest_framework.routers import DefaultRouter

from apps.tenancy import views

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("ai-usage", views.AiUsageViewSet, basename="ai-usage")

urlpatterns = router.urls
