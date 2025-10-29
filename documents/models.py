from django.db import models
from django.conf import settings
from core.models import Organization, CustomUser, OrganizationMembership
import uuid

# --- 1. Document Template Model ---
class DocumentTemplate(models.Model):
    """Defines a blueprint for creating new documents (e.g., 'Employment Contract')."""
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='documents_templates',  # CHANGED: Unique related_name
        help_text="The organization this template belongs to."
    )
    name = models.CharField(max_length=255, help_text="Template name (e.g., 'Employment Contract')")
    title = models.CharField(max_length=255, blank=True, help_text="Display title (optional)")
    description = models.TextField(blank=True, help_text="Template description and usage notes")
    
    content = models.TextField(
        help_text="HTML/Markdown content with placeholders (e.g., {{user.first_name}})."
    )
    content_template = models.TextField(
        blank=True,
        help_text="Legacy field - use 'content' instead."
    )
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='documents_created_templates')  # CHANGED
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('organization', 'name') 
        verbose_name = "Document Template"
        ordering = ['name']
        
    def __str__(self):
        return f"{self.name} ({self.organization.name})"
    
    def save(self, *args, **kwargs):
        if not self.content_template and self.content:
            self.content_template = self.content
        super().save(*args, **kwargs)


# --- 2. Document Model (The Instance) ---
class Document(models.Model):
    """An actual generated document instance derived from a template."""
    STATUS_DRAFT = 'draft'
    STATUS_PENDING_REVIEW = 'pending_review'
    STATUS_PENDING_APPROVAL = 'pending_approval'
    STATUS_PENDING_FINAL_SIGNATURE = 'pending_final_signature'
    STATUS_SIGNED = 'signed'
    STATUS_ARCHIVED = 'archived'
    STATUS_REJECTED = 'rejected'
    
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING_REVIEW, 'Pending Review'),
        (STATUS_PENDING_APPROVAL, 'Pending Approval'),
        (STATUS_PENDING_FINAL_SIGNATURE, 'Pending Final Signature'),
        (STATUS_SIGNED, 'Signed/Final'),
        (STATUS_ARCHIVED, 'Archived'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='documents_documents'  # CHANGED: Unique related_name
    )
    template = models.ForeignKey(
        DocumentTemplate, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        related_name='documents_documents'  # CHANGED: Unique related_name
    )
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES, 
        default=STATUS_DRAFT
    )
    
    final_content = models.TextField(
        null=True, 
        blank=True,
        help_text="The rendered HTML content of the document instance."
    )
    
    file_attachment = models.FileField(
        upload_to='documents/%Y/%m/',
        null=True, 
        blank=True,
        help_text="The final PDF or file representation."
    )
    file_description = models.TextField(
        blank=True,
        help_text="Description of the attached file"
    )
    file_size = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="File size in bytes"
    )
    
    created_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE, 
        related_name='documents_authored_documents'  # CHANGED: Unique related_name
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    version = models.IntegerField(default=1)
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['organization', 'created_by']),
            models.Index(fields=['organization', 'template']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Doc: {self.title} ({self.status})"
    
    def save(self, *args, **kwargs):
        if self.file_attachment and not self.file_size:
            self.file_size = self.file_attachment.size
        super().save(*args, **kwargs)


# --- 3. Digital Signature Log Model ---
class DigitalSignatureLog(models.Model):
    """Records a single digital signature/approval action on a document."""
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='documents_signatures'  # CHANGED: Unique related_name
    )
    signer = models.ForeignKey(
        CustomUser, 
        on_delete=models.PROTECT,
        related_name='documents_document_signatures'  # CHANGED: Unique related_name
    )
    
    signed_at = models.DateTimeField(auto_now_add=True)
    signer_role = models.CharField(max_length=50)
    
    signature_data = models.TextField(
        blank=True,
        help_text="Encrypted signature data or hash"
    )
    signing_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Reason for signing"
    )
    ip_address = models.GenericIPAddressField(
        null=True, 
        blank=True,
        help_text="IP address of signer"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Browser/user agent information"
    )
    
    content_hash = models.CharField(
        max_length=64, 
        null=True, 
        blank=True, 
        help_text="SHA256 hash of the document's content at the time of signing."
    )
    is_valid = models.BooleanField(default=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidated_reason = models.TextField(blank=True)

    class Meta:
        unique_together = ('document', 'signer')
        verbose_name = "Digital Signature Log"
        verbose_name_plural = "Digital Signature Logs"
        ordering = ['-signed_at']
        
    def __str__(self):
        return f"Signed by {self.signer.email} on {self.document.title}"


# --- 4. Document Permission Model ---
class DocumentPermission(models.Model):
    """Defines who can view/edit/sign a specific document instance."""
    PERMISSION_VIEW = 'view'
    PERMISSION_COMMENT = 'comment'
    PERMISSION_EDIT = 'edit'
    PERMISSION_SIGN = 'sign'
    
    PERMISSION_CHOICES = [
        (PERMISSION_VIEW, 'Can View'),
        (PERMISSION_COMMENT, 'Can Comment'),
        (PERMISSION_EDIT, 'Can Edit'),
        (PERMISSION_SIGN, 'Can Sign'),
    ]

    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='documents_permissions'  # CHANGED: Unique related_name
    )
    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    role = models.CharField(
        max_length=50, 
        choices=OrganizationMembership.ROLE_CHOICES, 
        null=True, 
        blank=True
    )
    permission_type = models.CharField(
        max_length=10, 
        choices=PERMISSION_CHOICES
    )
    granted_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE,
        related_name='documents_granted_permissions'  # CHANGED: Unique related_name
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('document', 'user', 'permission_type') 
        verbose_name = "Document Permission"
        verbose_name_plural = "Document Permissions"
        
    def __str__(self):
        target = self.user.email if self.user else self.role
        return f"{target} - {self.get_permission_type_display()} on {self.document.title}"


# --- 5. Document Comment Model ---
class DocumentComment(models.Model):
    """Comments and discussions on documents."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='documents_comments'  # CHANGED: Unique related_name
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='documents_document_comments'  # CHANGED: Unique related_name
    )
    comment = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal comment (not visible to external parties)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "Document Comment"
        verbose_name_plural = "Document Comments"

    def __str__(self):
        return f"Comment by {self.user.email} on {self.document.title}"


# --- 6. Document Version Model ---
class DocumentVersion(models.Model):
    """Tracks version history of documents."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='documents_versions'  # CHANGED: Unique related_name
    )
    version_number = models.IntegerField()
    content = models.TextField()
    changes = models.TextField(
        blank=True,
        help_text="Description of changes in this version"
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='documents_created_versions'  # CHANGED: Unique related_name
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('document', 'version_number')
        ordering = ['document', '-version_number']
        verbose_name = "Document Version"
        verbose_name_plural = "Document Versions"

    def __str__(self):
        return f"v{self.version_number} of {self.document.title}"


# --- 7. Document Share Model ---
class DocumentShare(models.Model):
    """Tracks document sharing with external parties."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='documents_shares'  # CHANGED: Unique related_name
    )
    share_token = models.CharField(
        max_length=64,
        unique=True,
        default=uuid.uuid4,
        help_text="Unique token for external sharing"
    )
    shared_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='documents_shared_documents'  # CHANGED: Unique related_name
    )
    shared_with_email = models.EmailField(
        blank=True,
        help_text="Email of person document is shared with"
    )
    permission_type = models.CharField(
        max_length=10,
        choices=DocumentPermission.PERMISSION_CHOICES,
        default=DocumentPermission.PERMISSION_VIEW
    )
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accessed_at = models.DateTimeField(null=True, blank=True)
    access_count = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Document Share"
        verbose_name_plural = "Document Shares"
        indexes = [
            models.Index(fields=['share_token']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"Share: {self.document.title} with {self.shared_with_email}"


# --- 8. Collaboration Models ---
class DocumentSession(models.Model):
    """Tracks active editing sessions"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='documents_sessions')  # CHANGED
    session_id = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='documents_sessions')  # CHANGED
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session {self.session_id} for {self.document.title}"

class CollaborationCursor(models.Model):
    """Tracks user cursor positions in real-time"""
    session = models.ForeignKey(DocumentSession, on_delete=models.CASCADE, related_name='documents_cursors')  # CHANGED
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='documents_cursors')  # CHANGED
    position = models.IntegerField(default=0)
    selection_range = models.JSONField(null=True, blank=True)
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'user')

    def __str__(self):
        return f"Cursor for {self.user.email} in session {self.session.session_id}"

class OperationalTransform(models.Model):
    """For conflict resolution in collaborative editing"""
    session = models.ForeignKey(DocumentSession, on_delete=models.CASCADE, related_name='documents_operations')  # CHANGED
    version = models.IntegerField()
    operation = models.JSONField()
    applied_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='documents_operations')  # CHANGED
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'version')
        ordering = ['session', 'version']

    def __str__(self):
        return f"OT v{self.version} for session {self.session.session_id}"