from rest_framework.routers import DefaultRouter

from apps.notes import views

router = DefaultRouter()
router.register("notes", views.NoteViewSet, basename="note")

urlpatterns = router.urls
