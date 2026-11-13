from django.urls import path

from . import views

urlpatterns = [
    path("tools/", views.ToolsView.as_view(), name="tools"),
    path("tools/validate/", views.ValidateView.as_view(), name="tools-validate"),
    path("tools/evaluate/", views.EvaluateView.as_view(), name="tools-evaluate"),
    path("tools/builder/", views.BuilderView.as_view(), name="tools-builder"),
    path("tools/<str:ref>/", views.ToolView.as_view(), name="tool"),
    path("tools/<str:ref>/duplicate/", views.ToolDuplicateView.as_view(), name="tool-duplicate"),
    path("tools/<str:ref>/archive/", views.ToolArchiveView.as_view(), name="tool-archive"),
    path("tool-runs/", views.RunsView.as_view(), name="tool-runs"),
    path("tool-runs/<str:pk>/", views.RunView.as_view(), name="tool-run"),
    path("tool-runs/<str:pk>/files/<str:kind>/", views.RunFileView.as_view(),
         name="tool-run-files"),
    path("tool-runs/<str:pk>/<str:action>/", views.RunActionView.as_view(),
         name="tool-run-action"),
]
