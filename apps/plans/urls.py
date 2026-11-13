from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlansView.as_view(), name="plans"),
    path("plans/from-session/", views.FromSessionView.as_view(), name="plans-from-session"),
    path("plans/<str:company>/", views.PlanView.as_view(), name="plan"),
    path("plans/<str:company>/week/", views.WeekView.as_view(), name="plan-week"),
    path("plans/<str:company>/close/", views.CloseView.as_view(), name="plan-close"),
    path("plans/<str:company>/sources/", views.SourcesView.as_view(), name="plan-sources"),
    path("plans/<str:company>/draft/", views.DraftView.as_view(), name="plan-draft"),
    path("plan-items/", views.ItemsView.as_view(), name="plan-items"),
    path("plan-items/<str:pk>/", views.ItemView.as_view(), name="plan-item"),
    path("plan-items/<str:pk>/accept/", views.AcceptView.as_view(), name="plan-item-accept"),
    path("plan-items/<str:pk>/discard/", views.DiscardView.as_view(),
         name="plan-item-discard"),
]
