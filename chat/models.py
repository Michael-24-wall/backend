from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache

class BaseModel(models.Model):
    """Abstract base model with common fields"""
    id = models.BigAutoField(primary_key=True, editable=False)  # Changed from UUIDField
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class ChatRoom(BaseModel):
    PRIVACY_LEVELS = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('secret', 'Secret'),
    ]
    
    name = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='room_avatars/', null=True, blank=True)
    privacy_level = models.CharField(max_length=10, choices=PRIVACY_LEVELS, default='public')
    max_members = models.IntegerField(default=1000)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_rooms')
    last_activity = models.DateTimeField(auto_now=True)
    
    # Moderation settings
    allow_links = models.BooleanField(default=True)
    allow_files = models.BooleanField(default=True)
    require_approval = models.BooleanField(default=False)
    slow_mode = models.IntegerField(default=0)  # seconds between messages
    
    class Meta:
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['privacy_level', 'is_active']),
            models.Index(fields=['last_activity']),
        ]
        ordering = ['-last_activity']
    
    def __str__(self):
        return f"{self.title} ({self.name})"
    
    def get_online_count(self):
        """Get number of online users in room"""
        cache_key = f"room_online_{self.id}"
        return cache.get(cache_key, 0)
    
    def can_join(self, user):
        """Check if user can join this room"""
        if self.privacy_level == 'secret':
            return RoomMembership.objects.filter(room=self, user=user).exists()
        return True

class RoomMembership(BaseModel):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Admin'),
        ('moderator', 'Moderator'),
        ('member', 'Member'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)
    is_banned = models.BooleanField(default=False)
    banned_until = models.DateTimeField(null=True, blank=True)
    notifications = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'room']
        indexes = [
            models.Index(fields=['user', 'room']),
            models.Index(fields=['room', 'is_banned']),
        ]
    
    def can_moderate(self):
        return self.role in ['owner', 'admin', 'moderator']
    
    def is_banned_currently(self):
        if not self.is_banned:
            return False
        if self.banned_until and self.banned_until < timezone.now():
            self.is_banned = False
            self.save()
            return False
        return True

class Message(BaseModel):
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('file', 'File'),
        ('system', 'System'),
        ('reply', 'Reply'),
    ]
    
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text')
    
    # File attachments
    file_url = models.URLField(blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.IntegerField(blank=True, null=True)
    file_type = models.CharField(max_length=100, blank=True, null=True)
    
    # Threading
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    thread = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='thread_messages')
    
    # Moderation
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_messages')
    
    # Metadata
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['room', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['thread', 'timestamp']),
            models.Index(fields=['is_deleted', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user.email}: {self.content[:50]}"
    
    def soft_delete(self, deleted_by=None):
        """Soft delete message with audit trail"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.content = "This message was deleted"
        self.file_url = None
        self.file_name = None
        self.file_size = None
        self.file_type = None
        self.save()
    
    def edit_message(self, new_content):
        """Edit message with version tracking"""
        # Create edit history
        MessageEditHistory.objects.create(
            message=self,
            old_content=self.content,
            new_content=new_content
        )
        
        self.content = new_content
        self.is_edited = True
        self.edited_at = timezone.now()
        self.save()

class MessageEditHistory(BaseModel):
    """Track message edit history"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='edit_history')
    old_content = models.TextField()
    new_content = models.TextField()
    edited_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-edited_at']

class MessageReadReceipt(BaseModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['message', 'user']
        indexes = [
            models.Index(fields=['message', 'user']),
            models.Index(fields=['user', 'read_at']),
        ]

class Reaction(BaseModel):
    """Message reactions"""
    REACTION_TYPES = [
        ('like', '👍'),
        ('love', '❤️'),
        ('laugh', '😂'),
        ('wow', '😮'),
        ('sad', '😢'),
        ('angry', '😠'),
    ]
    
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reaction_type = models.CharField(max_length=10, choices=REACTION_TYPES)
    
    class Meta:
        unique_together = ['message', 'user']
        indexes = [
            models.Index(fields=['message', 'reaction_type']),
        ]

class UserProfile(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_profile')
    avatar = models.ImageField(upload_to='chat/avatars/', null=True, blank=True)
    status = models.CharField(max_length=100, blank=True)
    online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(auto_now=True)
    theme = models.CharField(max_length=20, default='light')
    
    # Privacy settings
    show_online_status = models.BooleanField(default=True)
    allow_direct_messages = models.BooleanField(default=True)
    
    # Notification settings
    notification_enabled = models.BooleanField(default=True)
    message_notifications = models.BooleanField(default=True)
    sound_notifications = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Profile - {self.user.email}"
    
    @property
    def is_online(self):
        """Check if user is currently online"""
        if not self.show_online_status:
            return None  # Privacy mode
        return self.online

class TypingIndicator(BaseModel):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_typing = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['room', 'user']

class BanHistory(BaseModel):
    """Track user bans"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE)
    banned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='given_bans')
    reason = models.TextField(blank=True)
    banned_at = models.DateTimeField(auto_now_add=True)
    banned_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'room', 'is_active']),
        ]