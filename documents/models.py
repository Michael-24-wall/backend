from django.db import models
from django.conf import settings
from core.models import Organization, CustomUser, OrganizationMembership

# --- 1. Document Template Model ---
class DocumentTemplate(models.Model):
    """Defines a blueprint for creating new documents (e.g., 'Employment Contract')."""
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='templates',
        help_text="The organization this template belongs to."
    )
    name = models.CharField(max_length=255, help_text="Template name (e.g., 'Employment Contract')")
    title = models.CharField(max_length=255, blank=True, help_text="Display title (optional)")
    description = models.TextField(blank=True, help_text="Template description and usage notes")
    
    # Stores the structure/content (HTML or placeholder text) for generation
    content = models.TextField(
        help_text="HTML/Markdown content with placeholders (e.g., {{user.first_name}})."
    )
    content_template = models.TextField(
        blank=True,
        help_text="Legacy field - use 'content' instead."
    )
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_templates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensures each organization has uniquely named templates
        unique_together = ('organization', 'name') 
        verbose_name = "Document Template"
        ordering = ['name']
        
    def __str__(self):
        return f"{self.name} ({self.organization.name})"
    
    def save(self, *args, **kwargs):
        # Backward compatibility: copy content to content_template if empty
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
        (STATUS_DRAFT, 'Draft'),                         # Still being edited
        (STATUS_PENDING_REVIEW, 'Pending Review'),       # Waiting for review
        (STATUS_PENDING_APPROVAL, 'Pending Approval'),   # Waiting for approval
        (STATUS_PENDING_FINAL_SIGNATURE, 'Pending Final Signature'), # Waiting for final signature
        (STATUS_SIGNED, 'Signed/Final'),                 # Finalized and signed
        (STATUS_ARCHIVED, 'Archived'),                   # Archived/completed
        (STATUS_REJECTED, 'Rejected'),                   # Rejected in workflow
    ]

    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='documents'
    )
    template = models.ForeignKey(
        DocumentTemplate, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        related_name='documents'
    )
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES, 
        default=STATUS_DRAFT
    )
    
    # Stores the generated, finalized HTML content (after placeholder substitution)
    final_content = models.TextField(
        null=True, 
        blank=True,
        help_text="The rendered HTML content of the document instance."
    )
    
    # Link to the associated PDF/file
    file_attachment = models.FileField(
        upload_to='documents/%Y/%m/',
        null=True, 
        blank=True,
        help_text="The final PDF or file representation."
    )
    file_description = models.CharField(
        max_length=255,
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
        related_name='authored_documents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Metadata fields
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
        # Update file_size when file_attachment changes
        if self.file_attachment and not self.file_size:
            self.file_size = self.file_attachment.size
        super().save(*args, **kwargs)


# --- 3. Digital Signature Log Model ---
class DigitalSignatureLog(models.Model):
    """Records a single digital signature/approval action on a document."""
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='signatures'
    )
    signer = models.ForeignKey(
        CustomUser, 
        on_delete=models.PROTECT,
        related_name='document_signatures'
    )
    
    signed_at = models.DateTimeField(auto_now_add=True)
    signer_role = models.CharField(max_length=50)
    
    # Enhanced signature fields
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
    
    # Security fields
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
        # Prevents one person from signing the same document multiple times
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
        related_name='permissions'
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
        related_name='granted_document_permissions'
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        # Allows for flexible permissions (user or role-based)
        unique_together = ('document', 'user', 'permission_type') 
        verbose_name = "Document Permission"
        verbose_name_plural = "Document Permissions"
        
    def __str__(self):
        target = self.user.email if self.user else self.role
        return f"{target} - {self.get_permission_type_display()} on {self.document.title}"


# --- 5. NEW: Document Comment Model ---
class DocumentComment(models.Model):
    """Comments and discussions on documents."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='documents_document_comments'  # Fixed: unique related_name
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


# --- 6. NEW: Document Version Model ---
class DocumentVersion(models.Model):
    """Tracks version history of documents."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='versions'
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
        related_name='created_document_versions'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('document', 'version_number')
        ordering = ['document', '-version_number']
        verbose_name = "Document Version"
        verbose_name_plural = "Document Versions"

    def __str__(self):
        return f"v{self.version_number} of {self.document.title}"


# --- 7. NEW: Document Share Model ---
class DocumentShare(models.Model):
    """Tracks document sharing with external parties."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='shares'
    )
    share_token = models.CharField(
        max_length=64,
        unique=True,
        help_text="Unique token for external sharing"
    )
    shared_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='shared_documents'
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