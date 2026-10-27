from rest_framework.routers import DefaultRouter

from apps.calendars import views

router = DefaultRouter()
router.register("calendar", views.CalendarViewSet, basename="calendar")

urlpatterns = router.urls
