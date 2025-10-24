from django.contrib import admin
from .models import ChatRoom, RoomMembership, Message, MessageReadReceipt, UserProfile, TypingIndicator

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'online', 'last_seen', 'status']
    list_filter = ['online', 'theme', 'notification_enabled']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'status']
    readonly_fields = ['last_seen']
    fieldsets = [
        ('User Information', {
            'fields': ['user', 'avatar', 'status']
        }),
        ('Online Status', {
            'fields': ['online', 'last_seen']
        }),
        ('Preferences', {
            'fields': ['theme', 'notification_enabled']
        }),
    ]

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'is_active', 'is_private', 'max_members', 'created_by', 'created_at']
    list_filter = ['is_active', 'is_private', 'created_at']
    search_fields = ['name', 'title', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'title', 'description']
        }),
        ('Settings', {
            'fields': ['is_active', 'is_private', 'max_members']
        }),
        ('Ownership', {
            'fields': ['created_by']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at']
        }),
    ]

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'message_type', 'timestamp', 'is_edited', 'is_deleted']
    list_filter = ['message_type', 'is_edited', 'is_deleted', 'timestamp']
    search_fields = ['content', 'user__email', 'room__name']
    readonly_fields = ['timestamp']
    fieldsets = [
        ('Message Content', {
            'fields': ['room', 'user', 'content', 'message_type']
        }),
        ('File Attachment', {
            'fields': ['file_url', 'file_name', 'file_size'],
            'classes': ['collapse']
        }),
        ('Reply Information', {
            'fields': ['reply_to'],
            'classes': ['collapse']
        }),
        ('Status', {
            'fields': ['is_edited', 'edited_at', 'is_deleted', 'deleted_at']
        }),
        ('Timestamp', {
            'fields': ['timestamp']
        }),
    ]

@admin.register(RoomMembership)
class RoomMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'role', 'joined_at', 'is_banned']
    list_filter = ['role', 'is_banned', 'joined_at']
    search_fields = ['user__email', 'room__name']
    readonly_fields = ['joined_at']

@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'read_at']
    list_filter = ['read_at']
    search_fields = ['user__email', 'message__content']
    readonly_fields = ['read_at']

@admin.register(TypingIndicator)
class TypingIndicatorAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'is_typing', 'last_activity']
    list_filter = ['is_typing', 'last_activity']
    search_fields = ['user__email', 'room__name']
    readonly_fields = ['last_activity']