from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.cache import cache
from .models import *

User = get_user_model()

class UserLiteSerializer(serializers.ModelSerializer):
    """Minimal user serializer for performance"""
    display_name = serializers.CharField(source='get_full_name', read_only=True)
    is_online = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'display_name', 'is_online', 'avatar']
        read_only_fields = ['id', 'username', 'email', 'display_name', 'is_online', 'avatar']
    
    def get_is_online(self, obj):
        try:
            profile = getattr(obj, 'chat_profile', None)
            if profile:
                return profile.is_online
        except (AttributeError, UserProfile.DoesNotExist):
            pass
        return False
    
    def get_avatar(self, obj):
        try:
            profile = getattr(obj, 'chat_profile', None)
            if profile and profile.avatar:
                return self.context.get('request').build_absolute_uri(profile.avatar.url) if self.context.get('request') else profile.avatar.url
        except (AttributeError, UserProfile.DoesNotExist):
            pass
        return None

class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    """
    A ModelSerializer that takes an additional `fields` argument that
    controls which fields should be displayed.
    """
    def __init__(self, *args, **kwargs):
        fields = kwargs.pop('fields', None)
        super().__init__(*args, **kwargs)
        
        if fields is not None:
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

class ChatRoomSerializer(DynamicFieldsModelSerializer):
    member_count = serializers.SerializerMethodField()
    online_count = serializers.SerializerMethodField()
    created_by = UserLiteSerializer(read_only=True)
    user_role = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatRoom
        fields = [
            'id', 'name', 'title', 'description', 'avatar', 'privacy_level',
            'max_members', 'is_active', 'created_by', 'last_activity',
            'member_count', 'online_count', 'user_role', 'is_member',
            'unread_count', 'last_message', 'allow_links', 'allow_files',
            'require_approval', 'slow_mode', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_activity']
    
    def get_member_count(self, obj):
        try:
            return obj.roommembership_set.filter(is_banned=False).count()
        except Exception:
            return 0
    
    def get_online_count(self, obj):
        try:
            return obj.get_online_count()
        except Exception:
            return 0
    
    def get_user_role(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                membership = RoomMembership.objects.get(room=obj, user=request.user)
                return membership.role
            except RoomMembership.DoesNotExist:
                return None
        return None
    
    def get_is_member(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                return RoomMembership.objects.filter(room=obj, user=request.user, is_banned=False).exists()
            except Exception:
                return False
        return False
    
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                # Cache this for performance
                cache_key = f"unread_{obj.id}_{request.user.id}"
                unread = cache.get(cache_key)
                if unread is None:
                    # Use a safe default for last_login
                    last_login = request.user.last_login or timezone.now() - timedelta(days=365)
                    unread = Message.objects.filter(
                        room=obj,
                        timestamp__gt=last_login,
                    ).exclude(
                        read_receipts__user=request.user
                    ).exclude(user=request.user).count()
                    cache.set(cache_key, unread, 60)  # Cache for 1 minute
                return unread
            except Exception:
                return 0
        return 0
    
    def get_last_message(self, obj):
        try:
            last_msg = obj.messages.filter(is_deleted=False).order_by('-timestamp').first()
            if last_msg:
                return {
                    'content': last_msg.content[:100] + '...' if len(last_msg.content) > 100 else last_msg.content,
                    'timestamp': last_msg.timestamp,
                    'user_name': last_msg.user.get_full_name() or last_msg.user.username,
                    'message_type': last_msg.message_type
                }
        except Exception:
            pass
        return None

class CreateChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = ['name', 'title', 'description', 'privacy_level', 'max_members', 
                 'allow_links', 'allow_files', 'require_approval', 'slow_mode']
    
    def validate_name(self, value):
        """Validate room name is unique and URL-safe"""
        if not value:
            raise serializers.ValidationError("Room name is required.")
        
        # Check if name is URL-safe
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', value):
            raise serializers.ValidationError("Room name can only contain letters, numbers, hyphens, and underscores.")
        
        # Check uniqueness
        if ChatRoom.objects.filter(name=value).exists():
            raise serializers.ValidationError("A room with this name already exists.")
        
        return value
    
    def validate_max_members(self, value):
        """Validate max members is reasonable"""
        if value < 2:
            raise serializers.ValidationError("Maximum members must be at least 2.")
        if value > 1000:
            raise serializers.ValidationError("Maximum members cannot exceed 1000.")
        return value

class UpdateChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = ['title', 'description', 'privacy_level', 'max_members', 
                 'allow_links', 'allow_files', 'require_approval', 'slow_mode', 'is_active']
    
    def validate_max_members(self, value):
        """Validate max members is reasonable"""
        if value < 2:
            raise serializers.ValidationError("Maximum members must be at least 2.")
        if value > 1000:
            raise serializers.ValidationError("Maximum members cannot exceed 1000.")
        return value

class RoomMembershipSerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    room_title = serializers.CharField(source='room.title', read_only=True)
    
    class Meta:
        model = RoomMembership
        fields = [
            'id', 'user', 'user_name', 'user_email', 'room', 'room_name', 'room_title',
            'role', 'joined_at', 'is_banned', 'banned_until', 'notifications'
        ]
        read_only_fields = ['id', 'joined_at']

class ReplyMessageSerializer(serializers.ModelSerializer):
    """Serializer for replied messages"""
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user = UserLiteSerializer(read_only=True)
    
    class Meta:
        model = Message
        fields = ['id', 'user', 'user_name', 'content', 'message_type', 'timestamp', 'is_deleted']
        read_only_fields = ['id', 'user', 'user_name', 'content', 'message_type', 'timestamp', 'is_deleted']

class MessageSerializer(DynamicFieldsModelSerializer):
    user = UserLiteSerializer(read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    room_title = serializers.CharField(source='room.title', read_only=True)
    is_read = serializers.SerializerMethodField()
    show_sender_info = serializers.SerializerMethodField()
    is_own_message = serializers.SerializerMethodField()
    reply_to_data = ReplyMessageSerializer(source='reply_to', read_only=True)
    reactions_summary = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'room', 'room_name', 'room_title', 'user', 'content', 'message_type',
            'file_url', 'file_name', 'file_size', 'file_type', 'reply_to',
            'reply_to_data', 'is_edited', 'edited_at', 'is_deleted', 'deleted_at',
            'timestamp', 'is_read', 'show_sender_info', 'is_own_message',
            'reactions_summary', 'can_edit', 'can_delete'
        ]
        read_only_fields = ['id', 'timestamp', 'is_read', 'show_sender_info', 'is_own_message']

    def get_is_read(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                return obj.read_receipts.filter(user=request.user).exists()
            except Exception:
                return False
        return False

    def get_show_sender_info(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.user != request.user
        return True

    def get_is_own_message(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.user == request.user
        return False

    def get_reactions_summary(self, obj):
        try:
            from django.db.models import Count
            reactions = obj.reactions.values('reaction_type').annotate(count=Count('id'))
            return {r['reaction_type']: r['count'] for r in reactions}
        except Exception:
            return {}

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Allow editing within 15 minutes for message owner
            if obj.user == request.user and not obj.is_deleted:
                try:
                    time_diff = (timezone.now() - obj.timestamp).total_seconds()
                    return time_diff <= 900  # 15 minutes
                except Exception:
                    return False
        return False

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if obj.user == request.user:
                return True
            # Check if user is moderator/admin of the room
            try:
                membership = RoomMembership.objects.get(room=obj.room, user=request.user)
                return membership.role in ['owner', 'admin', 'moderator']
            except RoomMembership.DoesNotExist:
                return False
        return False

class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['room', 'content', 'message_type', 'reply_to']
    
    def validate(self, attrs):
        room = attrs.get('room')
        user = self.context['request'].user
        
        if not room:
            raise serializers.ValidationError("Room is required")
        
        # Check if user is member of room
        try:
            if not RoomMembership.objects.filter(room=room, user=user, is_banned=False).exists():
                raise serializers.ValidationError("You are not a member of this room")
        except Exception:
            raise serializers.ValidationError("You are not a member of this room")
        
        # Check slow mode
        if room.slow_mode > 0:
            try:
                last_message = Message.objects.filter(room=room, user=user).order_by('-timestamp').first()
                if last_message:
                    time_diff = (timezone.now() - last_message.timestamp).total_seconds()
                    if time_diff < room.slow_mode:
                        raise serializers.ValidationError(f"Slow mode active. Wait {room.slow_mode - int(time_diff)} seconds")
            except Exception:
                pass  # If slow mode check fails, continue anyway
        
        # Validate reply
        reply_to = attrs.get('reply_to')
        if reply_to:
            if reply_to.room != room:
                raise serializers.ValidationError("Cannot reply to message from different room")
            if reply_to.is_deleted:
                raise serializers.ValidationError("Cannot reply to deleted message")
        
        # Validate content for non-file messages
        if attrs.get('message_type') != 'file' and not attrs.get('content', '').strip():
            raise serializers.ValidationError("Message content cannot be empty for non-file messages")
        
        return attrs

class UpdateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content']
    
    def validate_content(self, value):
        if len(value.strip()) == 0:
            raise serializers.ValidationError("Message content cannot be empty")
        if len(value) > 5000:  # Reasonable message length limit
            raise serializers.ValidationError("Message is too long (maximum 5000 characters)")
        return value

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    is_online = serializers.BooleanField(source='online', read_only=True)
    
    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'user_name', 'user_email', 'avatar', 'status',
            'is_online', 'last_seen', 'theme', 'notification_enabled',
            'show_online_status', 'allow_direct_messages',
            'message_notifications', 'sound_notifications', 'email_notifications',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'last_seen', 'created_at', 'updated_at']
    
    def validate_theme(self, value):
        if value not in ['light', 'dark', 'auto']:
            raise serializers.ValidationError("Theme must be 'light', 'dark', or 'auto'")
        return value

class MessageReadReceiptSerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = MessageReadReceipt
        fields = ['id', 'user', 'user_name', 'message', 'read_at']
        read_only_fields = ['id', 'read_at']

class ReactionSerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    reaction_emoji = serializers.SerializerMethodField()
    
    class Meta:
        model = Reaction
        fields = ['id', 'user', 'user_name', 'message', 'reaction_type', 'reaction_emoji', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_reaction_emoji(self, obj):
        """Get the emoji representation of the reaction type"""
        reaction_emojis = {
            'like': '👍',
            'love': '❤️',
            'laugh': '😂',
            'wow': '😮',
            'sad': '😢',
            'angry': '😠',
        }
        return reaction_emojis.get(obj.reaction_type, '❓')

class TypingIndicatorSerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = TypingIndicator
        fields = ['id', 'user', 'user_name', 'room', 'is_typing', 'last_activity']
        read_only_fields = ['id', 'last_activity']

class BanHistorySerializer(serializers.ModelSerializer):
    user = UserLiteSerializer(read_only=True)
    banned_by = UserLiteSerializer(read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    
    class Meta:
        model = BanHistory
        fields = [
            'id', 'user', 'room', 'room_name', 'banned_by', 'reason',
            'banned_at', 'banned_until', 'is_active'
        ]
        read_only_fields = ['id', 'banned_at']

class MessageEditHistorySerializer(serializers.ModelSerializer):
    edited_by_name = serializers.CharField(source='edited_by.get_full_name', read_only=True)
    
    class Meta:
        model = MessageEditHistory
        fields = ['id', 'message', 'old_content', 'new_content', 'edited_by', 'edited_by_name', 'edited_at']
        read_only_fields = ['id', 'edited_at']

# Additional serializers for specific use cases
class RoomInviteSerializer(serializers.Serializer):
    """Serializer for room invitations"""
    room_id = serializers.UUIDField()
    user_emails = serializers.ListField(
        child=serializers.EmailField(),
        max_length=10
    )
    message = serializers.CharField(required=False, allow_blank=True, max_length=500)
    
    def validate_user_emails(self, value):
        if not value:
            raise serializers.ValidationError("At least one user email is required.")
        if len(value) > 10:
            raise serializers.ValidationError("Cannot invite more than 10 users at once.")
        return value

class BulkMessageDeleteSerializer(serializers.Serializer):
    """Serializer for bulk message deletion"""
    message_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=50
    )
    
    def validate_message_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one message ID is required.")
        if len(value) > 50:
            raise serializers.ValidationError("Cannot delete more than 50 messages at once.")
        return value

class UserPresenceUpdateSerializer(serializers.Serializer):
    """Serializer for updating user presence"""
    online = serializers.BooleanField(required=True)
    status = serializers.CharField(required=False, max_length=100, allow_blank=True)

class NotificationPreferencesSerializer(serializers.Serializer):
    """Serializer for notification preferences"""
    message_notifications = serializers.BooleanField(default=True)
    sound_notifications = serializers.BooleanField(default=True)
    email_notifications = serializers.BooleanField(default=False)

# Stats serializers
class RoomStatisticsSerializer(serializers.Serializer):
    total_messages = serializers.IntegerField()
    total_members = serializers.IntegerField()
    active_members = serializers.IntegerField()
    messages_today = serializers.IntegerField()
    most_active_user = serializers.DictField(required=False)
    message_types = serializers.DictField()

class UserStatisticsSerializer(serializers.Serializer):
    total_rooms = serializers.IntegerField()
    total_messages = serializers.IntegerField()
    unread_messages = serializers.IntegerField()
    messages_today = serializers.IntegerField()

class ActivityStatisticsSerializer(serializers.Serializer):
    daily_activity = serializers.ListField()
    most_active_room = serializers.DictField(required=False)

# File upload serializer
class FileUploadSerializer(serializers.Serializer):
    """Serializer for file uploads"""
    file = serializers.FileField()
    room_id = serializers.UUIDField(required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)

# Search serializers
class MessageSearchSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=100)
    room_id = serializers.UUIDField(required=False)
    message_type = serializers.CharField(required=False)
    user_id = serializers.UUIDField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    include_files = serializers.BooleanField(default=True)

    # chat/serializers.py
class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['room', 'content', 'reply_to', 'message_type']
    
    def validate_room(self, value):
        # Ensure user has access to the room
        user = self.context['request'].user
        if not RoomMembership.objects.filter(room=value, user=user, is_banned=False).exists():
            raise serializers.ValidationError("You are not a member of this room")
        return value