from rest_framework import permissions

# --- Assumption: User model has an 'organization' ForeignKey ---

class IsOrganizationMember(permissions.BasePermission):
    """
    Custom permission to only allow access to users who belong to the 
    same organization as the object (for detail views) or the organization 
    of the request user (for list/create views).
    
    This is the primary multi-tenancy gate.
    """

    def has_permission(self, request, view):
        """
        Allows access if the user is authenticated and has an organization linked.
        This prevents completely unlinked users from listing/creating.
        """
        # User must be authenticated and must have an organization linked
        return request.user and request.user.is_authenticated and request.user.organization is not None

    def has_object_permission(self, request, view, obj):
        """
        Allows access to the object only if the user's organization 
        matches the object's organization.
        """
        # Read permissions are allowed to any user in the organization.
        # Write permissions (PUT, PATCH, DELETE) are handled by a stronger permission (IsProjectManagerOrReadOnly).
        
        # Check if the user is in the same organization as the object
        return request.user.organization == obj.organization

# ----------------------------------------------------------------------
        
class IsProjectManagerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to allow:
    1. Read-only access (GET, HEAD, OPTIONS) to all authenticated organization members.
    2. Write access (POST, PUT, PATCH, DELETE) only to the project manager or a staff user.
    """

    def has_permission(self, request, view):
        # First, ensure they pass the basic organization membership check
        return IsOrganizationMember().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Read-only permissions are allowed for any request.
        if request.method in permissions.SAFE_METHODS:
            # Must still belong to the same organization (delegating to IsOrganizationMember)
            return IsOrganizationMember().has_object_permission(request, view, obj)

        # Write permissions are only allowed if:
        # 1. The user is a staff/superuser (global admin bypass).
        if user.is_staff or user.is_superuser:
            return True
        
        # 2. The user is the designated Project Manager for this specific project.
        if isinstance(obj, permissions.BasePermission): # Handles potential Project vs Task object difference gracefully
             # If obj is a Project, check if the user is the manager
             return obj.manager == user
        
        # 3. Handle Task objects: Task management is often allowed to the assigned user or the project manager.
        # For simplicity here, we'll check if the user is the project's manager.
        if hasattr(obj, 'project'):
            return obj.project.manager == user
            
        return False
    
    # core/permissions.py (Add this new class)

class IsOrganizationManager(permissions.BasePermission):
    """
    Custom permission to only allow access to users who are 'manager' 
    or 'owner' of their organization.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.organization:
            return False
        
        # Check if the user's primary role is either 'owner' or 'manager'
        return user.primary_role in ['owner', 'manager']