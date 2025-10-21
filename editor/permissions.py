# editor/permissions.py
from rest_framework import permissions
from django.core.exceptions import PermissionDenied

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner
        return obj.owner == request.user

class IsInOrganization(permissions.BasePermission):
    """
    Permission to only allow users in the same organization.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and hasattr(request.user, 'organization')

    def has_object_permission(self, request, view, obj):
        if hasattr(request.user, 'organization') and hasattr(obj, 'organization'):
            return request.user.organization == obj.organization
        return False

class CanEditSpreadsheet(permissions.BasePermission):
    """
    Permission to check if user can edit the spreadsheet.
    """
    def has_object_permission(self, request, view, obj):
        return obj.can_edit(request.user)

class HasDashboardAccess(permissions.BasePermission):
    """
    Permission to access dashboard features.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated