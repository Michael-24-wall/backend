# editor/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.core.cache import cache
import uuid
import json
import hashlib
from typing import Dict, Any, Optional, List, TYPE_CHECKING

# Use TYPE_CHECKING to avoid circular imports in type hints
if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserType
else:
    UserType = get_user_model()

class DocumentStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    ACTIVE = 'active', _('Active')
    ARCHIVED = 'archived', _('Archived')
    LOCKED = 'locked', _('Locked')
    DELETED = 'deleted', _('Deleted')

class DocumentType(models.TextChoices):
    SPREADSHEET = 'spreadsheet', _('Spreadsheet')
    BUDGET = 'budget', _('Budget')
    INVENTORY = 'inventory', _('Inventory')
    REPORT = 'report', _('Report')
    TEMPLATE = 'template', _('Template')
    CUSTOM = 'custom', _('Custom')

class PermissionLevel(models.TextChoices):
    VIEW = 'view', _('Can View')
    COMMENT = 'comment', _('Can Comment')
    EDIT = 'edit', _('Can Edit')
    MANAGE = 'manage', _('Can Manage')
    OWNER = 'owner', _('Owner')

class ChangeType(models.TextChoices):
    CREATED = 'created', _('Created')
    UPDATED = 'updated', _('Updated')
    DELETED = 'deleted', _('Deleted')
    RENAMED = 'renamed', _('Renamed')
    SHARED = 'shared', _('Shared')
    VERSIONED = 'versioned', _('Versioned')
    RESTORED = 'restored', _('Restored')
    EXPORTED = 'exported', _('Exported')

class Organization(models.Model):
    """
    Organization model for multi-tenant support
    """
    name = models.CharField(_('organization name'), max_length=255)
    slug = models.SlugField(_('organization slug'), unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    plan_type = models.CharField(
        _('plan type'),
        max_length=50,
        choices=[
            ('free', 'Free'),
            ('pro', 'Professional'),
            ('enterprise', 'Enterprise')
        ],
        default='free'
    )
    storage_limit_mb = models.IntegerField(_('storage limit (MB)'), default=1024)
    
    # FIX: Added unique related_name to avoid conflicts with core app
    active_users = models.ManyToManyField(
        UserType, 
        through='OrganizationMembership',
        related_name='editor_organizations'
    )

    class Meta:
        db_table = 'editor_organizations'  # Unique table name
        verbose_name = _('organization')
        verbose_name_plural = _('organizations')

    def __str__(self) -> str:
        return self.name

class OrganizationMembership(models.Model):
    """
    Track user membership in organizations with roles
    """
    # FIX: Added unique related_names to avoid conflicts
    user = models.ForeignKey(
        UserType, 
        on_delete=models.CASCADE,
        related_name='editor_organization_memberships'
    )
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='editor_memberships'
    )
    role = models.CharField(
        max_length=50,
        choices=[
            ('member', 'Member'),
            ('admin', 'Admin'),
            ('owner', 'Owner')
        ],
        default='member'
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'editor_organization_memberships'  # Unique table name
        unique_together = ['user', 'organization']
        verbose_name = _('organization membership')
        verbose_name_plural = _('organization memberships')

    def __str__(self) -> str:
        return f"{self.user.username} - {self.organization.name} ({self.role})"

class Tag(models.Model):
    """
    Flexible tagging system for documents
    """
    name = models.CharField(_('tag name'), max_length=50)
    color = models.CharField(_('tag color'), max_length=7, default='#6B7280')  # HEX color
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    created_by = models.ForeignKey(
        UserType, 
        on_delete=models.CASCADE,
        related_name='created_tags'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'editor_tags'  # Unique table name
        unique_together = ['name', 'organization']
        verbose_name = _('tag')
        verbose_name_plural = _('tags')

    def __str__(self) -> str:
        return self.name

class SpreadsheetDocument(models.Model):
    """
    Enhanced model for comprehensive spreadsheet document management
    with versioning, collaboration, and enterprise features.
    """
    
    # Core Identification
    uuid = models.UUIDField(
        _('unique identifier'), 
        default=uuid.uuid4, 
        editable=False, 
        unique=True
    )
    title = models.CharField(
        _('document title'), 
        max_length=255,
        help_text=_('Name of the spreadsheet document')
    )
    description = models.TextField(
        _('description'), 
        blank=True, 
        null=True,
        help_text=_('Optional document description')
    )
    
    # Ownership & Organization
    owner = models.ForeignKey(
        UserType, 
        on_delete=models.CASCADE, 
        related_name='owned_spreadsheets',
        verbose_name=_('owner')
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='spreadsheets',
        null=True,
        blank=True,
        verbose_name=_('organization')
    )
    
    # Document Classification
    document_type = models.CharField(
        _('document type'),
        max_length=50,
        choices=DocumentType.choices,
        default=DocumentType.SPREADSHEET
    )
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT
    )
    
    # Core Data Storage
    editor_data = models.JSONField(
        _('editor data'),
        default=dict,
        blank=True,
        help_text=_('Complete JSON state of the spreadsheet editor')
    )
    
    # Metadata & Tracking
    created_at = models.DateTimeField(
        _('created at'), 
        default=timezone.now,
        db_index=True
    )
    updated_at = models.DateTimeField(
        _('updated at'), 
        auto_now=True,
        db_index=True
    )
    last_accessed_at = models.DateTimeField(
        _('last accessed at'),
        default=timezone.now
    )
    last_modified_by = models.ForeignKey(
        UserType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modified_spreadsheets',
        verbose_name=_('last modified by')
    )
    
    # Collaboration - FIX: Added through_fields to resolve ambiguity
    collaborators = models.ManyToManyField(
        UserType,
        through='DocumentCollaborator',
        related_name='collaborative_spreadsheets',
        through_fields=('document', 'user'),
        verbose_name=_('collaborators')
    )
    
    # Categorization
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='spreadsheets',
        verbose_name=_('tags')
    )
    
    # Flags & Settings
    is_template = models.BooleanField(
        _('is template'),
        default=False,
        help_text=_('Whether this document is a template')
    )
    is_archived = models.BooleanField(
        _('is archived'),
        default=False,
        db_index=True
    )
    is_public = models.BooleanField(
        _('is public'),
        default=False,
        help_text=_('Whether this document is publicly accessible')
    )
    allow_comments = models.BooleanField(
        _('allow comments'),
        default=True
    )
    
    # Performance & Analytics
    size = models.IntegerField(
        _('data size'),
        default=0,
        help_text=_('Size of editor_data in bytes')
    )
    complexity_score = models.FloatField(
        _('complexity score'),
        default=0.0,
        help_text=_('Calculated complexity of the spreadsheet')
    )
    view_count = models.IntegerField(
        _('view count'),
        default=0
    )
    
    # Search Optimization
    search_vector = SearchVectorField(
        null=True,
        blank=True,
        help_text=_('Search vector for full-text search')
    )
    
    # External References
    template_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='derived_documents',
        verbose_name=_('template source')
    )
    
    # Custom Metadata
    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        blank=True,
        help_text=_('Additional custom metadata')
    )

    class Meta:
        db_table = 'spreadsheet_documents'
        verbose_name = _('spreadsheet document')
        verbose_name_plural = _('spreadsheet documents')
        indexes = [
            models.Index(fields=['owner', 'created_at']),
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['is_archived', 'document_type']),
            GinIndex(fields=['search_vector']),
            models.Index(fields=['updated_at']),
            models.Index(fields=['last_accessed_at']),
        ]
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return f"{self.title} ({self.owner.username})"

    def save(self, *args, **kwargs) -> None:
        """Enhanced save with automatic field updates"""
        # Update size field
        if self.editor_data:
            self.size = len(json.dumps(self.editor_data))
        
        # Update timestamps
        if not self.id:
            self.created_at = timezone.now()
        
        self.updated_at = timezone.now()
        
        # Calculate complexity score
        self.complexity_score = self.calculate_complexity()
        
        # Validate data before saving
        self.full_clean()
        
        super().save(*args, **kwargs)
        
        # Update search vector asynchronously (could be done with Celery)
        self.update_search_vector()

    def calculate_complexity(self) -> float:
        """Calculate spreadsheet complexity score"""
        if not self.editor_data:
            return 0.0
        
        try:
            data = self.editor_data
            complexity = 0.0
            
            # Factor 1: Number of sheets
            sheets = data.get('sheets', [])
            complexity += len(sheets) * 0.1
            
            # Factor 2: Number of cells (estimated)
            total_cells = 0
            for sheet in sheets:
                cells = sheet.get('cells', {})
                total_cells += len(cells)
            
            complexity += total_cells * 0.001
            
            # Factor 3: Formulas count
            formula_count = 0
            for sheet in sheets:
                formulas = sheet.get('formulas', {})
                formula_count += len(formulas)
            
            complexity += formula_count * 0.01
            
            # Factor 4: Data size
            complexity += self.size * 0.000001
            
            return min(complexity, 100.0)  # Cap at 100
            
        except (AttributeError, TypeError, KeyError):
            return 0.0

    def update_search_vector(self) -> None:
        """Update full-text search vector (simplified implementation)"""
        # In a real implementation, you'd use Django's SearchVector
        # This is a placeholder for the concept
        search_content = f"{self.title} {self.description or ''}"
        # Actual implementation would use:
        # from django.contrib.postgres.search import SearchVector
        # SpreadsheetDocument.objects.filter(pk=self.pk).update(
        #     search_vector=SearchVector('title', 'description')
        # )

    def can_view(self, user: 'UserType') -> bool:
        """Check if user can view this document"""
        if self.is_public:
            return True
        
        if user == self.owner:
            return True
        
        if self.organization and hasattr(user, 'editor_organization_memberships'):
            if user.editor_organization_memberships.filter(
                organization=self.organization
            ).exists():
                return True
        
        return self.collaborators.filter(pk=user.pk).exists()

    def can_edit(self, user: 'UserType') -> bool:
        """Check if user can edit this document"""
        if user == self.owner:
            return True
        
        if self.status == DocumentStatus.LOCKED:
            return False
        
        if hasattr(self, 'document_collaborators'):
            collaborator = self.document_collaborators.filter(user=user).first()
            return collaborator and collaborator.permission_level in [
                PermissionLevel.EDIT, 
                PermissionLevel.MANAGE, 
                PermissionLevel.OWNER
            ]
        return False

    def can_share(self, user: 'UserType') -> bool:
        """Check if user can share this document"""
        if user == self.owner:
            return True
        
        if hasattr(self, 'document_collaborators'):
            collaborator = self.document_collaborators.filter(user=user).first()
            return collaborator and collaborator.permission_level in [
                PermissionLevel.MANAGE, 
                PermissionLevel.OWNER
            ]
        return False

    def can_delete(self, user: 'UserType') -> bool:
        """Check if user can delete this document"""
        return user == self.owner

    def create_version(self, user: 'UserType', description: str = "") -> 'DocumentVersion':
        """Create a version snapshot of the document"""
        return DocumentVersion.objects.create(
            document=self,
            version_data=self.editor_data.copy() if self.editor_data else {},
            created_by=user,
            version_number=self.versions.count() + 1,
            change_description=description,
            checksum=self.calculate_checksum()
        )

    def calculate_checksum(self) -> str:
        """Calculate checksum for data integrity verification"""
        if not self.editor_data:
            return ""
        return hashlib.md5(
            json.dumps(self.editor_data, sort_keys=True).encode('utf-8')
        ).hexdigest()

    def get_download_size(self) -> int:
        """Calculate approximate download size in bytes"""
        base_size = self.size
        # Add overhead for metadata, formatting, etc.
        return int(base_size * 1.1)

    def record_access(self, user: 'UserType') -> None:
        """Record document access for analytics"""
        self.last_accessed_at = timezone.now()
        self.view_count += 1
        self.save(update_fields=['last_accessed_at', 'view_count'])
        
        # Record detailed access log
        DocumentAccessLog.objects.create(
            document=self,
            user=user,
            access_type='view'
        )

    def clean(self) -> None:
        """Model-level validation"""
        super().clean()
        
        # Validate document size limits
        max_size = 50 * 1024 * 1024  # 50MB
        if self.size > max_size:
            raise ValidationError(
                f"Document size ({self.size} bytes) exceeds maximum allowed ({max_size} bytes)"
            )
        
        # Validate template constraints
        if self.is_template and self.template_source:
            raise ValidationError("A template cannot have a template source")
        
        # Validate organization membership - FIX: Updated to use editor_organization_memberships
        if self.organization and self.owner:
            if hasattr(self.owner, 'editor_organization_memberships'):
                if not self.owner.editor_organization_memberships.filter(
                    organization=self.organization
                ).exists():
                    raise ValidationError("Document owner must be a member of the organization")

    @property
    def is_active(self) -> bool:
        """Check if document is active"""
        return self.status == DocumentStatus.ACTIVE and not self.is_archived

    @property
    def collaborator_count(self) -> int:
        """Get number of collaborators"""
        return self.collaborators.count()

    @property
    def version_count(self) -> int:
        """Get number of versions"""
        return self.versions.count()

    @classmethod
    def get_user_documents(cls, user: 'UserType', include_archived: bool = False) -> models.QuerySet:
        """Get all documents accessible by a user"""
        # FIX: Updated to use editor_memberships
        queryset = cls.objects.filter(
            models.Q(owner=user) |
            models.Q(collaborators=user) |
            models.Q(is_public=True) |
            models.Q(organization__editor_memberships__user=user)
        ).distinct()
        
        if not include_archived:
            queryset = queryset.filter(is_archived=False)
        
        return queryset

class DocumentCollaborator(models.Model):
    """
    Through model for document collaboration with permission levels
    """
    document = models.ForeignKey(
        SpreadsheetDocument,
        on_delete=models.CASCADE,
        related_name='document_collaborators'
    )
    # FIX: Added unique related_name to avoid conflicts
    user = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='editor_document_collaborations'
    )
    permission_level = models.CharField(
        _('permission level'),
        max_length=20,
        choices=PermissionLevel.choices,
        default=PermissionLevel.VIEW
    )
    added_at = models.DateTimeField(auto_now_add=True)
    # FIX: Added unique related_name to avoid conflicts
    added_by = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='editor_added_collaborators'
    )
    expires_at = models.DateTimeField(
        _('expires at'),
        null=True,
        blank=True
    )

    class Meta:
        db_table = 'document_collaborators'
        unique_together = ['document', 'user']
        verbose_name = _('document collaborator')
        verbose_name_plural = _('document collaborators')

    def __str__(self) -> str:
        return f"{self.user.username} - {self.document.title} ({self.permission_level})"

    def is_active(self) -> bool:
        """Check if collaboration is still active"""
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

class DocumentVersion(models.Model):
    """
    Comprehensive versioning system for document changes
    """
    document = models.ForeignKey(
        SpreadsheetDocument,
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.IntegerField(_('version number'))
    version_data = models.JSONField(_('version data'))
    created_at = models.DateTimeField(_('created at'), default=timezone.now)
    created_by = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='created_versions'
    )
    change_description = models.TextField(
        _('change description'),
        blank=True,
        null=True
    )
    checksum = models.CharField(_('checksum'), max_length=32)
    data_size = models.IntegerField(_('data size'), default=0)

    class Meta:
        db_table = 'document_versions'
        verbose_name = _('document version')
        verbose_name_plural = _('document versions')
        unique_together = ['document', 'version_number']
        ordering = ['document', '-version_number']

    def __str__(self) -> str:
        return f"v{self.version_number} - {self.document.title}"

    def save(self, *args, **kwargs) -> None:
        """Calculate data size before saving"""
        if self.version_data:
            self.data_size = len(json.dumps(self.version_data))
        super().save(*args, **kwargs)

    def restore(self, user: 'UserType') -> SpreadsheetDocument:
        """Restore this version as the current document"""
        self.document.editor_data = self.version_data
        self.document.last_modified_by = user
        self.document.save()
        return self.document

class AuditLog(models.Model):
    """
    Comprehensive audit logging for all document activities
    """
    document = models.ForeignKey(
        SpreadsheetDocument,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    user = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='audit_actions'
    )
    action = models.CharField(
        _('action'),
        max_length=50,
        choices=ChangeType.choices
    )
    timestamp = models.DateTimeField(_('timestamp'), default=timezone.now)
    details = models.JSONField(_('details'), default=dict)
    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True
    )
    user_agent = models.TextField(
        _('user agent'),
        blank=True,
        null=True
    )

    class Meta:
        db_table = 'audit_logs'
        verbose_name = _('audit log')
        verbose_name_plural = _('audit logs')
        indexes = [
            models.Index(fields=['document', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self) -> str:
        return f"{self.user.username} {self.action} {self.document.title}"

class DocumentAccessLog(models.Model):
    """
    Detailed access logging for analytics and security
    """
    document = models.ForeignKey(
        SpreadsheetDocument,
        on_delete=models.CASCADE,
        related_name='access_logs'
    )
    user = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='document_accesses'
    )
    access_type = models.CharField(
        _('access type'),
        max_length=20,
        choices=[
            ('view', 'View'),
            ('edit', 'Edit'),
            ('download', 'Download'),
            ('print', 'Print')
        ]
    )
    accessed_at = models.DateTimeField(_('accessed at'), default=timezone.now)
    session_id = models.CharField(
        _('session ID'),
        max_length=100,
        blank=True,
        null=True
    )
    duration_seconds = models.IntegerField(
        _('duration seconds'),
        null=True,
        blank=True
    )

    class Meta:
        db_table = 'document_access_logs'
        verbose_name = _('document access log')
        verbose_name_plural = _('document access logs')
        indexes = [
            models.Index(fields=['document', 'accessed_at']),
            models.Index(fields=['user', 'accessed_at']),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} accessed {self.document.title}"

class DocumentComment(models.Model):
    """
    Comment system for document collaboration
    """
    document = models.ForeignKey(
        SpreadsheetDocument,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    user = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        related_name='document_comments'
    )
    parent_comment = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies'
    )
    content = models.TextField(_('content'))
    cell_reference = models.CharField(
        _('cell reference'),
        max_length=20,
        blank=True,
        null=True,
        help_text=_('Cell reference if comment is tied to a specific cell')
    )
    created_at = models.DateTimeField(_('created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    is_resolved = models.BooleanField(_('is resolved'), default=False)

    class Meta:
        db_table = 'document_comments'
        verbose_name = _('document comment')
        verbose_name_plural = _('document comments')
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Comment by {self.user.username} on {self.document.title}"

# Signal handlers
@receiver(post_save, sender=SpreadsheetDocument)
def create_initial_audit_log(sender, instance, created, **kwargs) -> None:
    """Create audit log entry when document is created"""
    if created:
        AuditLog.objects.create(
            document=instance,
            user=instance.owner,
            action=ChangeType.CREATED,
            details={'title': instance.title}
        )

@receiver(pre_delete, sender=SpreadsheetDocument)
def create_deletion_audit_log(sender, instance, **kwargs) -> None:
    """Create audit log entry when document is deleted"""
    AuditLog.objects.create(
        document=instance,
        user=instance.owner,
        action=ChangeType.DELETED,
        details={'title': instance.title}
    )

# Custom managers
class ActiveDocumentManager(models.Manager):
    """Custom manager for active documents only"""
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(
            is_archived=False,
            status=DocumentStatus.ACTIVE
        )

class TemplateManager(models.Manager):
    """Custom manager for template documents"""
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_template=True)

# Add custom managers to SpreadsheetDocument
SpreadsheetDocument.active_objects = ActiveDocumentManager()
SpreadsheetDocument.template_objects = TemplateManager()