from rest_framework.routers import DefaultRouter

from apps.esign import views

router = DefaultRouter(trailing_slash=True)
router.register("document-templates", views.DocumentTemplateViewSet, basename="document-template")
router.register("documents", views.DocumentViewSet, basename="document")
router.register("portal-documents", views.PortalDocumentViewSet, basename="portal-document")

urlpatterns = router.urls
