from django.urls import path

from apps.people import views

urlpatterns = [
    path("people/", views.PeopleHome.as_view(), name="people-home"),
    path("people/<str:scope>/", views.PeopleScope.as_view(), name="people-scope"),
    path("people/<str:scope>/records/", views.PeopleRecords.as_view(), name="people-records"),
    path("people/<str:scope>/records/<str:pk>/", views.PeopleRecord.as_view(),
         name="people-record"),
    path("people/<str:scope>/export/", views.PeopleExport.as_view(), name="people-export"),
    path("people/<str:scope>/permissions/", views.PeoplePermissions.as_view(),
         name="people-permissions"),
    path("people/<str:scope>/permissions/<str:pk>/revoke/",
         views.PeoplePermissionRevoke.as_view(), name="people-permission-revoke"),
    path("people/<str:scope>/access-log/", views.PeopleAccessLogView.as_view(),
         name="people-access-log"),
]
