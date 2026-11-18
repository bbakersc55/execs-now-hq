from django.urls import path

from apps.people import views

S = "people/<str:scope>/"

urlpatterns = [
    path("people/", views.PeopleHome.as_view(), name="people-home"),
    path(S, views.PeopleScope.as_view(), name="people-scope"),
    path(S + "records/", views.PeopleRecords.as_view(), name="people-records"),
    path(S + "records/<str:pk>/", views.PeopleRecord.as_view(), name="people-record"),
    path(S + "records/<str:pk>/offer/", views.PeopleSend.as_view(what="offer"),
         name="people-offer"),
    path(S + "records/<str:pk>/handbook/", views.PeopleSend.as_view(what="handbook"),
         name="people-handbook"),
    path(S + "records/<str:pk>/checklists/", views.PeopleChecklistStart.as_view(),
         name="people-checklist-start"),
    path(S + "records/<str:pk>/access/", views.PeopleAccessEntries.as_view(),
         name="people-access-entries"),
    path(S + "records/<str:pk>/documents/", views.PeopleDocuments.as_view(),
         name="people-documents"),
    path(S + "documents/<str:pk>/", views.PeopleDocumentFile.as_view(),
         name="people-document-file"),
    path(S + "access/<str:pk>/", views.PeopleAccessEntry.as_view(), name="people-access-entry"),
    path(S + "items/<str:pk>/<str:act>/", views.PeopleItem.as_view(), name="people-item"),
    path(S + "checklists/<str:pk>/close/", views.PeopleChecklistClose.as_view(),
         name="people-checklist-close"),
    path(S + "setup/", views.PeopleSetup.as_view(), name="people-setup"),
    path(S + "setup/<str:what>/", views.PeopleSetup.as_view(), name="people-setup-new"),
    path(S + "setup/<str:what>/<str:pk>/", views.PeopleSetup.as_view(),
         name="people-setup-one"),
    path(S + "export/", views.PeopleExport.as_view(), name="people-export"),
    path(S + "permissions/", views.PeoplePermissions.as_view(), name="people-permissions"),
    path(S + "permissions/<str:pk>/revoke/", views.PeoplePermissionRevoke.as_view(),
         name="people-permission-revoke"),
    path(S + "access-log/", views.PeopleAccessLogView.as_view(), name="people-access-log"),
]
