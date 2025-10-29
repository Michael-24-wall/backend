from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from datetime import timedelta

class ApprovalWorkflow(models.Model):
    """
    Defines a reusable, named sequence of approval steps for an organization.
    """
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.CASCADE, 
        related_name='approval_workflows'
    )
    name = models.CharField(max_length=255, help_text="e.g., 'High-Value Expense Approval'")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Approval Workflow"
        verbose_name_plural = "Approval Workflows"
        unique_together = ('organization', 'name')
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]

    def __str__(self):
        return f"Workflow: {self.name} ({self.organization.name})"

    def clean(self):
        if not self.organization:
            raise ValidationError("Workflow must belong to an organization")

    def get_steps_count(self):
        return self.template_steps.count()

    def can_delete(self):
        return not self.document_approval_flows.exists()


class WorkflowTemplateStep(models.Model):
    """
    A single stage in an ApprovalWorkflow template.
    """
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('contributor', 'Contributor'),
        ('manager', 'Manager'),
        ('admin', 'Administrator'),
        ('owner', 'Owner'),
        ('staff', 'Staff'),  # ADDED: For view compatibility
    ]

    workflow = models.ForeignKey(
        ApprovalWorkflow, 
        on_delete=models.CASCADE, 
        related_name='template_steps'
    )
    approver_role = models.CharField(
        max_length=50, 
        choices=ROLE_CHOICES,
        help_text="The role required for approval at this step."
    )
    step_order = models.IntegerField(help_text="The sequence number (1, 2, 3...)")
    
    next_step_routes = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON mapping of decision keys to subsequent step_order numbers. Use 0 to end workflow."
    )
    
    timeout_days = models.PositiveIntegerField(
        default=7,
        help_text="Number of days before this step is considered overdue"
    )
    
    require_all_approvers = models.BooleanField(
        default=False,
        help_text="If True, all users with this role must approve. If False, any one can approve."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['step_order']
        unique_together = ('workflow', 'step_order')
        verbose_name = "Workflow Template Step"
        verbose_name_plural = "Workflow Template Steps"
        indexes = [
            models.Index(fields=['workflow', 'step_order']),
        ]

    def __str__(self):
        return f"{self.workflow.name} - Step {self.step_order} ({self.get_approver_role_display()})"

    def clean(self):
        if self.step_order < 1:
            raise ValidationError("Step order must be a positive integer")
        
        if self.next_step_routes:
            if not isinstance(self.next_step_routes, dict):
                raise ValidationError("next_step_routes must be a JSON object")
            
            valid_orders = list(self.workflow.template_steps.values_list('step_order', flat=True))
            if self.pk:
                valid_orders = [order for order in valid_orders if order != self.step_order]
            
            valid_orders.append(0)
            
            for decision_key, target_step in self.next_step_routes.items():
                if not isinstance(target_step, int):
                    raise ValidationError(f"Route target for '{decision_key}' must be an integer")
                if target_step not in valid_orders:
                    raise ValidationError(
                        f"Route '{decision_key}' points to invalid step {target_step}. "
                        f"Valid steps: {sorted(valid_orders)}"
                    )

    def get_next_step(self, decision_key='default'):
        if decision_key in self.next_step_routes:
            next_order = self.next_step_routes[decision_key]
        else:
            next_order = self.step_order + 1
        
        if next_order == 0:
            return None
        
        try:
            return WorkflowTemplateStep.objects.get(
                workflow=self.workflow,
                step_order=next_order
            )
        except WorkflowTemplateStep.DoesNotExist:
            return None

    # ADDED: Method to calculate deadline
    def calculate_deadline(self):
        return timezone.now() + timedelta(days=self.timeout_days)


class DocumentApprovalFlow(models.Model):
    """
    Tracks the current state of a specific Document within its assigned workflow.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    document = models.OneToOneField(
        'documents.Document',
        on_delete=models.CASCADE, 
        related_name='approval_flow'
    )
    workflow_template = models.ForeignKey(
        ApprovalWorkflow, 
        on_delete=models.PROTECT, 
        help_text="The template this flow is based on."
    )
    
    current_template_step = models.ForeignKey(
        WorkflowTemplateStep, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        help_text="The definition of the step currently awaiting action."
    )
    
    current_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='pending_approvals',
        help_text="The specific user assigned to approve this step."
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    is_complete = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    
    started_at = models.DateTimeField(auto_now_add=True)
    current_step_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    current_deadline = models.DateTimeField(null=True, blank=True)
    auto_escalate_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Document Approval Flow Instance"
        verbose_name_plural = "Document Approval Flow Instances"
        indexes = [
            models.Index(fields=['document', 'is_complete']),
            models.Index(fields=['current_approver', 'is_complete']),
            models.Index(fields=['status', 'current_deadline']),
        ]

    def __str__(self):
        status = self.get_status_display()
        current_step = self.current_template_step.step_order if self.current_template_step else 'N/A'
        return f"Flow for {self.document.title}: Step {current_step} ({status})"

    def clean(self):
        if self.document.organization != self.workflow_template.organization:
            raise ValidationError("Document organization must match workflow organization")

    def save(self, *args, **kwargs):
        # Set deadline when step changes
        if (self.current_template_step and self.current_step_started_at and 
            not self.current_deadline):
            self.current_deadline = self.current_template_step.calculate_deadline()
        
        if self.is_complete and not self.completed_at:
            self.completed_at = timezone.now()
            if self.is_approved:
                self.status = 'approved'
            else:
                self.status = 'rejected'
        
        if self.status in ['approved', 'rejected', 'cancelled']:
            self.is_complete = True
            self.is_approved = (self.status == 'approved')
        else:
            self.is_complete = False
            self.is_approved = False
        
        super().save(*args, **kwargs)

    def get_progress_percentage(self):
        """Calculate progress percentage"""
        total_steps = self.workflow_template.template_steps.count()
        if not self.current_template_step or total_steps == 0:
            return 0
        
        current_step_order = self.current_template_step.step_order
        return int((current_step_order - 1) / total_steps * 100)

    def get_status_display(self):
        """Get human-readable status"""
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    def is_overdue(self):
        if self.current_deadline:
            return timezone.now() > self.current_deadline
        return False

    # ADDED: Method to check if user can take action
    def user_can_take_action(self, user):
        """Check if user can approve/reject this flow"""
        if self.is_complete:
            return False
        if self.current_approver == user:
            return True
        
        # Allow organization owners to take action on any flow
        try:
            if hasattr(user, 'organizationmembership'):
                return user.organizationmembership.role.lower() == 'owner'
        except (AttributeError, ObjectDoesNotExist):
            pass
        
        return False


class WorkflowLog(models.Model):
    """
    Records every action taken throughout the workflow's history.
    """
    ACTION_CHOICES = [
        ('approve', 'Approved/Pushed Up'),
        ('reject', 'Rejected'),
        ('route', 'Decision Route Taken'),
        ('forward', 'Forwarded to New Approver'),
        ('escalate', 'Escalated'),
        ('delegate', 'Delegated'),
    ]

    document = models.ForeignKey(
        'documents.Document',
        on_delete=models.CASCADE, 
        related_name='workflow_logs'
    )
    template_step = models.ForeignKey(
        WorkflowTemplateStep, 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="The step definition this action relates to."
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        help_text="The user who took the action."
    )
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES)
    decision_key = models.CharField(max_length=100, blank=True, help_text="The specific decision route taken")
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    from_step = models.ForeignKey(
        WorkflowTemplateStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="The step this action was taken from"
    )
    to_step = models.ForeignKey(
        WorkflowTemplateStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="The step this action moved to"
    )

    class Meta:
        ordering = ['created_at']
        verbose_name = "Workflow Log"
        verbose_name_plural = "Workflow Logs"
        indexes = [
            models.Index(fields=['document', 'created_at']),
            models.Index(fields=['actor', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.get_action_type_display()}] by {self.actor.username} on {self.document.title}"

    def save(self, *args, **kwargs):
        if not self.from_step and self.template_step:
            self.from_step = self.template_step
        super().save(*args, **kwargs)


# Chat Integration Models
class ApprovalChatRoom(models.Model):
    """Links approval flows to chat rooms"""
    approval_flow = models.OneToOneField(
        DocumentApprovalFlow, 
        on_delete=models.CASCADE, 
        related_name='chat_room_link'
    )
    chat_room = models.ForeignKey('chat.ChatRoom', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['approval_flow']),
        ]

    def __str__(self):
        return f"Chat for {self.approval_flow.document.title}"


class WorkflowMessageContext(models.Model):
    """Adds workflow context to chat messages"""
    message = models.OneToOneField('chat.Message', on_delete=models.CASCADE)
    workflow_action = models.CharField(max_length=50, blank=True)
    related_step = models.ForeignKey(WorkflowTemplateStep, on_delete=models.SET_NULL, null=True)
    is_urgent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['related_step']),
        ]

    def __str__(self):
        return f"Context for message {self.message.id}"