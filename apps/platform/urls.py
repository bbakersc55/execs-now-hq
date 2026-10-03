from django.urls import path, re_path

from apps.platform import views

urlpatterns = [
    path("platform/area", views.AreaView.as_view(), name="platform-area"),
    path("platform/practices", views.PracticesView.as_view(), name="platform-practices"),
    path("platform/practices/<uuid:pk>", views.PracticeView.as_view(), name="platform-practice"),
    re_path(r"^platform/practices/(?P<pk>[0-9a-f-]{36})/(?P<action>archive|unarchive)$",
            views.PracticeView.as_view(), name="platform-practice-action"),
]
