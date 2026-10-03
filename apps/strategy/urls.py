from rest_framework.routers import DefaultRouter

from apps.strategy import views, views_builder

router = DefaultRouter()
router.register("strategy-sessions", views.SessionViewSet, basename="strategy-session")
router.register("strategy-map-rows", views.MapRowViewSet, basename="strategy-map-row")
router.register("strategy-diagnostic-proposals", views.DiagnosticProposalViewSet,
                basename="strategy-diagnostic-proposal")
router.register("strategy-path-notes", views.PathNoteViewSet,
                basename="strategy-path-note")
router.register("strategy-prep-questions", views.PrepQuestionViewSet,
                basename="strategy-prep-question")
router.register("strategy-templates", views.TemplateViewSet, basename="strategy-template")
router.register("strategy-template-builder", views_builder.TemplateBuilderViewSet,
                basename="strategy-template-builder")

urlpatterns = router.urls
