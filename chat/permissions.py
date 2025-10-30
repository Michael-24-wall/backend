from rest_framework import permissions
from django.utils import timezone

class IsRoomMember(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        from .models import RoomMembership
        if hasattr(obj, 'room'):
            room = obj.room
        else:
            room = obj
        
        return RoomMembership.objects.filter(
            room=room, 
            user=request.user, 
            is_banned=False
        ).exists()

class IsRoomMemberOrPublic(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        from .models import RoomMembership
        # Public rooms can be viewed by anyone
        if obj.privacy_level == 'public' and request.method in permissions.SAFE_METHODS:
            return True
        
        return RoomMembership.objects.filter(
            room=obj, 
            user=request.user, 
            is_banned=False
        ).exists()

class IsRoomAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        from .models import RoomMembership
        try:
            membership = RoomMembership.objects.get(room=obj, user=request.user)
            return membership.role in ['owner', 'admin']
        except RoomMembership.DoesNotExist:
            return False

class IsMessageOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

class CanEditMessage(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        from .models import RoomMembership
        # Message owner can edit within time limit
        if obj.user == request.user:
            # Allow editing within 15 minutes
            return (timezone.now() - obj.timestamp).total_seconds() <= 900
        
        # Moderators can edit any message
        try:
            membership = RoomMembership.objects.get(room=obj.room, user=request.user)
            return membership.role in ['owner', 'admin', 'moderator']
        except RoomMembership.DoesNotExist:
            return False