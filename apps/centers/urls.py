from django.urls import path

from apps.centers import views

urlpatterns = [
    path("command-centers/", views.CentersView.as_view(), name="command-centers"),
    path("command-centers/library/", views.LibraryView.as_view(),
         name="command-centers-library"),
    path("command-centers/library/export/", views.LibraryExportView.as_view(),
         name="command-centers-library-export"),
    path("command-centers/<str:code>/", views.CenterView.as_view(), name="command-center"),
    path("playbooks/", views.PlaybooksView.as_view(), name="playbooks"),
    path("playbooks/copy/", views.PlaybookCopyView.as_view(), name="playbooks-copy"),
    path("playbooks/start/", views.PlaybookStartView.as_view(), name="playbooks-start"),
    path("playbooks/<uuid:pk>/", views.PlaybookView.as_view(), name="playbook"),
]
