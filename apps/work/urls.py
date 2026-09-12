from rest_framework.routers import DefaultRouter

from django.urls import path

from apps.work import views, views_cadence

router = DefaultRouter()
router.register("goals", views.GoalViewSet, basename="goal")
router.register("projects", views.ProjectViewSet, basename="project")
# Module 3 owns /api/tasks/ now; Phase 1's read-only stand-in in apps.crm is gone.
router.register("tasks", views.TaskViewSet, basename="task")
router.register("checklist-items", views.ChecklistItemViewSet, basename="checklist-item")
router.register("comments", views.CommentViewSet, basename="comment")
router.register("stakeholders", views.StakeholderViewSet, basename="stakeholder")
router.register("digests", views.DigestViewSet, basename="digest")
router.register("progress-report", views.ProgressReportView, basename="progress-report")
router.register("client-activity", views.ClientActivityView, basename="client-activity")
router.register("portal-access", views.PortalAccessViewSet, basename="portal-access")
router.register("portal-people", views.AssignablePeopleView, basename="portal-people")

urlpatterns = router.urls
