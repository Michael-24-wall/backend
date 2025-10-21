from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import *
from .serializers import *
from django.utils import timezone
from django.db.models import Q, Count

class IsRoomMember(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'room'):
            return RoomMembership.objects.filter(
                room=obj.room, 
                user=request.user, 
                is_banned=False
            ).exists()
        return RoomMembership.objects.filter(
            room=obj, 
            user=request.user, 
            is_banned=False
        ).exists()

class IsMessageOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

class ChatRoomViewSet(viewsets.ModelViewSet):
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title', 'member_count']
    
    def get_queryset(self):
        user_rooms = ChatRoom.objects.filter(
            Q(roommembership__user=self.request.user, roommembership__is_banned=False) |
            Q(created_by=self.request.user)
        ).distinct().annotate(
            member_count=Count('roommembership', filter=Q(roommembership__is_banned=False))
        )
        return user_rooms
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        room = self.get_object()
        if room.is_private:
            return Response({'error': 'This room is private'}, status=status.HTTP_403_FORBIDDEN)
        
        membership, created = RoomMembership.objects.get_or_create(
            room=room,
            user=request.user,
            defaults={'role': 'member'}
        )
        
        if created:
            return Response({'status': 'joined room'}, status=status.HTTP_201_CREATED)
        return Response({'status': 'already member'}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        room = self.get_object()
        try:
            membership = RoomMembership.objects.get(room=room, user=request.user)
            if membership.role == 'admin' and room.created_by != request.user:
                return Response({'error': 'Admins cannot leave rooms they did not create'}, 
                              status=status.HTTP_403_FORBIDDEN)
            membership.delete()
            return Response({'status': 'left room'})
        except RoomMembership.DoesNotExist:
            return Response({'error': 'Not a member of this room'}, 
                          status=status.HTTP_400_BAD_REQUEST)

class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated, IsRoomMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['room', 'user', 'message_type']
    ordering_fields = ['timestamp', 'id']
    ordering = ['-timestamp']
    
    def get_queryset(self):
        return Message.objects.filter(
            room__roommembership__user=self.request.user,
            room__roommembership__is_banned=False,
            is_deleted=False
        ).select_related('user', 'reply_to', 'room').prefetch_related('read_receipts')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateMessageSerializer
        elif self.action == 'update':
            return UpdateMessageSerializer
        return MessageSerializer
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        message = self.get_object()
        MessageReadReceipt.objects.get_or_create(
            message=message,
            user=request.user
        )
        return Response({'status': 'message marked as read'})
    
    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        message = self.get_object()
        reaction = request.data.get('reaction')
        # Implement reaction logic
        return Response({'status': 'reaction added'})

class RoomMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = RoomMembershipSerializer
    permission_classes = [permissions.IsAuthenticated, IsRoomMember]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['room', 'user', 'role', 'is_banned']
    
    def get_queryset(self):
        return RoomMembership.objects.filter(
            room__roommembership__user=self.request.user,
            room__roommembership__is_banned=False
        ).select_related('user', 'room')
    
    @action(detail=True, methods=['post'])
    def ban(self, request, pk=None):
        membership = self.get_object()
        if not self.has_admin_permission(request.user, membership.room):
            return Response({'error': 'Insufficient permissions'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        membership.is_banned = True
        membership.save()
        return Response({'status': 'user banned'})
    
    def has_admin_permission(self, user, room):
        try:
            membership = RoomMembership.objects.get(room=room, user=user)
            return membership.role in ['admin', 'moderator']
        except RoomMembership.DoesNotExist:
            return False

class UserProfileViewSet(viewsets.ModelViewSet):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return UserProfile.objects.filter(user=self.request.user)
    
    def get_object(self):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile
    
    @action(detail=False, methods=['get'])
    def online_users(self, request):
        online_profiles = UserProfile.objects.filter(is_online=True)
        serializer = self.get_serializer(online_profiles, many=True)
        return Response(serializer.data)

# API Views for specific endpoints
class ChatStatisticsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        user = request.user
        stats = {
            'total_rooms': ChatRoom.objects.filter(
                roommembership__user=user, 
                roommembership__is_banned=False
            ).count(),
            'total_messages': Message.objects.filter(user=user).count(),
            'unread_messages': Message.objects.filter(
                room__roommembership__user=user,
                room__roommembership__is_banned=False
            ).exclude(
                read_receipts__user=user
            ).count(),
        }
        return Response(stats)

class SearchMessagesAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        query = request.GET.get('q', '')
        room_id = request.GET.get('room_id')
        
        messages = Message.objects.filter(
            room__roommembership__user=request.user,
            room__roommembership__is_banned=False,
            content__icontains=query,
            is_deleted=False
        )
        
        if room_id:
            messages = messages.filter(room_id=room_id)
        
        serializer = MessageSerializer(messages[:50], many=True)
        return Response(serializer.data)

# SIMPLE API VIEWS FOR URLS.PY
class ChatRoomListAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        rooms = ChatRoom.objects.filter(
            Q(roommembership__user=request.user, roommembership__is_banned=False) |
            Q(created_by=request.user)
        ).distinct()
        serializer = ChatRoomSerializer(rooms, many=True, context={'request': request})
        return Response(serializer.data)

class MessageHistoryAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, room_name):
        try:
            room = ChatRoom.objects.get(name=room_name)
            # Check if user has access to this room
            if not RoomMembership.objects.filter(room=room, user=request.user, is_banned=False).exists():
                return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
            
            messages = Message.objects.filter(
                room=room,
                is_deleted=False
            ).select_related('user').order_by('timestamp')[:50]
            
            serializer = MessageSerializer(messages, many=True)
            return Response({
                'room': room_name,
                'messages': serializer.data
            })
        except ChatRoom.DoesNotExist:
            return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)

class UserProfileAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile)
        return Response(serializer.data)

class FileUploadAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        return Response({'error': 'File upload not implemented yet'}, status=status.HTTP_501_NOT_IMPLEMENTED)