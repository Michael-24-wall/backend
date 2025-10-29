from rest_framework import serializers
from .models import ChatRoom, RoomMembership, Message, MessageReadReceipt, UserProfile

class ChatRoomSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = ChatRoom
        fields = [
            'id', 'name', 'title', 'description', 'is_active', 'is_private',
            'max_members', 'created_by', 'created_by_name', 'created_at',
            'updated_at', 'member_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'member_count']

    def get_member_count(self, obj):
        return obj.roommembership_set.filter(is_banned=False).count()

class RoomMembershipSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    
    class Meta:
        model = RoomMembership
        fields = [
            'id', 'user', 'user_name', 'user_email', 'room', 'room_name',
            'role', 'joined_at', 'is_banned'
        ]
        read_only_fields = ['id', 'joined_at']

class MessageSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    is_read = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'room', 'room_name', 'user', 'user_name', 'user_email',
            'content', 'message_type', 'file_url', 'file_name', 'file_size',
            'reply_to', 'is_edited', 'edited_at', 'is_deleted', 'deleted_at',
            'timestamp', 'is_read'
        ]
        read_only_fields = ['id', 'timestamp', 'is_read']

    def get_is_read(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.read_receipts.filter(user=request.user).exists()
        return False

class UserProfileSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'user_name', 'user_email', 'avatar', 'status',
            'online', 'last_seen', 'theme', 'notification_enabled'
        ]
        read_only_fields = ['id', 'user', 'last_seen']

# Serializers for creation (simplified fields)
class CreateChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = ['name', 'title', 'description', 'is_private', 'max_members']

class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['room', 'content', 'message_type', 'reply_to']

class UpdateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content']