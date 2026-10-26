from django.urls import path

from apps.notify import views

urlpatterns = [
    path("notify/notices/", views.NoticesView.as_view(), name="notify-notices"),
    path("notify/notices/read/", views.ReadView.as_view(), name="notify-read"),
    path("notify/push/", views.PushView.as_view(), name="notify-push"),
    path("notify/push/subscribe/", views.SubscribeView.as_view(), name="notify-subscribe"),
    path("notify/push/unsubscribe/", views.UnsubscribeView.as_view(),
         name="notify-unsubscribe"),
]
