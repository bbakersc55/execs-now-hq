from django.urls import path

from apps.platform import views

urlpatterns = [
    path("platform/area", views.AreaView.as_view(), name="platform-area"),
]
