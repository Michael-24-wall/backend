from django.contrib import admin
from .models import *

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'is_active', 'is_private', 'created_by', 'created_at']
    list_filter = ['is_active', 'is_private', 'created_at']
    search_fields = ['name', 'title', 'description']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'user', 'content_preview', 'message_type', 'timestamp', 'is_deleted']
    list_filter = ['message_type', 'is_deleted', 'timestamp', 'room']
    search_fields = ['content', 'user__username', 'room__name']
    readonly_fields = ['timestamp', 'edited_at', 'deleted_at']
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'

@admin.register(RoomMembership)
class RoomMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'role', 'is_banned', 'joined_at']
    list_filter = ['role', 'is_banned', 'joined_at']
    search_fields = ['user__username', 'room__name']

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_online', 'last_seen', 'status']
    list_filter = ['is_online', 'last_seen']
    search_fields = ['user__username']

@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ['message', 'user', 'read_at']
    list_filter = ['read_at']
    search_fields = ['message__content', 'user__username']