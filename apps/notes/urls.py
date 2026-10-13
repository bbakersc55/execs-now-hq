from rest_framework.routers import DefaultRouter

from apps.notes import views

router = DefaultRouter()
router.register("note-folders", views.NoteFolderViewSet, basename="note-folder")
router.register("notes", views.NoteViewSet, basename="note")

urlpatterns = router.urls
