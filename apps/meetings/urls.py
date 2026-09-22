from rest_framework.routers import DefaultRouter

from apps.meetings import views

router = DefaultRouter()
router.register("drive-watch", views.DriveWatchViewSet, basename="drive-watch")
router.register("meeting-proposals", views.ProposalViewSet, basename="meeting-proposal")
router.register("proposal-items", views.ProposalItemViewSet, basename="proposal-item")

urlpatterns = router.urls
