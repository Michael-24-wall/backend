# workflow/models.py
from django.db import models
from django.conf import settings
# REMOVED: from documents.models import Document  # This causes circular import

class ApprovalStep(models.Model):
    """
    Represents a single step in a document's approval workflow.
    """
    
    # Status Choices
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SKIPPED', 'Skipped'),
    ]

    document = models.ForeignKey(
        'documents.Document',  # CHANGED: Use string reference instead of direct import
        on_delete=models.CASCADE, 
        related_name='approval_steps',
        help_text="The document this step belongs to."
    )
    
    # The user who is responsible for this approval step
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='workflow_steps'
    )
    
    order = models.IntegerField(
        help_text="The sequence number for this step (e.g., 1, 2, 3)."
    )
    
    status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default='PENDING',
        help_text="Current status of the approval step."
    )
    
    notes = models.TextField(
        blank=True, 
        null=True,
        help_text="Comments or feedback from the approver."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensures each document has a unique sequence of steps
        unique_together = ('document', 'order') 
        ordering = ['document', 'order']
        verbose_name_plural = "Approval Steps"

    def __str__(self):
        return f"Step {self.order} for {self.document.title} - {self.approver.username}"