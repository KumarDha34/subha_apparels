"""
Central permission classes, shared by every app.
Keeping role-checks in one place avoids drift between modules.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and
                     (request.user.is_superuser or request.user.role == "ADMIN"))


class HasRole(BasePermission):
    """
    Usage: add `required_roles = ["ADMIN", "STORE_MANAGER"]` on the view/viewset.
    Admins and superusers always pass.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser or request.user.role == "ADMIN":
            return True
        required_roles = getattr(view, "required_roles", None)
        if not required_roles:
            return True
        return request.user.role in required_roles


class ReadOnlyOrHasRole(HasRole):
    """
    Anyone authenticated can read (GET/HEAD/OPTIONS); writes require the role check.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return super().has_permission(request, view)
