from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import *
from .serializers import *
from django.utils import timezone
from django.db.models import Q, Count
import os
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from datetime import datetime

# Import for workflow integration
from workflow.models import ApprovalChatRoom

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
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title', 'member_count']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateChatRoomSerializer
        return ChatRoomSerializer
    
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
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
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
    permission_classes = [permissions.IsAuthenticated, IsRoomMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['room', 'user', 'message_type']
    ordering_fields = ['timestamp', 'id']
    ordering = ['-timestamp']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateMessageSerializer
        elif self.action == 'update':
            return UpdateMessageSerializer
        return MessageSerializer
    
    def get_queryset(self):
        return Message.objects.filter(
            room__roommembership__user=self.request.user,
            room__roommembership__is_banned=False,
            is_deleted=False
        ).select_related('user', 'reply_to', 'room').prefetch_related('read_receipts')
    
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
        # You can implement reaction logic here
        return Response({'status': 'reaction added'})
    
    @action(detail=False, methods=['post'], url_path='upload-file', parser_classes=[MultiPartParser, FormParser])
    def upload_file(self, request):
        """Upload and share file in a room"""
        if 'file' not in request.FILES:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = request.FILES['file']
        room_id = request.data.get('room')
        description = request.data.get('description', '')
        
        # Validate file size (10MB limit)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response({'error': 'File size exceeds 10MB limit'}, status=status.HTTP_400_BAD_REQUEST)
        
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
            return Response({'error': f'File type {uploaded_file.content_type} not allowed'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            room = ChatRoom.objects.get(id=room_id)
            
            # Check if user has access to the room
            if not RoomMembership.objects.filter(room=room, user=request.user, is_banned=False).exists():
                return Response({'error': 'Access denied to this room'}, status=status.HTTP_403_FORBIDDEN)
            
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_files/{timestamp}_{request.user.id}_{uploaded_file.name}"
            
            # Save file to storage
            saved_path = default_storage.save(filename, ContentFile(uploaded_file.read()))
            file_url = default_storage.url(saved_path)
            
            # Create message with file attachment
            message = Message.objects.create(
                room=room,
                user=request.user,
                content=description or f"Shared file: {uploaded_file.name}",
                message_type='file',
                file_url=file_url,
                file_name=uploaded_file.name,
                file_size=uploaded_file.size
            )
            
            serializer = MessageSerializer(message)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except ChatRoom.DoesNotExist:
            return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'File upload failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        online_profiles = UserProfile.objects.filter(online=True)
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
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        if 'file' not in request.FILES:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = request.FILES['file']
        room_id = request.data.get('room_id')
        description = request.data.get('description', '')
        
        # Validate file size (10MB limit)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response({'error': 'File size exceeds 10MB limit'}, status=status.HTTP_400_BAD_REQUEST)
        
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
            return Response({'error': f'File type {uploaded_file.content_type} not allowed'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Check if room exists and user has access
            if room_id:
                room = ChatRoom.objects.get(id=room_id)
                if not RoomMembership.objects.filter(room=room, user=request.user, is_banned=False).exists():
                    return Response({'error': 'Access denied to this room'}, status=status.HTTP_403_FORBIDDEN)
            
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = os.path.splitext(uploaded_file.name)[1]
            filename = f"chat_files/{timestamp}_{request.user.id}_{uploaded_file.name}"
            
            # Save file to storage
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
                    file_size=uploaded_file.size
                )
                
                return Response({
                    'detail': 'File uploaded and shared successfully',
                    'message_id': message.id,
                    'file_url': file_url,
                    'file_name': uploaded_file.name,
                    'file_size': uploaded_file.size,
                    'room_id': room_id
                }, status=status.HTTP_201_CREATED)
            else:
                # Just upload file without sharing to room
                return Response({
                    'detail': 'File uploaded successfully',
                    'file_url': file_url,
                    'file_name': uploaded_file.name,
                    'file_size': uploaded_file.size
                }, status=status.HTTP_201_CREATED)
                
        except ChatRoom.DoesNotExist:
            return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'File upload failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkflowChatViewSet(viewsets.GenericViewSet):
    """Special chat endpoints for workflow integration"""
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'], url_path='workflow-rooms')
    def workflow_rooms(self, request):
        """Get all chat rooms related to user's workflow documents"""
        try:
            # Rooms where user is involved in approval process
            approval_rooms = ChatRoom.objects.filter(
                Q(approvalchatroom__approval_flow__current_approver=request.user) |
                Q(approvalchatroom__approval_flow__document__created_by=request.user) |
                Q(roommembership__user=request.user, name__startswith='approval-')
            ).distinct()
            
            serializer = ChatRoomSerializer(approval_rooms, many=True, context={'request': request})
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': f'Error fetching workflow rooms: {str(e)}'}, 
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='workflow-quick-action')
    def workflow_quick_action(self, request):
        """Take workflow action directly from chat"""
        message_id = request.data.get('message_id')
        action = request.data.get('action')  # 'approve', 'reject', 'request_changes'
        comments = request.data.get('comments', '')
        
        try:
            message = Message.objects.get(id=message_id)
            chat_room = message.room
            
            # Find related approval flow
            approval_room = ApprovalChatRoom.objects.get(chat_room=chat_room)
            flow = approval_room.approval_flow
            
            # Verify user can take action
            if flow.current_approver != request.user:
                return Response({'error': 'Not authorized to take action on this document'}, 
                              status=status.HTTP_403_FORBIDDEN)
            
            # Process the action
            if action == 'approve':
                decision_key = 'approve'
                action_message = "approved"
            elif action == 'reject':
                decision_key = 'reject' 
                action_message = "rejected"
            elif action == 'request_changes':
                decision_key = 'request_changes'
                action_message = "requested changes for"
            else:
                return Response({'error': 'Invalid action'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Note: In a full implementation, you would call the actual workflow processing methods
            # from workflow.views.WorkflowActionViewSet here
            
            # Send confirmation message to chat
            Message.objects.create(
                room=chat_room,
                user=request.user,
                content=f"✅ {action_message.title()} the document. {comments}",
                message_type='system'
            )
            
            return Response({
                'status': f'{action} completed',
                'document_title': flow.document.title,
                'action': action_message
            })
            
        except Message.DoesNotExist:
            return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)
        except ApprovalChatRoom.DoesNotExist:
            return Response({'error': 'Not a workflow chat room'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'Action failed: {str(e)}'}, 
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='my-workflow-discussions')
    def my_workflow_discussions(self, request):
        """Get workflow chat rooms where user is currently involved"""
        try:
            # Get rooms where user is either current approver or document creator
            workflow_rooms = ChatRoom.objects.filter(
                Q(approvalchatroom__approval_flow__current_approver=request.user) |
                Q(approvalchatroom__approval_flow__document__created_by=request.user)
            ).distinct()
            
            # Add context about the workflow status
            rooms_data = []
            for room in workflow_rooms:
                try:
                    approval_room = ApprovalChatRoom.objects.get(chat_room=room)
                    flow = approval_room.approval_flow
                    
                    room_info = ChatRoomSerializer(room, context={'request': request}).data
                    room_info['workflow_status'] = flow.status
                    room_info['document_title'] = flow.document.title
                    room_info['current_approver'] = flow.current_approver.get_full_name() if flow.current_approver else None
                    room_info['is_current_approver'] = flow.current_approver == request.user
                    
                    rooms_data.append(room_info)
                except ApprovalChatRoom.DoesNotExist:
                    continue
            
            return Response(rooms_data)
            
        except Exception as e:
            return Response({'error': f'Error fetching discussions: {str(e)}'}, 
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)