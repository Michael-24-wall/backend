from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from django_filters.rest_framework import DjangoFilterBackend

# Ensure the User model reference is available (supports custom user models)
from django.contrib.auth import get_user_model
User = get_user_model()
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Q, Count, F, Subquery, OuterRef, Prefetch
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.db import transaction, DatabaseError
from django.core.files.base import ContentFile
import logging
from datetime import timedelta, datetime
import json
from django.core.files.storage import default_storage

from .models import *
from .serializers import *
from . import serializers as chat_serializers
from .serializers import RoomMembershipSerializer, UserProfileSerializer
from .permissions import IsRoomMember, IsRoomAdmin

# Provide a fallback alias in case a module-local MessageRateThrottle isn't defined.
from rest_framework.throttling import UserRateThrottle, ScopedRateThrottle

try:
    # Prefer explicit imports from the filters module if available
    from .filters import ChatRoomFilter, MessageFilter
except Exception:
    # Provide lightweight fallbacks so the views module can import without error.
    import django_filters

    class ChatRoomFilter(django_filters.FilterSet):
        class Meta:
            model = ChatRoom
            fields = ['title', 'name', 'privacy_level']

    class MessageFilter(django_filters.FilterSet):
        class Meta:
            model = Message
            fields = ['message_type', 'user', 'timestamp']

try:
    from .throttles import *
except ImportError:
    pass

logger = logging.getLogger(__name__)

class IsRoomMemberOrPublic(permissions.BasePermission):
    """
    Permission allowing access to public rooms or to room members.
    """
    def has_permission(self, request, view):
        # Allow listing and creating rooms for authenticated users
        # For detail actions, object-level permission will be checked.
        if view.action in ['list', 'create', None]:
            return request.user and request.user.is_authenticated
        return True

    def has_object_permission(self, request, view, obj):
        # obj is expected to be a ChatRoom instance; allow access if room is public
        if getattr(obj, 'privacy_level', None) == 'public':
            return True
        # allow if the requesting user created the room
        if getattr(obj, 'created_by_id', None) == getattr(request.user, 'id', None):
            return True
        # allow if user is a non-banned member of the room
        return RoomMembership.objects.filter(room=obj, user=request.user, is_banned=False).exists()

class ChatRoomViewSet(viewsets.ModelViewSet):
    """
    Complete Chat Room Management API
    """
    permission_classes = [permissions.IsAuthenticated, IsRoomMemberOrPublic]
    throttle_classes = [UserRateThrottle]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ChatRoomFilter
    search_fields = ['title', 'description', 'name']
    ordering_fields = ['last_activity', 'created_at', 'member_count']
    ordering = ['-last_activity']
    
    def get_serializer_class(self):
        # Safely retrieve serializer classes from the serializers module; fall back to the default ChatRoomSerializer
        if self.action == 'create':
            return getattr(chat_serializers, 'CreateChatRoomSerializer', ChatRoomSerializer)
        elif self.action in ['update', 'partial_update']:
            return getattr(chat_serializers, 'UpdateChatRoomSerializer', ChatRoomSerializer)
        return getattr(chat_serializers, 'ChatRoomSerializer', ChatRoomSerializer)
    
    def get_queryset(self):
        """FIXED: Simple queryset without problematic annotations"""
        user = self.request.user
        
        # Simple base query - remove all complex annotations that were causing the error
        base_qs = ChatRoom.objects.filter(
            Q(privacy_level='public') |
            Q(roommembership__user=user, roommembership__is_banned=False) |
            Q(created_by=user)
        ).distinct()
        
        # FIX: Remove ALL Subquery annotations that were causing "Cannot use None as query value"
        # Just use simple count annotations
        base_qs = base_qs.annotate(
            member_count=Count('roommembership', filter=Q(roommembership__is_banned=False))
        )
        
        return base_qs.select_related('created_by').prefetch_related(
            Prefetch('roommembership_set', 
                    queryset=RoomMembership.objects.filter(is_banned=False),
                    to_attr='active_members')
        )
    
    @transaction.atomic
    def perform_create(self, serializer):
        """Create room and auto-join as owner"""
        room = serializer.save(created_by=self.request.user)
        
        # Auto-join as owner
        RoomMembership.objects.create(
            room=room,
            user=self.request.user,
            role='owner'
        )
        
        logger.info(f"Room created: {room.name} by {self.request.user.email}")
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def join(self, request, pk=None):
        """
        Join a chat room
        ---
        Join a public or private room. For private rooms, requires invitation.
        """
        room = self.get_object()
        user = request.user
        
        try:
            with transaction.atomic():
                if not room.can_join(user):
                    return Response(
                        {'error': 'Cannot join this room'}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                existing_membership = RoomMembership.objects.filter(room=room, user=user).first()
                if existing_membership:
                    if existing_membership.is_banned_currently():
                        return Response(
                            {'error': 'You are banned from this room'}, 
                            status=status.HTTP_403_FORBIDDEN
                        )
                    existing_membership.is_banned = False
                    existing_membership.banned_until = None
                    existing_membership.save()
                    return Response({'status': 'rejoined room'})
                
                current_members = RoomMembership.objects.filter(room=room, is_banned=False).count()
                if current_members >= room.max_members:
                    return Response(
                        {'error': 'Room is at maximum capacity'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                role = 'member'
                if room.require_approval:
                    role = 'pending'
                
                membership = RoomMembership.objects.create(
                    room=room,
                    user=user,
                    role=role
                )
                
                if not room.require_approval:
                    Message.objects.create(
                        room=room,
                        user=user,
                        content=f"{user.get_full_name()} joined the room",
                        message_type='system'
                    )
                
                return Response({
                    'status': 'joined room' if not room.require_approval else 'pending approval',
                    'role': membership.role
                }, status=status.HTTP_201_CREATED)
                
        except DatabaseError as e:
            logger.error(f"Database error joining room: {e}")
            return Response(
                {'error': 'Unable to join room at this time'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsRoomMember])
    def leave(self, request, pk=None):
        """Leave a chat room"""
        room = self.get_object()
        user = request.user
        
        try:
            membership = RoomMembership.objects.get(room=room, user=user)
            
            if membership.role == 'owner':
                return Response(
                    {'error': 'Room owners must transfer ownership before leaving'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            membership.delete()
            
            Message.objects.create(
                room=room,
                user=user,
                content=f"{user.get_full_name()} left the room",
                message_type='system'
            )
            
            return Response({'status': 'left room'})
            
        except RoomMembership.DoesNotExist:
            return Response(
                {'error': 'Not a member of this room'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated, IsRoomMember])
    def members(self, request, pk=None):
        """Get room members with pagination and filtering"""
        room = self.get_object()
        
        members = RoomMembership.objects.filter(
            room=room, 
            is_banned=False
        ).select_related('user', 'user__chat_profile').order_by('-role', 'joined_at')
        
        # Filter by role if provided
        role_filter = request.query_params.get('role')
        if role_filter:
            members = members.filter(role=role_filter)
        
        page = self.paginate_queryset(members)
        if page is not None:
            serializer = RoomMembershipSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = RoomMembershipSerializer(members, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated, IsRoomMember])
    def messages(self, request, pk=None):
        """Get room messages with advanced filtering OR create new message"""
        room = self.get_object()
        
        if request.method == 'POST':
            # Handle message creation
            return self.create_message(request, room)
        
        # Original GET logic for listing messages
        messages = Message.objects.filter(
            room=room,
            is_deleted=False
        ).select_related('user', 'reply_to').prefetch_related('reactions', 'read_receipts')
        
        # Apply filters
        message_type = request.query_params.get('message_type')
        if message_type:
            messages = messages.filter(message_type=message_type)
        
        user_id = request.query_params.get('user_id')
        if user_id:
            messages = messages.filter(user_id=user_id)
        
        date_from = request.query_params.get('date_from')
        if date_from:
            messages = messages.filter(timestamp__date__gte=date_from)
        
        date_to = request.query_params.get('date_to')
        if date_to:
            messages = messages.filter(timestamp__date__lte=date_to)
        
        # Pagination
        page = self.paginate_queryset(messages.order_by('-timestamp'))
        if page is not None:
            serializer = MessageSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = MessageSerializer(messages.order_by('-timestamp')[:50], many=True, context={'request': request})
        return Response(serializer.data)
    
    def create_message(self, request, room):
        """Create a new message in the room"""
        # Add room to request data
        data = request.data.copy()
        data['room'] = room.id
        
        serializer = CreateMessageSerializer(data=data, context={'request': request})
        
        if serializer.is_valid():
            try:
                with transaction.atomic():
                    message = serializer.save(
                        user=request.user,
                        room=room,
                        ip_address=self.get_client_ip(request)
                    )
                    
                    # Update room last activity
                    room.last_activity = timezone.now()
                    room.save()
                    
                    logger.info(f"Message created by {request.user.email} in room {room.name}")
                    
                    # Return the created message
                    response_serializer = MessageSerializer(message, context={'request': request})
                    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
                    
            except Exception as e:
                logger.error(f"Error creating message: {e}")
                return Response(
                    {'error': 'Failed to create message'}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsRoomAdmin])
    def transfer_ownership(self, request, pk=None):
        """Transfer room ownership to another member"""
        room = self.get_object()
        new_owner_id = request.data.get('new_owner_id')
        
        if not new_owner_id:
            return Response(
                {'error': 'new_owner_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                current_owner_membership = RoomMembership.objects.get(
                    room=room, 
                    user=request.user, 
                    role='owner'
                )
                
                new_owner_membership = RoomMembership.objects.get(
                    room=room, 
                    user_id=new_owner_id,
                    is_banned=False
                )
                
                current_owner_membership.role = 'admin'
                current_owner_membership.save()
                
                new_owner_membership.role = 'owner'
                new_owner_membership.save()
                
                room.created_by_id = new_owner_id
                room.save()
                
                Message.objects.create(
                    room=room,
                    user=request.user,
                    content=f"Room ownership transferred to {new_owner_membership.user.get_full_name()}",
                    message_type='system'
                )
                
                return Response({'status': 'ownership transferred'})
                
        except RoomMembership.DoesNotExist:
            return Response(
                {'error': 'Invalid new owner or permissions'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated, IsRoomMember])
    def statistics(self, request, pk=None):
        """Get room statistics"""
        room = self.get_object()
        
        stats = {
            'total_messages': room.messages.count(),
            'total_members': room.roommembership_set.filter(is_banned=False).count(),
            'active_members': room.roommembership_set.filter(
                is_banned=False,
                user__chat_profile__online=True
            ).count(),
            'messages_today': room.messages.filter(
                timestamp__date=timezone.now().date()
            ).count(),
            'most_active_user': self.get_most_active_user(room),
            'message_types': self.get_message_type_breakdown(room),
        }
        
        return Response(stats)
    
    def get_most_active_user(self, room):
        """Get most active user in room"""
        from django.db.models import Count
        result = room.messages.values('user__email').annotate(
            count=Count('id')
        ).order_by('-count').first()
        
        if result:
            return {
                'email': result['user__email'],
                'message_count': result['count']
            }
        return None
    
    def get_message_type_breakdown(self, room):
        """Get message type breakdown"""
        from django.db.models import Count
        breakdown = room.messages.values('message_type').annotate(
            count=Count('id')
        )
        return {item['message_type']: item['count'] for item in breakdown}

class MessageViewSet(viewsets.ModelViewSet):
    """
    Complete Message Management API
    """
    permission_classes = [permissions.IsAuthenticated, IsRoomMember]
    throttle_classes = [MessageRateThrottle]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = MessageFilter
    ordering_fields = ['timestamp', 'id']
    ordering = ['-timestamp']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateMessageSerializer
        elif self.action in ['update', 'partial_update']:
            return UpdateMessageSerializer
        return MessageSerializer
    
    def get_queryset(self):
        """Highly optimized message queryset"""
        return Message.objects.filter(
            room__roommembership__user=self.request.user,
            room__roommembership__is_banned=False,
            is_deleted=False
        ).select_related(
            'user', 'user__chat_profile', 'reply_to', 'reply_to__user', 'room'
        ).prefetch_related(
            'read_receipts', 'reactions', 'edit_history'
        ).only(
            'id', 'room_id', 'user_id', 'content', 'message_type',
            'file_url', 'file_name', 'file_size', 'file_type',
            'reply_to_id', 'is_edited', 'edited_at', 'is_deleted',
            'timestamp', 'user__username', 'user__email', 'user__first_name', 'user__last_name'
        )
    
    @transaction.atomic
    def perform_create(self, serializer):
        """Create message with validation"""
        message = serializer.save(
            user=self.request.user,
            ip_address=self.get_client_ip()
        )
        
        # Update room last activity
        message.room.last_activity = timezone.now()
        message.room.save()
        
        logger.info(f"Message created by {self.request.user.email} in room {message.room.name}")
    
    def get_client_ip(self):
        """Get client IP address"""
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip
    
    def destroy(self, request, *args, **kwargs):
        """Standard DELETE method for message deletion"""
        try:
            message = self.get_object()
            
            can_delete = (
                message.user == request.user or 
                self.has_mod_permission(request.user, message.room)
            )
            
            if not can_delete:
                return Response(
                    {'error': 'Insufficient permissions to delete this message'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if already deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Message is already deleted'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                deleted_by = request.user if message.user != request.user else None
                message.soft_delete(deleted_by)
                
                logger.info(f"Message {message.id} deleted by {request.user.email}")
            
            return Response({'status': 'message deleted'})
            
        except Exception as e:
            logger.error(f"Error in destroy method: {str(e)}")
            return Response(
                {'error': f'Failed to delete message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """Update message with validation"""
        instance = self.get_object()
        
        if not (instance.user == request.user or self.has_mod_permission(request.user, instance.room)):
            return Response(
                {'error': 'You can only edit your own messages'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        if instance.is_deleted:
            return Response(
                {'error': 'Cannot edit a deleted message'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 15-minute edit window
        if (timezone.now() - instance.timestamp).total_seconds() > 900:
            return Response(
                {'error': 'Message is too old to edit'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='delete')
    def delete(self, request, pk=None):
        """Soft delete message via POST"""
        try:
            message = self.get_object()
            
            can_delete = (
                message.user == request.user or 
                self.has_mod_permission(request.user, message.room)
            )
            
            if not can_delete:
                return Response(
                    {'error': 'Insufficient permissions to delete this message'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if already deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Message is already deleted'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                deleted_by = request.user if message.user != request.user else None
                message.soft_delete(deleted_by)
                
                logger.info(f"Message {message.id} deleted by {request.user.email}")
            
            return Response({'status': 'message deleted'})
            
        except Exception as e:
            logger.error(f"Error in delete action: {str(e)}")
            return Response(
                {'error': f'Failed to delete message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def edit(self, request, pk=None):
        """Edit message content"""
        try:
            message = self.get_object()
            new_content = request.data.get('content')
            
            if not new_content:
                return Response(
                    {'error': 'Content is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check permissions
            if not (message.user == request.user or self.has_mod_permission(request.user, message.room)):
                return Response(
                    {'error': 'You can only edit your own messages'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if message is deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Cannot edit a deleted message'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 15-minute edit window (you can adjust this)
            if (timezone.now() - message.timestamp).total_seconds() > 900:
                return Response(
                    {'error': 'Message is too old to edit'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                message.edit_message(new_content)
                
                logger.info(f"Message {message.id} edited by {request.user.email}")
            
            # Return updated message
            serializer = MessageSerializer(message, context={'request': request})
            return Response({
                'status': 'message edited',
                'message': serializer.data
            })
            
        except Exception as e:
            logger.error(f"Error in edit action: {str(e)}")
            return Response(
                {'error': f'Failed to edit message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        """Mark message as read"""
        message = self.get_object()
        
        receipt, created = MessageReadReceipt.objects.get_or_create(
            message=message,
            user=request.user
        )
        
        # Clear unread count cache
        cache_key = f"unread_{message.room_id}_{request.user.id}"
        cache.delete(cache_key)
        
        return Response({
            'status': 'message marked as read',
            'read_at': receipt.read_at
        })
    
    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """Add reaction to message"""
        message = self.get_object()
        reaction_type = request.data.get('reaction_type')
        
        if not reaction_type:
            return Response(
                {'error': 'reaction_type is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        valid_reactions = dict(Reaction.REACTION_TYPES)
        if reaction_type not in valid_reactions:
            return Response(
                {'error': f'Invalid reaction type. Valid types: {list(valid_reactions.keys())}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Remove existing reaction if exists
            Reaction.objects.filter(
                message=message,
                user=request.user
            ).delete()
            
            # Add new reaction
            reaction = Reaction.objects.create(
                message=message,
                user=request.user,
                reaction_type=reaction_type
            )
        
        return Response({
            'status': 'reaction added',
            'reaction_type': reaction_type,
            'reaction_emoji': valid_reactions[reaction_type]
        })
    
    @action(detail=True, methods=['delete'], url_path='react')
    def remove_reaction(self, request, pk=None):
        """Remove reaction from message"""
        message = self.get_object()
        reaction_type = request.data.get('reaction_type')
        
        if not reaction_type:
            return Response(
                {'error': 'reaction_type is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = Reaction.objects.filter(
            message=message,
            user=request.user,
            reaction_type=reaction_type
        ).delete()
        
        if deleted_count > 0:
            return Response({'status': 'reaction removed'})
        else:
            return Response(
                {'error': 'Reaction not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'])
    def readers(self, request, pk=None):
        """Get users who have read this message"""
        message = self.get_object()
        readers = message.read_receipts.select_related('user').order_by('-read_at')
        
        serializer = MessageReadReceiptSerializer(readers, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def reactions(self, request, pk=None):
        """Get all reactions for this message"""
        message = self.get_object()
        reactions = message.reactions.select_related('user')
        
        # Group by reaction type
        reaction_summary = {}
        for reaction in reactions:
            if reaction.reaction_type not in reaction_summary:
                reaction_summary[reaction.reaction_type] = {
                    'count': 0,
                    'users': [],
                    'emoji': dict(Reaction.REACTION_TYPES).get(reaction.reaction_type, '')
                }
            reaction_summary[reaction.reaction_type]['count'] += 1
            reaction_summary[reaction.reaction_type]['users'].append({
                'id': reaction.user.id,
                'username': reaction.user.username,
                'display_name': reaction.user.get_full_name()
            })
        
        return Response(reaction_summary)
    
    def has_mod_permission(self, user, room):
        """Check if user has moderation permissions"""
        try:
            membership = RoomMembership.objects.get(room=room, user=user)
            return membership.role in ['owner', 'admin', 'moderator']
        except RoomMembership.DoesNotExist:
            return False

class RoomMembershipViewSet(viewsets.ModelViewSet):
    """
    Room Membership Management API
    """
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
        """Ban user from room"""
        membership = self.get_object()
        
        if not self.has_admin_permission(request.user, membership.room):
            return Response(
                {'error': 'Insufficient permissions'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Cannot ban room owner
        if membership.role == 'owner':
            return Response(
                {'error': 'Cannot ban room owner'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        duration_days = request.data.get('duration_days', 7)
        reason = request.data.get('reason', '')
        
        membership.is_banned = True
        membership.banned_until = timezone.now() + timedelta(days=duration_days)
        membership.save()
        
        # Log ban
        BanHistory.objects.create(
            user=membership.user,
            room=membership.room,
            banned_by=request.user,
            reason=reason,
            banned_until=membership.banned_until
        )
        
        Message.objects.create(
            room=membership.room,
            user=request.user,
            content=f"{membership.user.get_full_name()} was banned from the room",
            message_type='system'
        )
        
        return Response({
            'status': 'user banned',
            'banned_until': membership.banned_until,
            'duration_days': duration_days
        })
    
    @action(detail=True, methods=['post'])
    def unban(self, request, pk=None):
        """Unban user from room"""
        membership = self.get_object()
        
        if not self.has_admin_permission(request.user, membership.room):
            return Response(
                {'error': 'Insufficient permissions'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        membership.is_banned = False
        membership.banned_until = None
        membership.save()
        
        Message.objects.create(
            room=membership.room,
            user=request.user,
            content=f"{membership.user.get_full_name()} was unbanned from the room",
            message_type='system'
        )
        
        return Response({'status': 'user unbanned'})
    
    @action(detail=True, methods=['post'])
    def promote(self, request, pk=None):
        """Promote user to higher role"""
        membership = self.get_object()
        new_role = request.data.get('role')
        
        if not new_role or new_role not in ['moderator', 'admin']:
            return Response(
                {'error': 'Valid role (moderator or admin) is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not self.has_admin_permission(request.user, membership.room):
            return Response(
                {'error': 'Insufficient permissions'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        membership.role = new_role
        membership.save()
        
        return Response({
            'status': 'user promoted',
            'new_role': new_role
        })
    
    @action(detail=True, methods=['post'])
    def demote(self, request, pk=None):
        """Demote user to member role"""
        membership = self.get_object()
        
        if not self.has_admin_permission(request.user, membership.room):
            return Response(
                {'error': 'Insufficient permissions'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Cannot demote owner
        if membership.role == 'owner':
            return Response(
                {'error': 'Cannot demote room owner'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        membership.role = 'member'
        membership.save()
        
        return Response({'status': 'user demoted to member'})
    
    def has_admin_permission(self, user, room):
        try:
            membership = RoomMembership.objects.get(room=room, user=user)
            return membership.role in ['owner', 'admin']
        except RoomMembership.DoesNotExist:
            return False

class UserProfileViewSet(viewsets.ModelViewSet):
    """
    User Profile Management API
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return UserProfile.objects.filter(user=self.request.user)
    
    def get_object(self):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile
    
    @action(detail=False, methods=['get'])
    def online_users(self, request):
        """Get all online users"""
        online_profiles = UserProfile.objects.filter(
            online=True,
            show_online_status=True
        ).select_related('user')
        
        serializer = UserProfileSerializer(online_profiles, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def set_status(self, request):
        """Set user status"""
        profile = self.get_object()
        status_text = request.data.get('status', '')
        
        profile.status = status_text[:100]  # Limit to 100 chars
        profile.save()
        
        return Response({
            'status': 'status updated',
            'new_status': profile.status
        })
    
    @action(detail=False, methods=['post'])
    def set_theme(self, request):
        """Set user theme preference"""
        profile = self.get_object()
        theme = request.data.get('theme', 'light')
        
        if theme not in ['light', 'dark', 'auto']:
            return Response(
                {'error': 'Theme must be light, dark, or auto'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        profile.theme = theme
        profile.save()
        
        return Response({
            'status': 'theme updated',
            'new_theme': profile.theme
        })
    
    @action(detail=False, methods=['post'])
    def update_notifications(self, request):
        """Update notification preferences"""
        profile = self.get_object()
        
        profile.message_notifications = request.data.get(
            'message_notifications', 
            profile.message_notifications
        )
        profile.sound_notifications = request.data.get(
            'sound_notifications', 
            profile.sound_notifications
        )
        profile.email_notifications = request.data.get(
            'email_notifications', 
            profile.email_notifications
        )
        profile.save()
        
        return Response({
            'status': 'notifications updated',
            'message_notifications': profile.message_notifications,
            'sound_notifications': profile.sound_notifications,
            'email_notifications': profile.email_notifications
        })

# Additional API Views
class ChatStatisticsAPI(APIView):
    """
    Global Chat Statistics API
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        user = request.user
        time_range = request.GET.get('time_range', '7d')
        
        # Calculate time delta
        if time_range == '7d':
            delta = timedelta(days=7)
        elif time_range == '30d':
            delta = timedelta(days=30)
        else:
            delta = timedelta(days=90)
        
        start_date = timezone.now() - delta
        
        stats = {
            'user_statistics': self.get_user_statistics(user, start_date),
            'room_statistics': self.get_room_statistics(user),
            'activity_statistics': self.get_activity_statistics(user, start_date),
            'time_range': time_range,
            'period': {
                'start_date': start_date,
                'end_date': timezone.now()
            }
        }
        
        return Response(stats)
    
    def get_user_statistics(self, user, start_date):
        """Get user-specific statistics"""
        return {
            'total_rooms': RoomMembership.objects.filter(
                user=user, 
                is_banned=False
            ).count(),
            'total_messages': Message.objects.filter(
                user=user,
                timestamp__gte=start_date
            ).count(),
            'unread_messages': Message.objects.filter(
                room__roommembership__user=user,
                room__roommembership__is_banned=False,
                timestamp__gte=start_date
            ).exclude(
                read_receipts__user=user
            ).count(),
            'messages_today': Message.objects.filter(
                user=user,
                timestamp__date=timezone.now().date()
            ).count(),
        }
    
    def get_room_statistics(self, user):
        """Get room statistics for user"""
        user_rooms = ChatRoom.objects.filter(
            roommembership__user=user,
            roommembership__is_banned=False
        )
        
        return {
            'total_rooms': user_rooms.count(),
            'public_rooms': user_rooms.filter(privacy_level='public').count(),
            'private_rooms': user_rooms.filter(privacy_level='private').count(),
            'rooms_created': user_rooms.filter(created_by=user).count(),
        }
    
    def get_activity_statistics(self, user, start_date):
        """Get user activity statistics"""
        from django.db.models import Count
        from django.db.models.functions import TruncDate
        
        daily_activity = Message.objects.filter(
            user=user,
            timestamp__gte=start_date
        ).annotate(
            date=TruncDate('timestamp')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        return {
            'daily_activity': list(daily_activity),
            'most_active_room': self.get_most_active_room(user, start_date),
        }
    
    def get_most_active_room(self, user, start_date):
        """Get user's most active room"""
        from django.db.models import Count
        
        room_activity = Message.objects.filter(
            user=user,
            timestamp__gte=start_date
        ).values('room__title').annotate(
            message_count=Count('id')
        ).order_by('-message_count').first()
        
        return room_activity

class MessageSearchAPI(APIView):
    """
    Advanced Message Search API
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def get(self, request):
        query = request.GET.get('q', '').strip()
        room_id = request.GET.get('room_id')
        message_type = request.GET.get('message_type')
        user_id = request.GET.get('user_id')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        include_files = request.GET.get('include_files', 'true').lower() == 'true'
        
        if not query:
            return Response(
                {'error': 'Search query is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Base queryset - user's accessible messages
        messages = Message.objects.filter(
            room__roommembership__user=request.user,
            room__roommembership__is_banned=False,
            is_deleted=False
        )
        
        # Apply filters
        if room_id:
            messages = messages.filter(room_id=room_id)
        
        if message_type:
            messages = messages.filter(message_type=message_type)
        
        if user_id:
            messages = messages.filter(user_id=user_id)
        
        if date_from:
            messages = messages.filter(timestamp__date__gte=date_from)
        
        if date_to:
            messages = messages.filter(timestamp__date__lte=date_to)
        
        if not include_files:
            messages = messages.exclude(message_type='file')
        
        # Search in content and file names
        messages = messages.filter(
            Q(content__icontains=query) |
            Q(file_name__icontains=query)
        )
        
        # Optimize queryset
        messages = messages.select_related(
            'user', 'room', 'reply_to'
        ).only(
            'id', 'content', 'message_type', 'file_name', 'timestamp',
            'user__first_name', 'user__last_name', 'room__name', 'room__title'
        ).order_by('-timestamp')[:100]
        
        serializer = MessageSerializer(messages, many=True, context={'request': request})
        
        return Response({
            'query': query,
            'results_count': len(messages),
            'results': serializer.data
        })

class FileUploadAPI(APIView):
    """
    File Upload API for Chat
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [UserRateThrottle]
    
    def post(self, request):
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        uploaded_file = request.FILES['file']
        room_id = request.data.get('room_id')
        description = request.data.get('description', '')
        
        # Validate file size (10MB limit)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response(
                {'error': 'File size exceeds 10MB limit'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file types
        allowed_types = [
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
            'application/pdf', 
            'text/plain', 'text/csv',
            'application/msword', 
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/zip', 'application/x-zip-compressed'
        ]
        
        if uploaded_file.content_type not in allowed_types:
            return Response(
                {'error': f'File type {uploaded_file.content_type} not allowed'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                # Check if room exists and user has access
                if room_id:
                    room = ChatRoom.objects.get(id=room_id)
                    if not RoomMembership.objects.filter(room=room, user=request.user, is_banned=False).exists():
                        return Response(
                            {'error': 'Access denied to this room'}, 
                            status=status.HTTP_403_FORBIDDEN
                        )
                
                # Generate unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"chat_files/{timestamp}_{request.user.id}_{uploaded_file.name}"
                
                # Save file to storage (in production, use AWS S3 or similar)
                saved_path = default_storage.save(filename, ContentFile(uploaded_file.read()))
                file_url = default_storage.url(saved_path)
                
                # If room_id provided, create a message with file attachment
                if room_id:
                    message = Message.objects.create(
                        room=room,
                        user=request.user,
                        content=description or f"Shared file: {uploaded_file.name}",
                        message_type='file',
                        file_url=file_url,
                        file_name=uploaded_file.name,
                        file_size=uploaded_file.size,
                        file_type=uploaded_file.content_type
                    )
                    
                    serializer = MessageSerializer(message, context={'request': request})
                    
                    return Response({
                        'detail': 'File uploaded and shared successfully',
                        'message': serializer.data,
                        'file_info': {
                            'url': file_url,
                            'name': uploaded_file.name,
                            'size': uploaded_file.size,
                            'type': uploaded_file.content_type
                        }
                    }, status=status.HTTP_201_CREATED)
                else:
                    # Just upload file without sharing to room
                    return Response({
                        'detail': 'File uploaded successfully',
                        'file_info': {
                            'url': file_url,
                            'name': uploaded_file.name,
                            'size': uploaded_file.size,
                            'type': uploaded_file.content_type
                        }
                    }, status=status.HTTP_201_CREATED)
                    
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Room not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return Response(
                {'error': f'File upload failed: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserPresenceAPI(APIView):
    """
    User Presence Management API
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Update user online status"""
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        
        online_status = request.data.get('online')
        if online_status is not None:
            profile.online = online_status
            profile.last_seen = timezone.now()
            profile.save()
        
        return Response({
            'status': 'presence updated',
            'online': profile.online,
            'last_seen': profile.last_seen
        })
    
    def get(self, request):
        """Get user presence information"""
        user_id = request.GET.get('user_id')
        
        if user_id:
            # Get specific user's presence
            try:
                profile = UserProfile.objects.get(user_id=user_id)
                if not profile.show_online_status:
                    return Response({
                        'online': None,
                        'privacy': 'hidden'
                    })
                
                return Response({
                    'online': profile.online,
                    'last_seen': profile.last_seen,
                    'status': profile.status
                })
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Get current user's presence
            profile, created = UserProfile.objects.get_or_create(user=request.user)
            return Response({
                'online': profile.online,
                'last_seen': profile.last_seen,
                'status': profile.status,
                'theme': profile.theme
            })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def user_suggestions(request):
    """
    User search/suggestions for mentions
    """
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return Response([])
    
    # Search in user fields
    users = User.objects.filter(
        Q(username__icontains=query) |
        Q(email__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    ).exclude(id=request.user.id)[:10]
    
    suggestions = []
    for user in users:
        suggestions.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'display_name': user.get_full_name() or user.username,
            'avatar': user.chat_profile.avatar.url if hasattr(user, 'chat_profile') and user.chat_profile.avatar else None
        })
    
    return Response(suggestions)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def room_suggestions(request):
    """
    Room search/suggestions for quick access
    """
    query = request.GET.get('q', '').strip()
    
    rooms = ChatRoom.objects.filter(
        Q(roommembership__user=request.user, roommembership__is_banned=False) |
        Q(created_by=request.user)
    ).filter(
        Q(title__icontains=query) |
        Q(name__icontains=query) |
        Q(description__icontains=query)
    ).distinct().annotate(
        member_count=Count('roommembership', filter=Q(roommembership__is_banned=False))
    )[:10]
    
    serializer = ChatRoomSerializer(rooms, many=True, context={'request': request})
    return Response(serializer.data)
class MessageViewSet(viewsets.ModelViewSet):
    """
    Complete Message Management API - FIXED VERSION
    """
    permission_classes = [permissions.IsAuthenticated, IsRoomMember]
    throttle_classes = [MessageRateThrottle]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = MessageFilter
    ordering_fields = ['timestamp', 'id']
    ordering = ['-timestamp']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateMessageSerializer
        elif self.action in ['update', 'partial_update']:
            return UpdateMessageSerializer
        return MessageSerializer
    
    def get_queryset(self):
        """Highly optimized message queryset"""
        return Message.objects.filter(
            room__roommembership__user=self.request.user,
            room__roommembership__is_banned=False,
            is_deleted=False
        ).select_related(
            'user', 'user__chat_profile', 'reply_to', 'reply_to__user', 'room'
        ).prefetch_related(
            'read_receipts', 'reactions', 'edit_history'
        ).only(
            'id', 'room_id', 'user_id', 'content', 'message_type',
            'file_url', 'file_name', 'file_size', 'file_type',
            'reply_to_id', 'is_edited', 'edited_at', 'is_deleted',
            'timestamp', 'user__username', 'user__email', 'user__first_name', 'user__last_name'
        )

    def create(self, request, *args, **kwargs):
        """Override create to handle errors properly"""
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            # Check if user can post in this room
            room_id = request.data.get('room')
            if room_id:
                try:
                    room = ChatRoom.objects.get(id=room_id)
                    # Check if user is a member of the room
                    if not RoomMembership.objects.filter(room=room, user=request.user, is_banned=False).exists():
                        return Response(
                            {'error': 'You are not a member of this room'}, 
                            status=status.HTTP_403_FORBIDDEN
                        )
                except ChatRoom.DoesNotExist:
                    return Response(
                        {'error': 'Room not found'}, 
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
            
        except Exception as e:
            logger.error(f"Error in message creation: {str(e)}")
            return Response(
                {'error': f'Failed to create message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def perform_create(self, serializer):
        """Create message with validation - FIXED VERSION"""
        try:
            # Get room from validated data
            validated_data = serializer.validated_data
            room = validated_data.get('room')
            
            # Create message
            message = serializer.save(
                user=self.request.user,
                ip_address=self.get_client_ip()
            )
            
            # Update room last activity
            room.last_activity = timezone.now()
            room.save()
            
            logger.info(f"Message created by {self.request.user.email} in room {room.name}")
            
        except Exception as e:
            logger.error(f"Error in perform_create: {str(e)}")
            raise e
    
    def get_client_ip(self):
        """Get client IP address"""
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip
    
    def destroy(self, request, *args, **kwargs):
        """Standard DELETE method for message deletion"""
        try:
            message = self.get_object()
            
            can_delete = (
                message.user == request.user or 
                self.has_mod_permission(request.user, message.room)
            )
            
            if not can_delete:
                return Response(
                    {'error': 'Insufficient permissions to delete this message'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if already deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Message is already deleted'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                deleted_by = request.user if message.user != request.user else None
                message.soft_delete(deleted_by)
                
                logger.info(f"Message {message.id} deleted by {request.user.email}")
            
            return Response({'status': 'message deleted'})
            
        except Exception as e:
            logger.error(f"Error in destroy method: {str(e)}")
            return Response(
                {'error': f'Failed to delete message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """Update message with validation"""
        instance = self.get_object()
        
        if not (instance.user == request.user or self.has_mod_permission(request.user, instance.room)):
            return Response(
                {'error': 'You can only edit your own messages'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        if instance.is_deleted:
            return Response(
                {'error': 'Cannot edit a deleted message'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 15-minute edit window
        if (timezone.now() - instance.timestamp).total_seconds() > 900:
            return Response(
                {'error': 'Message is too old to edit'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='delete')
    def delete(self, request, pk=None):
        """Soft delete message via POST"""
        try:
            message = self.get_object()
            
            can_delete = (
                message.user == request.user or 
                self.has_mod_permission(request.user, message.room)
            )
            
            if not can_delete:
                return Response(
                    {'error': 'Insufficient permissions to delete this message'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if already deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Message is already deleted'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                deleted_by = request.user if message.user != request.user else None
                message.soft_delete(deleted_by)
                
                logger.info(f"Message {message.id} deleted by {request.user.email}")
            
            return Response({'status': 'message deleted'})
            
        except Exception as e:
            logger.error(f"Error in delete action: {str(e)}")
            return Response(
                {'error': f'Failed to delete message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def edit(self, request, pk=None):
        """Edit message content"""
        try:
            message = self.get_object()
            new_content = request.data.get('content')
            
            if not new_content:
                return Response(
                    {'error': 'Content is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check permissions
            if not (message.user == request.user or self.has_mod_permission(request.user, message.room)):
                return Response(
                    {'error': 'You can only edit your own messages'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if message is deleted
            if message.is_deleted:
                return Response(
                    {'error': 'Cannot edit a deleted message'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 15-minute edit window (you can adjust this)
            if (timezone.now() - message.timestamp).total_seconds() > 900:
                return Response(
                    {'error': 'Message is too old to edit'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                message.edit_message(new_content)
                
                logger.info(f"Message {message.id} edited by {request.user.email}")
            
            # Return updated message
            serializer = MessageSerializer(message, context={'request': request})
            return Response({
                'status': 'message edited',
                'message': serializer.data
            })
            
        except Exception as e:
            logger.error(f"Error in edit action: {str(e)}")
            return Response(
                {'error': f'Failed to edit message: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        """Mark message as read"""
        message = self.get_object()
        
        receipt, created = MessageReadReceipt.objects.get_or_create(
            message=message,
            user=request.user
        )
        
        # Clear unread count cache
        cache_key = f"unread_{message.room_id}_{request.user.id}"
        cache.delete(cache_key)
        
        return Response({
            'status': 'message marked as read',
            'read_at': receipt.read_at
        })
    
    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """Add reaction to message"""
        message = self.get_object()
        reaction_type = request.data.get('reaction_type')
        
        if not reaction_type:
            return Response(
                {'error': 'reaction_type is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        valid_reactions = dict(Reaction.REACTION_TYPES)
        if reaction_type not in valid_reactions:
            return Response(
                {'error': f'Invalid reaction type. Valid types: {list(valid_reactions.keys())}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Remove existing reaction if exists
            Reaction.objects.filter(
                message=message,
                user=request.user
            ).delete()
            
            # Add new reaction
            reaction = Reaction.objects.create(
                message=message,
                user=request.user,
                reaction_type=reaction_type
            )
        
        return Response({
            'status': 'reaction added',
            'reaction_type': reaction_type,
            'reaction_emoji': valid_reactions[reaction_type]
        })
    
    @action(detail=True, methods=['delete'], url_path='react')
    def remove_reaction(self, request, pk=None):
        """Remove reaction from message"""
        message = self.get_object()
        reaction_type = request.data.get('reaction_type')
        
        if not reaction_type:
            return Response(
                {'error': 'reaction_type is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = Reaction.objects.filter(
            message=message,
            user=request.user,
            reaction_type=reaction_type
        ).delete()
        
        if deleted_count > 0:
            return Response({'status': 'reaction removed'})
        else:
            return Response(
                {'error': 'Reaction not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'])
    def readers(self, request, pk=None):
        """Get users who have read this message"""
        message = self.get_object()
        readers = message.read_receipts.select_related('user').order_by('-read_at')
        
        serializer = MessageReadReceiptSerializer(readers, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def reactions(self, request, pk=None):
        """Get all reactions for this message"""
        message = self.get_object()
        reactions = message.reactions.select_related('user')
        
        # Group by reaction type
        reaction_summary = {}
        for reaction in reactions:
            if reaction.reaction_type not in reaction_summary:
                reaction_summary[reaction.reaction_type] = {
                    'count': 0,
                    'users': [],
                    'emoji': dict(Reaction.REACTION_TYPES).get(reaction.reaction_type, '')
                }
            reaction_summary[reaction.reaction_type]['count'] += 1
            reaction_summary[reaction.reaction_type]['users'].append({
                'id': reaction.user.id,
                'username': reaction.user.username,
                'display_name': reaction.user.get_full_name()
            })
        
        return Response(reaction_summary)
    
    def has_mod_permission(self, user, room):
        """Check if user has moderation permissions"""
        try:
            membership = RoomMembership.objects.get(room=room, user=user)
            return membership.role in ['owner', 'admin', 'moderator']
        except RoomMembership.DoesNotExist:
            return False