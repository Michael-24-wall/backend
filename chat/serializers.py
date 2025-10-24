from rest_framework import serializers
from .models import *
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    online_status = serializers.SerializerMethodField()
    
    class Meta:
        model = UserProfile
        fields = ['user', 'avatar', 'status', 'online', 'last_seen', 'online_status', 'theme', 'notification_enabled']  # ✅ Fixed: is_online to online
    
    def get_online_status(self, obj):
        if obj.online:  # ✅ Fixed: is_online to online
            return "online"
        return "offline"

class MessageSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    user_avatar = serializers.SerializerMethodField()
    reply_to_data = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    read_by = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'content', 'user', 'username', 'user_avatar', 'message_type',
            'file_url', 'file_name', 'file_size', 'reply_to', 'reply_to_data',
            'is_edited', 'edited_at', 'is_deleted', 'timestamp', 'reactions', 'read_by'
        ]
    
    def get_user_avatar(self, obj):
        if hasattr(obj.user, 'chat_profile') and obj.user.chat_profile.avatar:
            return obj.user.chat_profile.avatar.url
        return None
    
    def get_reply_to_data(self, obj):
        if obj.reply_to:
            return {
                'id': obj.reply_to.id,
                'content': obj.reply_to.content,
                'username': obj.reply_to.user.username,
                'timestamp': obj.reply_to.timestamp
            }
        return None
    
    def get_reactions(self, obj):
        # Implement reaction counting logic
        return {}
    
    def get_read_by(self, obj):
        return obj.read_receipts.count()

class ChatRoomSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    online_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatRoom
        fields = [
            'id', 'name', 'title', 'description', 'is_active', 'is_private',
            'max_members', 'created_by', 'created_at', 'updated_at',
            'member_count', 'online_count', 'last_message', 'user_role'
        ]
    
    def get_member_count(self, obj):
        return obj.roommembership_set.filter(is_banned=False).count()
    
    def get_online_count(self, obj):
        return UserProfile.objects.filter(
            user__in=obj.roommembership_set.filter(is_banned=False).values('user'),
            online=True  # ✅ Fixed: is_online to online
        ).count()
    
    def get_last_message(self, obj):
        last_msg = obj.messages.filter(is_deleted=False).last()
        if last_msg:
            return MessageSerializer(last_msg).data
        return None
    
    def get_user_role(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                membership = RoomMembership.objects.get(room=obj, user=request.user)
                return membership.role
            except RoomMembership.DoesNotExist:
                return None
        return None

class RoomMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    room = ChatRoomSerializer(read_only=True)
    
    class Meta:
        model = RoomMembership
        fields = ['id', 'user', 'room', 'role', 'joined_at', 'is_banned']

class MessageReadReceiptSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    message = MessageSerializer(read_only=True)
    
    class Meta:
        model = MessageReadReceipt
        fields = ['id', 'user', 'message', 'read_at']

class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['room', 'content', 'message_type', 'reply_to', 'file_url', 'file_name', 'file_size']
    
    def validate_content(self, value):
        if len(value) > 5000:
            raise serializers.ValidationError("Message content cannot exceed 5000 characters.")
        return value

class CreateChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = ['name', 'title', 'description', 'is_private', 'max_members']
    
    def validate_name(self, value):
        if ChatRoom.objects.filter(name=value).exists():
            raise serializers.ValidationError("A room with this name already exists.")
        return value

class UpdateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content']
    
    def validate_content(self, value):
        if len(value) > 5000:
            raise serializers.ValidationError("Message content cannot exceed 5000 characters.")
        return value