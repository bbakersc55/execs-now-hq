from rest_framework.routers import DefaultRouter

from apps.meetings import views, views_commitments

router = DefaultRouter()
router.register("drive-watch", views.DriveWatchViewSet, basename="drive-watch")
router.register("meetings", views.MeetingViewSet, basename="meeting")
router.register("meeting-proposals", views.ProposalViewSet, basename="meeting-proposal")
router.register("proposal-items", views.ProposalItemViewSet, basename="proposal-item")
router.register("commitments", views_commitments.CommitmentViewSet, basename="commitment")

urlpatterns = router.urls
