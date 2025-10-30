from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Q
from .models import *

class IsOnlineFilter(admin.SimpleListFilter):
    title = 'online status'
    parameter_name = 'online'

    def lookups(self, request, model_admin):
        return (
            ('online', 'Online'),
            ('offline', 'Offline'),
            ('recent', 'Recently Active (5 min)'),
        )

    def queryset(self, request, queryset):
        five_min_ago = timezone.now() - timezone.timedelta(minutes=5)
        
        if self.value() == 'online':
            return queryset.filter(online=True)
        elif self.value() == 'offline':
            return queryset.filter(online=False)
        elif self.value() == 'recent':
            return queryset.filter(last_seen__gte=five_min_ago)
        return queryset

class HasUnreadMessagesFilter(admin.SimpleListFilter):
    title = 'unread messages'
    parameter_name = 'has_unread'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Has Unread Messages'),
            ('no', 'No Unread Messages'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(
                Q(messages__read_receipts__isnull=True) & 
                Q(messages__is_deleted=False)
            ).distinct()
        elif self.value() == 'no':
            return queryset.exclude(
                Q(messages__read_receipts__isnull=True) & 
                Q(messages__is_deleted=False)
            ).distinct()
        return queryset

class ActiveRoomsFilter(admin.SimpleListFilter):
    title = 'room activity'
    parameter_name = 'activity'

    def lookups(self, request, model_admin):
        return (
            ('active', 'Recently Active (24h)'),
            ('inactive', 'Inactive (7+ days)'),
            ('no_messages', 'No Messages'),
        )

    def queryset(self, request, queryset):
        twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        
        if self.value() == 'active':
            return queryset.filter(last_activity__gte=twenty_four_hours_ago)
        elif self.value() == 'inactive':
            return queryset.filter(
                Q(last_activity__lt=seven_days_ago) | 
                Q(last_activity__isnull=True)
            )
        elif self.value() == 'no_messages':
            return queryset.annotate(message_count=Count('messages')).filter(message_count=0)
        return queryset

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user_info', 'online_status', 'last_seen', 'message_count', 
        'room_count', 'notification_status'
    ]
    list_display_links = ['user_info']
    list_filter = [IsOnlineFilter, 'theme', 'notification_enabled', 'last_seen']
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name', 
        'user__username', 'status'
    ]
    readonly_fields = [
        'last_seen', 'user_info', 'message_count', 'room_count', 
        'online_duration', 'created_at', 'updated_at'
    ]
    list_per_page = 50
    actions = ['enable_notifications', 'disable_notifications', 'set_theme_light', 'set_theme_dark']
    
    fieldsets = [
        ('User Information', {
            'fields': ['user', 'avatar_preview', 'status', 'user_info']
        }),
        ('Online Status', {
            'fields': ['online', 'last_seen', 'online_duration'],
            'classes': ['collapse']
        }),
        ('Preferences', {
            'fields': ['theme', 'notification_enabled', 'show_online_status', 'allow_direct_messages']
        }),
        ('Statistics', {
            'fields': ['message_count', 'room_count'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def user_info(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html(
            '<a href="{}"><strong>{}</strong></a><br><small>{}</small>',
            url,
            obj.user.get_full_name() or obj.user.username,
            obj.user.email
        )
    user_info.short_description = 'User'
    user_info.admin_order_field = 'user__email'

    def online_status(self, obj):
        if obj.online:
            return format_html(
                '<span style="color: green;">● Online</span>'
            )
        
        # Show how long ago they were last seen
        if obj.last_seen:
            delta = timezone.now() - obj.last_seen
            if delta.days > 0:
                return format_html(
                    '<span style="color: orange;">● {} days ago</span>',
                    delta.days
                )
            elif delta.seconds > 3600:
                return format_html(
                    '<span style="color: orange;">● {} hours ago</span>',
                    delta.seconds // 3600
                )
            else:
                return format_html(
                    '<span style="color: red;">● {} min ago</span>',
                    delta.seconds // 60
                )
        return format_html('<span style="color: gray;">● Never</span>')
    online_status.short_description = 'Status'

    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 100px;" />',
                obj.avatar.url
            )
        return "No avatar"
    avatar_preview.short_description = 'Avatar Preview'

    def message_count(self, obj):
        count = obj.user.messages.count()
        url = reverse('admin:chat_message_changelist') + f'?user__id={obj.user.id}'
        return format_html('<a href="{}">{}</a>', url, count)
    message_count.short_description = 'Messages'

    def room_count(self, obj):
        count = RoomMembership.objects.filter(user=obj.user, is_banned=False).count()
        url = reverse('admin:chat_roommembership_changelist') + f'?user__id={obj.user.id}'
        return format_html('<a href="{}">{}</a>', url, count)
    room_count.short_description = 'Rooms'

    def notification_status(self, obj):
        if obj.notification_enabled:
            return format_html('<span style="color: green;">✓ Enabled</span>')
        return format_html('<span style="color: red;">✗ Disabled</span>')
    notification_status.short_description = 'Notifications'

    def online_duration(self, obj):
        if obj.online and obj.last_seen:
            # This would require additional tracking in your model
            return "Currently online"
        return "Offline"
    online_duration.short_description = 'Online Duration'

    # Admin actions
    def enable_notifications(self, request, queryset):
        updated = queryset.update(notification_enabled=True)
        self.message_user(request, f'{updated} users enabled notifications')
    enable_notifications.short_description = "Enable notifications for selected users"

    def disable_notifications(self, request, queryset):
        updated = queryset.update(notification_enabled=False)
        self.message_user(request, f'{updated} users disabled notifications')
    disable_notifications.short_description = "Disable notifications for selected users"

    def set_theme_light(self, request, queryset):
        updated = queryset.update(theme='light')
        self.message_user(request, f'{updated} users set to light theme')
    set_theme_light.short_description = "Set light theme for selected users"

    def set_theme_dark(self, request, queryset):
        updated = queryset.update(theme='dark')
        self.message_user(request, f'{updated} users set to dark theme')
    set_theme_dark.short_description = "Set dark theme for selected users"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user').annotate(
            message_count=Count('user__messages'),
            room_count=Count('user__roommembership')
        )

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'title', 'privacy_badge', 'member_count', 'message_count', 
        'last_activity', 'created_by_link', 'is_active'
    ]
    list_display_links = ['name', 'title']
    list_filter = [ActiveRoomsFilter, 'privacy_level', 'is_active', 'created_at', 'allow_files', 'allow_links']
    search_fields = ['name', 'title', 'description', 'created_by__email']
    readonly_fields = [
        'created_at', 'updated_at', 'last_activity', 'member_count', 
        'message_count', 'created_by_link', 'active_members_list'
    ]
    list_per_page = 25
    actions = ['activate_rooms', 'deactivate_rooms', 'make_public', 'make_private']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'title', 'description', 'avatar_preview']
        }),
        ('Privacy & Settings', {
            'fields': [
                'privacy_level', 'is_active', 'max_members',
                'allow_links', 'allow_files', 'require_approval', 'slow_mode'
            ]
        }),
        ('Statistics', {
            'fields': ['member_count', 'message_count', 'last_activity', 'active_members_list'],
            'classes': ['collapse']
        }),
        ('Ownership', {
            'fields': ['created_by_link']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def privacy_badge(self, obj):
        colors = {
            'public': 'green',
            'private': 'orange', 
            'secret': 'red'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px;">{}</span>',
            colors.get(obj.privacy_level, 'gray'),
            obj.get_privacy_level_display()
        )
    privacy_badge.short_description = 'Privacy'
    privacy_badge.admin_order_field = 'privacy_level'

    def member_count(self, obj):
        count = obj.roommembership_set.filter(is_banned=False).count()
        url = reverse('admin:chat_roommembership_changelist') + f'?room__id={obj.id}'
        return format_html('<a href="{}">{}</a>', url, count)
    member_count.short_description = 'Members'

    def message_count(self, obj):
        count = obj.messages.count()
        url = reverse('admin:chat_message_changelist') + f'?room__id={obj.id}'
        return format_html('<a href="{}">{}</a>', url, count)
    message_count.short_description = 'Messages'

    def created_by_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.created_by.id])
        return format_html('<a href="{}">{}</a>', url, obj.created_by.email)
    created_by_link.short_description = 'Created By'

    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 100px;" />',
                obj.avatar.url
            )
        return "No avatar"
    avatar_preview.short_description = 'Room Avatar'

    def active_members_list(self, obj):
        members = obj.roommembership_set.filter(is_banned=False).select_related('user')[:10]
        member_links = []
        for membership in members:
            url = reverse('admin:auth_user_change', args=[membership.user.id])
            member_links.append(
                f'<a href="{url}">{membership.user.get_full_name() or membership.user.email}</a>'
            )
        return format_html('<br>'.join(member_links)) if member_links else "No members"
    active_members_list.short_description = 'Active Members'

    # Admin actions
    def activate_rooms(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} rooms activated')
    activate_rooms.short_description = "Activate selected rooms"

    def deactivate_rooms(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} rooms deactivated')
    deactivate_rooms.short_description = "Deactivate selected rooms"

    def make_public(self, request, queryset):
        updated = queryset.update(privacy_level='public')
        self.message_user(request, f'{updated} rooms set to public')
    make_public.short_description = "Make selected rooms public"

    def make_private(self, request, queryset):
        updated = queryset.update(privacy_level='private')
        self.message_user(request, f'{updated} rooms set to private')
    make_private.short_description = "Make selected rooms private"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by').annotate(
            member_count=Count('roommembership', filter=Q(roommembership__is_banned=False)),
            message_count=Count('messages')
        )

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = [
        'truncated_content', 'user_link', 'room_link', 'message_type_badge', 
        'timestamp', 'is_edited', 'is_deleted', 'read_count'
    ]
    list_display_links = ['truncated_content']
    list_filter = [
        'message_type', 'is_edited', 'is_deleted', 'timestamp', 
        'room', HasUnreadMessagesFilter
    ]
    search_fields = [
        'content', 'user__email', 'user__first_name', 'user__last_name',
        'room__name', 'room__title'
    ]
    readonly_fields = [
        'timestamp', 'edited_at', 'deleted_at', 'user_link', 
        'room_link', 'reply_to_link', 'read_count', 'reactions_summary'
    ]
    list_per_page = 50
    actions = ['soft_delete_messages', 'restore_messages', 'export_messages']
    
    fieldsets = [
        ('Message Content', {
            'fields': ['room_link', 'user_link', 'content', 'message_type']
        }),
        ('File Attachment', {
            'fields': ['file_url', 'file_name', 'file_size', 'file_type'],
            'classes': ['collapse']
        }),
        ('Reply Information', {
            'fields': ['reply_to_link'],
            'classes': ['collapse']
        }),
        ('Status & Analytics', {
            'fields': [
                'is_edited', 'edited_at', 'is_deleted', 'deleted_at', 
                'deleted_by_link', 'read_count', 'reactions_summary'
            ],
            'classes': ['collapse']
        }),
        ('Timestamp', {
            'fields': ['timestamp']
        }),
    ]

    def truncated_content(self, obj):
        content = obj.content
        if len(content) > 80:
            content = content[:77] + '...'
        
        badges = []
        if obj.is_deleted:
            badges.append('<span style="color: red;">[DELETED]</span>')
        if obj.is_edited:
            badges.append('<span style="color: orange;">[EDITED]</span>')
        if obj.reply_to:
            badges.append('<span style="color: blue;">[REPLY]</span>')
        
        badge_html = ' '.join(badges)
        return format_html('{} {}', badge_html, content)
    truncated_content.short_description = 'Content'
    truncated_content.admin_order_field = 'content'

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = 'User'

    def room_link(self, obj):
        url = reverse('admin:chat_chatroom_change', args=[obj.room.id])
        return format_html('<a href="{}">{}</a>', url, obj.room.name)
    room_link.short_description = 'Room'

    def message_type_badge(self, obj):
        colors = {
            'text': 'blue',
            'image': 'green',
            'file': 'orange',
            'system': 'gray',
            'reply': 'purple'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px;">{}</span>',
            colors.get(obj.message_type, 'gray'),
            obj.get_message_type_display()
        )
    message_type_badge.short_description = 'Type'

    def reply_to_link(self, obj):
        if obj.reply_to:
            url = reverse('admin:chat_message_change', args=[obj.reply_to.id])
            return format_html('<a href="{}">Reply to: {}</a>', url, obj.reply_to.truncated_content())
        return "Not a reply"
    reply_to_link.short_description = 'Reply To'

    def deleted_by_link(self, obj):
        if obj.deleted_by:
            url = reverse('admin:auth_user_change', args=[obj.deleted_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.deleted_by.email)
        return "Not deleted by user"
    deleted_by_link.short_description = 'Deleted By'

    def read_count(self, obj):
        count = obj.read_receipts.count()
        return f"{count} readers"
    read_count.short_description = 'Read By'

    def reactions_summary(self, obj):
        reactions = obj.reactions.values('reaction_type').annotate(count=Count('id'))
        if reactions:
            reaction_display = []
            for reaction in reactions:
                reaction_display.append(f"{reaction['reaction_type']}: {reaction['count']}")
            return ', '.join(reaction_display)
        return "No reactions"
    reactions_summary.short_description = 'Reactions'

    # Admin actions
    def soft_delete_messages(self, request, queryset):
        updated = 0
        for message in queryset:
            if not message.is_deleted:
                message.soft_delete(deleted_by=request.user)
                updated += 1
        self.message_user(request, f'{updated} messages soft deleted')
    soft_delete_messages.short_description = "Soft delete selected messages"

    def restore_messages(self, request, queryset):
        updated = queryset.update(is_deleted=False, deleted_at=None, deleted_by=None)
        self.message_user(request, f'{updated} messages restored')
    restore_messages.short_description = "Restore selected messages"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'room', 'reply_to', 'deleted_by'
        ).prefetch_related('read_receipts', 'reactions')

@admin.register(RoomMembership)
class RoomMembershipAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'room_link', 'role_badge', 'joined_at', 'is_banned_badge', 'ban_expiry']
    list_display_links = ['user_link', 'room_link']
    list_filter = ['role', 'is_banned', 'joined_at', 'room']
    search_fields = ['user__email', 'room__name', 'room__title']
    readonly_fields = ['joined_at', 'user_link', 'room_link']
    list_per_page = 50
    actions = ['ban_members', 'unban_members', 'promote_to_admin', 'demote_to_member']
    
    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = 'User'

    def room_link(self, obj):
        url = reverse('admin:chat_chatroom_change', args=[obj.room.id])
        return format_html('<a href="{}">{}</a>', url, obj.room.name)
    room_link.short_description = 'Room'

    def role_badge(self, obj):
        colors = {
            'owner': 'red',
            'admin': 'orange',
            'moderator': 'blue',
            'member': 'green',
            'pending': 'gray'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px;">{}</span>',
            colors.get(obj.role, 'gray'),
            obj.get_role_display().upper()
        )
    role_badge.short_description = 'Role'

    def is_banned_badge(self, obj):
        if obj.is_banned_currently():
            return format_html('<span style="color: red;">● BANNED</span>')
        return format_html('<span style="color: green;">● ACTIVE</span>')
    is_banned_badge.short_description = 'Status'

    def ban_expiry(self, obj):
        if obj.banned_until:
            if obj.banned_until > timezone.now():
                return f"Until {obj.banned_until.strftime('%Y-%m-%d %H:%M')}"
            else:
                return "EXPIRED"
        return "-"
    ban_expiry.short_description = 'Ban Expiry'

    # Admin actions
    def ban_members(self, request, queryset):
        updated = queryset.update(is_banned=True)
        self.message_user(request, f'{updated} members banned')
    ban_members.short_description = "Ban selected members"

    def unban_members(self, request, queryset):
        updated = queryset.update(is_banned=False, banned_until=None)
        self.message_user(request, f'{updated} members unbanned')
    unban_members.short_description = "Unban selected members"

    def promote_to_admin(self, request, queryset):
        updated = queryset.update(role='admin')
        self.message_user(request, f'{updated} members promoted to admin')
    promote_to_admin.short_description = "Promote to admin"

    def demote_to_member(self, request, queryset):
        # Don't allow demoting room owners
        updated = queryset.exclude(role='owner').update(role='member')
        self.message_user(request, f'{updated} members demoted to member')
    demote_to_member.short_description = "Demote to member"

@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'message_preview', 'read_at']
    list_filter = ['read_at']
    search_fields = ['user__email', 'message__content']
    readonly_fields = ['read_at', 'user_link', 'message_link']
    
    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = 'User'

    def message_preview(self, obj):
        content = obj.message.content
        if len(content) > 60:
            content = content[:57] + '...'
        url = reverse('admin:chat_message_change', args=[obj.message.id])
        return format_html('<a href="{}">{}</a>', url, content)
    message_preview.short_description = 'Message'

    def message_link(self, obj):
        url = reverse('admin:chat_message_change', args=[obj.message.id])
        return format_html('<a href="{}">View Message</a>', url)
    message_link.short_description = 'Message'

@admin.register(TypingIndicator)
class TypingIndicatorAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'room_link', 'is_typing_badge', 'last_activity']
    list_filter = ['is_typing', 'last_activity', 'room']
    search_fields = ['user__email', 'room__name']
    readonly_fields = ['last_activity', 'user_link', 'room_link']
    
    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = 'User'

    def room_link(self, obj):
        url = reverse('admin:chat_chatroom_change', args=[obj.room.id])
        return format_html('<a href="{}">{}</a>', url, obj.room.name)
    room_link.short_description = 'Room'

    def is_typing_badge(self, obj):
        if obj.is_typing:
            return format_html('<span style="color: green;">● TYPING</span>')
        return format_html('<span style="color: gray;">● IDLE</span>')
    is_typing_badge.short_description = 'Status'

# Custom Admin Site Configuration
class ChatAdminSite(admin.AdminSite):
    site_header = "Chat System Administration"
    site_title = "Chat System Admin"
    index_title = "Chat System Management"

# Optional: Register custom admin site
# chat_admin = ChatAdminSite(name='chat_admin')
# chat_admin.register(UserProfile, UserProfileAdmin)
# ... register other models