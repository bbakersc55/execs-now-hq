from rest_framework.routers import DefaultRouter

from apps.strategy import views

router = DefaultRouter()
router.register("strategy-sessions", views.SessionViewSet, basename="strategy-session")
router.register("strategy-map-rows", views.MapRowViewSet, basename="strategy-map-row")
router.register("strategy-path-notes", views.PathNoteViewSet,
                basename="strategy-path-note")
router.register("strategy-prep-questions", views.PrepQuestionViewSet,
                basename="strategy-prep-question")
router.register("strategy-templates", views.TemplateViewSet, basename="strategy-template")

urlpatterns = router.urls
