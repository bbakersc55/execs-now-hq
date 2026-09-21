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
# FR-3.38's on-demand progress report is **gone, not shadowed** (FR-4B.5,
# AC-4B.23). It answered "what happened lately", which is the wrong question;
# the client value report answers whether the work is working.
router.register("client-activity", views.ClientActivityView, basename="client-activity")
# Was "portal-activity", the client's own log (FR-3.41). The owner reversed that
# on 2026-09-16: the feed is the practice's, and a client role is refused.
router.register("activity", views.ActivityView, basename="activity")
router.register("portal-access", views.PortalAccessViewSet, basename="portal-access")
router.register("portal-people", views.AssignablePeopleView, basename="portal-people")

# --- Module 4B — the client value report ---
router.register("value-report", views.ValueReportViewSet, basename="value-report")
router.register("goal-measurements", views.GoalMeasurementViewSet,
                basename="goal-measurement")
router.register("goal-milestones", views.GoalMilestoneViewSet,
                basename="goal-milestone")
router.register("goal-resolutions", views.GoalResolutionViewSet,
                basename="goal-resolution")
router.register("value-report-exports", views.GoalReportExportViewSet,
                basename="value-report-export")

urlpatterns = router.urls
