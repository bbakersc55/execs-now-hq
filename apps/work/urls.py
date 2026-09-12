from rest_framework.routers import DefaultRouter

from apps.work import views

router = DefaultRouter()
router.register("goals", views.GoalViewSet, basename="goal")
router.register("projects", views.ProjectViewSet, basename="project")
# Module 3 owns /api/tasks/ now; Phase 1's read-only stand-in in apps.crm is gone.
router.register("tasks", views.TaskViewSet, basename="task")
router.register("checklist-items", views.ChecklistItemViewSet, basename="checklist-item")
router.register("comments", views.CommentViewSet, basename="comment")

urlpatterns = router.urls
