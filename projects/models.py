from django.db import models
from django.conf import settings
from core.models import Organization  # Assuming Organization model is in core/models.py
from django.utils import timezone
from datetime import timedelta

# Get the custom user model
User = settings.AUTH_USER_MODEL


class Project(models.Model):
    """
    Represents a multi-tenant project within an organization.
    """
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    # --- Multi-tenancy Link ---
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='projects',
        help_text="The organization this project belongs to."
    )

    # --- Core Fields ---
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='planning'
    )

    # --- Dates and Tracking ---
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)

    # --- Project Management ---
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_projects'
    )

    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensures no two projects have the same name within the same organization
        unique_together = ('organization', 'name')
        ordering = ['status', 'end_date']
        verbose_name = "Project"
        verbose_name_plural = "Projects"

    def __str__(self):
        return f"{self.organization.name} - {self.name} ({self.status})"

    def is_overdue(self):
        """Checks if the project is past its due date and not completed."""
        return self.end_date and self.end_date < timezone.now().date() and self.status not in ['completed', 'cancelled']


class Task(models.Model):
    """
    Represents an individual task belonging to a project.
    """
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('review', 'Review'),
        ('completed', 'Completed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    # --- Links ---
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks'
    )

    # --- Core Fields ---
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='todo'
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )

    # --- Dates and Tracking ---
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'priority']
        verbose_name = "Task"
        verbose_name_plural = "Tasks"

    def __str__(self):
        return f"[{self.project.name}] {self.title} ({self.status})"

    def is_overdue(self):
        """Checks if the task is past its due date and not completed."""
        return self.due_date and self.due_date < timezone.now().date() and self.status != 'completed'

    def save(self, *args, **kwargs):
        """Sets completed_at timestamp when status is set to 'completed'."""
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != 'completed' and self.completed_at:
            self.completed_at = None  # Clear timestamp if reverted from completed
        super().save(*args, **kwargs)


class Document(models.Model):
    """
    Represents a document associated with a project or task.
    """
    DOCUMENT_TYPES = [
        ('contract', 'Contract'),
        ('proposal', 'Proposal'),
        ('report', 'Report'),
        ('agreement', 'Agreement'),
        ('specification', 'Specification'),
        ('meeting_minutes', 'Meeting Minutes'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_review', 'In Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('final', 'Final'),
    ]

    # --- Links ---
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='documents',
        help_text="The organization this document belongs to."
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='documents',
        null=True,
        blank=True,
        help_text="Optional project this document is associated with."
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='documents',
        null=True,
        blank=True,
        help_text="Optional task this document is associated with."
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_documents'
    )

    # --- Core Fields ---
    title = models.CharField(max_length=255)
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        default='other'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )
    content = models.TextField(blank=True, help_text="Main content of the document")
    version = models.PositiveIntegerField(default=1)
    file = models.FileField(
        upload_to='documents/%Y/%m/%d/',
        null=True,
        blank=True,
        help_text="Uploaded file version of the document"
    )

    # --- Signature Requirements ---
    requires_signatures = models.BooleanField(default=False)
    signature_required_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of signatures required for this document"
    )

    # --- Dates ---
    effective_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)

    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        unique_together = ('organization', 'title', 'version')

    def __str__(self):
        return f"{self.title} v{self.version} ({self.document_type})"

    def is_signed(self):
        """Check if the document has all required signatures."""
        if not self.requires_signatures:
            return True
        return self.signatures.filter(is_signed=True).count() >= self.signature_required_count

    def get_signature_status(self):
        """Get signature status summary."""
        total_signatures = self.signatures.count()
        signed_count = self.signatures.filter(is_signed=True).count()
        return {
            'required': self.signature_required_count,
            'signed': signed_count,
            'pending': total_signatures - signed_count,
            'completed': self.is_signed()
        }

    def is_expired(self):
        """Check if the document has expired."""
        return self.expiration_date and self.expiration_date < timezone.now().date()

    def save(self, *args, **kwargs):
        """Handle versioning and status updates."""
        # If this is a new document and requires signatures, set up signature requirements
        if not self.pk and self.requires_signatures and self.signature_required_count == 0:
            self.signature_required_count = 1  # Default to 1 if not specified

        super().save(*args, **kwargs)


class Signature(models.Model):
    """
    Represents a signature on a document.
    """
    SIGNATURE_TYPES = [
        ('digital', 'Digital Signature'),
        ('handwritten', 'Handwritten Signature'),
        ('electronic', 'Electronic Consent'),
        ('clickwrap', 'Clickwrap Agreement'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('signed', 'Signed'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    # --- Links ---
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='signatures'
    )
    signatory = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='signatures'
    )

    # --- Signature Details ---
    signature_type = models.CharField(
        max_length=20,
        choices=SIGNATURE_TYPES,
        default='electronic'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    is_signed = models.BooleanField(default=False)

    # --- Signature Data ---
    signature_data = models.TextField(
        blank=True,
        help_text="Actual signature data (encrypted signature, image path, etc.)"
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address where the document was signed"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="User agent of the browser used for signing"
    )

    # --- Dates ---
    sent_at = models.DateTimeField(auto_now_add=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Signature request expiration date"
    )

    # --- Additional Fields ---
    decline_reason = models.TextField(
        blank=True,
        help_text="Reason for declining to sign"
    )
    signature_order = models.PositiveIntegerField(
        default=0,
        help_text="Order in which signatures should be collected"
    )

    class Meta:
        ordering = ['signature_order', 'sent_at']
        verbose_name = "Signature"
        verbose_name_plural = "Signatures"
        unique_together = ('document', 'signatory')

    def __str__(self):
        return f"{self.signatory.get_full_name()} - {self.document.title} ({self.status})"

    def is_expired(self):
        """Check if the signature request has expired."""
        return self.expires_at and self.expires_at < timezone.now()

    def can_sign(self):
        """Check if the signature can be provided (not expired and pending)."""
        return self.status == 'pending' and not self.is_expired()

    def sign(self, signature_data, ip_address=None, user_agent=None):
        """Process signature for this request."""
        if not self.can_sign():
            return False

        self.signature_data = signature_data
        self.is_signed = True
        self.status = 'signed'
        self.signed_at = timezone.now()
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.save()
        return True

    def decline(self, reason=""):
        """Decline to sign the document."""
        if self.status != 'pending':
            return False

        self.status = 'declined'
        self.decline_reason = reason
        self.signed_at = timezone.now()
        self.save()
        return True

    def save(self, *args, **kwargs):
        """Set expiration date if not provided and sync is_signed with status."""
        # Set default expiration (30 days from sending)
        if not self.expires_at and not self.pk:
            self.expires_at = timezone.now() + timedelta(days=30)

        # Sync is_signed with status
        self.is_signed = self.status == 'signed'

        super().save(*args, **kwargs)


class DocumentTemplate(models.Model):
    """
    Represents a reusable document template.
    """
    TEMPLATE_TYPES = [
        ('contract', 'Contract'),
        ('proposal', 'Proposal'),
        ('report', 'Report'),
        ('agreement', 'Agreement'),
        ('form', 'Form'),
    ]

    # --- Links ---
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='document_templates'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_templates'
    )

    # --- Core Fields ---
    name = models.CharField(max_length=255)
    template_type = models.CharField(
        max_length=20,
        choices=TEMPLATE_TYPES,
        default='contract'
    )
    content = models.TextField(help_text="Template content with variables")
    description = models.TextField(blank=True)

    # --- Metadata ---
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Document Template"
        verbose_name_plural = "Document Templates"
        unique_together = ('organization', 'name')

    def __str__(self):
        return f"{self.name} ({self.template_type})"

    def create_document_from_template(self, title, created_by, project=None, task=None, **context):
        """Create a new document from this template with context variables."""
        from django.template import Template, Context

        template = Template(self.content)
        context = Context(context)
        rendered_content = template.render(context)

        document = Document.objects.create(
            organization=self.organization,
            project=project,
            task=task,
            created_by=created_by,
            title=title,
            document_type=self.template_type,
            content=rendered_content,
            requires_signatures=self.template_type in ['contract', 'agreement']
        )

        return document