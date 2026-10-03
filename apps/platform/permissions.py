from rest_framework.permissions import BasePermission

from apps.tenancy.middleware import AREA_PLATFORM


class IsPlatformOwnerInPracticesArea(BasePermission):
    """Practices endpoints: the platform owner, **and** switched to the
    Practices area. In the Executives Now area they are a practice owner like
    any other, and these endpoints refuse them too."""

    message = "This is for the platform owner, in the Practices area."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_owner
                    and getattr(request, "area", None) == AREA_PLATFORM)


class IsPlatformOwner(BasePermission):
    """Switching areas: the platform owner, from either area."""

    message = "This is for the platform owner."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_owner)
