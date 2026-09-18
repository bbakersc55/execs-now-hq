from rest_framework.routers import DefaultRouter

from apps.strategy import views

router = DefaultRouter()
router.register("strategy-sessions", views.SessionViewSet, basename="strategy-session")
router.register("strategy-map-rows", views.MapRowViewSet, basename="strategy-map-row")
router.register("strategy-templates", views.TemplateViewSet, basename="strategy-template")

urlpatterns = router.urls
