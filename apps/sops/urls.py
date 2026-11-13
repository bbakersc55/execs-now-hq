from django.urls import path

from . import views

urlpatterns = [
    path("sops/", views.SopsView.as_view(), name="sops"),
    path("sops/map/", views.MapView.as_view(), name="sops-map"),
    path("sops/pack/", views.PackView.as_view(), name="sops-pack"),
    path("sops/pack/prompts/", views.PackPromptsView.as_view(), name="sops-pack-prompts"),
    path("sops/brainstorms/", views.BrainstormsView.as_view(), name="sop-brainstorms"),
    path("sops/brainstorms/<str:pk>/", views.BrainstormView.as_view(), name="sop-brainstorm"),
    path("sops/brainstorms/<str:pk>/act/<str:kind>/", views.BrainstormActionView.as_view(),
         {"action": "act"}, name="sop-brainstorm-act"),
    path("sops/brainstorms/<str:pk>/sources/<str:sid>/", views.BrainstormSourceView.as_view(),
         name="sop-brainstorm-source"),
    path("sops/brainstorms/<str:pk>/sources/<str:sid>/read/",
         views.BrainstormSourceView.as_view(), name="sop-brainstorm-source-read"),
    path("sops/brainstorms/<str:pk>/proposals/<str:pid>/<str:decision>/",
         views.ProposalView.as_view(), name="sop-brainstorm-proposal"),
    path("sops/brainstorms/<str:pk>/<str:action>/", views.BrainstormActionView.as_view(),
         name="sop-brainstorm-action"),
    path("sops/<str:pk>/", views.SopView.as_view(), name="sop"),
    path("sops/<str:pk>/comments/<str:cid>/resolve/", views.SopCommentView.as_view(),
         name="sop-comment-resolve"),
    path("sops/<str:pk>/attachments/", views.AttachmentsView.as_view(), name="sop-attachments"),
    path("sops/<str:pk>/attachments/<str:aid>/", views.AttachmentView.as_view(),
         name="sop-attachment"),
    path("sops/<str:pk>/files/<str:kind>/", views.SopFileView.as_view(), name="sop-files"),
    path("sops/<str:pk>/<str:action>/", views.SopActionView.as_view(), name="sop-action"),
    path("ai-media-key/", views.MediaKeyView.as_view(), name="ai-media-key"),
    path("ai-media-key/<str:action>/", views.MediaKeyView.as_view(), name="ai-media-key-action"),
]
