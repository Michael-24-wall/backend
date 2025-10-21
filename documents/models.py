# documents/models.py

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
    title = models.CharField(max_length=255)
    # Stores the structure/content (HTML or placeholder text) for generation
    content_template = models.TextField(
        help_text="HTML/Markdown content with placeholders (e.g., {{user.first_name}})."
    )
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_templates')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Ensures each organization has uniquely named templates
        unique_together = ('organization', 'title') 
        verbose_name = "Document Template"
        
    def __str__(self):
        return f"{self.title} ({self.organization.name})"


# --- 2. Document Model (The Instance) ---
class Document(models.Model):
    """An actual generated document instance derived from a template."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),             # Still being edited
        ('pending', 'Pending Approval'), # Entered a workflow
        ('signed', 'Signed/Final'),     # Finalized and archived
        ('rejected', 'Rejected'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    template = models.ForeignKey(DocumentTemplate, on_delete=models.SET_NULL, null=True)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='draft')
    
    # Stores the generated, finalized HTML content (after placeholder substitution)
    final_content = models.TextField(
        null=True, blank=True,
        help_text="The rendered HTML content of the document instance."
    )
    
    # Link to the associated PDF/file
    # This stores the path (e.g., S3 URL or local path)
    file_attachment = models.FileField(
        upload_to='documents/%Y/%m/',
        null=True, blank=True,
        help_text="The final PDF or file representation."
    )
    
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='authored_documents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Doc: {self.title} ({self.status})"


# --- 3. Digital Signature Log Model ---
class DigitalSignatureLog(models.Model):
    """Records a single digital signature/approval action on a document."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='signatures')
    signer = models.ForeignKey(CustomUser, on_delete=models.PROTECT) # Don't delete signer if they sign documents
    
    signed_at = models.DateTimeField(auto_now_add=True)
    # The role the user signed in (e.g., 'CEO', 'HR')
    signer_role = models.CharField(max_length=50) 
    
    # Optional: store the hash of the document content at the time of signing
    content_hash = models.CharField(max_length=64, null=True, blank=True, help_text="SHA256 hash of the document's content at the time of signing.")
    
    class Meta:
        # Prevents one person from signing the same document multiple times (unless specific workflow allows)
        unique_together = ('document', 'signer')
        verbose_name = "Digital Signature Log"
        
    def __str__(self):
        return f"Signed by {self.signer.email} on {self.document.title}"

# --- 4. Document Permission Model (Optional, for fine-grained access) ---
class DocumentPermission(models.Model):
    """Defines who can view/edit/sign a specific document instance."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='permissions')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    # We could also grant permission based on role within the organization
    role = models.CharField(max_length=50, choices=OrganizationMembership.ROLE_CHOICES, null=True, blank=True)
    
    PERMISSION_CHOICES = [
        ('view', 'Can View'),
        ('edit', 'Can Edit'),
        ('sign', 'Can Sign'),
    ]
    permission_type = models.CharField(max_length=10, choices=PERMISSION_CHOICES)
    
    class Meta:
        # Allows for flexible permissions (user or role-based)
        unique_together = ('document', 'user', 'permission_type') 
        
    def __str__(self):
        target = self.user.email if self.user else self.role
        return f"{target} - {self.get_permission_type_display()} on {self.document.title}"