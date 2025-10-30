from rest_framework.throttling import UserRateThrottle

class MessageRateThrottle(UserRateThrottle):
    scope = 'message'
    
    def allow_request(self, request, view):
        # Allow unlimited messages for moderators
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Check if user is moderator in any room
            from .models import RoomMembership
            is_moderator = RoomMembership.objects.filter(
                user=request.user,
                role__in=['owner', 'admin', 'moderator']
            ).exists()
            
            if is_moderator:
                return True
        
        return super().allow_request(request, view)

class FileUploadThrottle(UserRateThrottle):
    scope = 'file_upload'
    rate = '10/hour'

class RoomCreationThrottle(UserRateThrottle):
    scope = 'room_creation'
    rate = '5/day'