from django.urls import path, re_path

from . import oauth, views

# Served at the root of the app's host (config/urls.py): the authorization
# server's metadata and endpoints (RFC 8414 puts the metadata at the root).
oauth_patterns = [
    re_path(r"^\.well-known/oauth-authorization-server/?$", oauth.metadata,
            name="oauth-metadata"),
    re_path(r"^oauth/register/?$", oauth.register, name="oauth-register"),
    re_path(r"^oauth/authorize/?$", oauth.authorize, name="oauth-authorize"),
    re_path(r"^oauth/token/?$", oauth.token, name="oauth-token"),
    re_path(r"^oauth/revoke/?$", oauth.revoke, name="oauth-revoke"),
]

# Under /api/.
urlpatterns = [
    path("ai/connections/", views.MyConnections.as_view(), name="ai-connections"),
    path("ai/connections/<uuid:pk>/revoke", views.RevokeConnection.as_view(),
         name="ai-connection-revoke"),
    path("ai/apps/", views.PracticeApps.as_view(), name="ai-apps"),
    path("ai/actions/", views.Actions.as_view(), name="ai-actions"),
    path("platform/model-tiers", views.ModelTiers.as_view(), name="platform-model-tiers"),
]
