from django.urls import path, re_path

from apps.platform import views

urlpatterns = [
    path("platform/area", views.AreaView.as_view(), name="platform-area"),
    path("platform/practices", views.PracticesView.as_view(), name="platform-practices"),
    path("platform/practices/<uuid:pk>", views.PracticeView.as_view(), name="platform-practice"),
    path("platform/practices/<uuid:pk>/invite", views.InviteView.as_view(),
         name="platform-practice-invite"),
    path("agreement", views.AgreementView.as_view(), name="agreement"),
    path("feedback/", views.FeedbackView.as_view(), name="feedback"),
    path("platform/feedback", views.PlatformFeedbackView.as_view(), name="platform-feedback"),
    path("platform/feedback/<uuid:pk>", views.PlatformFeedbackView.as_view(),
         name="platform-feedback-item"),
    re_path(r"^platform/practices/(?P<pk>[0-9a-f-]{36})/(?P<action>archive|unarchive)$",
            views.PracticeView.as_view(), name="platform-practice-action"),
]
