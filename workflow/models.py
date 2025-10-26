from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q

# Import your actual models - adjust these imports based on your project structure
from core.models import Organization, OrganizationMembership
from documents.models import Document


class ApprovalWorkflow(models.Model):
    """
    Defines a reusable, named sequence of approval steps for an organization.
    This is the blueprint (e.g., 'Expense Report Flow').
    """
    organization = models.ForeignKey(
        Organization,
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
        """Validate workflow data"""
        if not self.organization:
            raise ValidationError("Workflow must belong to an organization")
        
        # Ensure unique name within organization (handled by unique_together but nice to have in clean)
        if ApprovalWorkflow.objects.filter(
            organization=self.organization, 
            name=self.name
        ).exclude(pk=self.pk).exists():
            raise ValidationError(f"A workflow with name '{self.name}' already exists in this organization")

    def get_steps_count(self):
        """Return number of steps in this workflow"""
        return self.template_steps.count()

    def can_delete(self):
        """Check if workflow can be safely deleted (not in use)"""
        return not self.document_approval_flows.exists()


class WorkflowTemplateStep(models.Model):
    """
    A single stage in an ApprovalWorkflow template, defining the required role 
    and conditional routing options.
    """
    
    # Define role choices locally to avoid dependency issues
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('contributor', 'Contributor'),
        ('manager', 'Manager'),
        ('admin', 'Administrator'),
        ('owner', 'Owner'),
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
    
    # Conditional Routing Logic: Maps the approver's decision key to the next step's order number
    # Example: {"approve": 2, "reject": 0, "escalate": 3} where 0 = end workflow
    next_step_routes = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON mapping of decision keys to subsequent step_order numbers. Use 0 to end workflow."
    )
    
    # Optional: Timeout for this step (in days)
    timeout_days = models.PositiveIntegerField(
        default=7,
        help_text="Number of days before this step is considered overdue"
    )
    
    # Whether multiple approvers with this role are required
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
        """Validate step data"""
        if self.step_order < 1:
            raise ValidationError("Step order must be a positive integer")
        
        # Validate next_step_routes structure
        if self.next_step_routes:
            if not isinstance(self.next_step_routes, dict):
                raise ValidationError("next_step_routes must be a JSON object")
            
            # Get valid step orders for this workflow
            valid_orders = list(self.workflow.template_steps.values_list('step_order', flat=True))
            if self.pk:  # Exclude self if updating
                valid_orders = [order for order in valid_orders if order != self.step_order]
            
            valid_orders.append(0)  # 0 means end workflow
            
            for decision_key, target_step in self.next_step_routes.items():
                if not isinstance(target_step, int):
                    raise ValidationError(f"Route target for '{decision_key}' must be an integer")
                if target_step not in valid_orders:
                    raise ValidationError(
                        f"Route '{decision_key}' points to invalid step {target_step}. "
                        f"Valid steps: {sorted(valid_orders)}"
                    )

    def get_next_step(self, decision_key='default'):
        """Get the next step based on decision"""
        if decision_key in self.next_step_routes:
            next_order = self.next_step_routes[decision_key]
        else:
            # Default linear progression
            next_order = self.step_order + 1
        
        if next_order == 0:  # End workflow
            return None
        
        try:
            return WorkflowTemplateStep.objects.get(
                workflow=self.workflow,
                step_order=next_order
            )
        except WorkflowTemplateStep.DoesNotExist:
            return None

    def get_potential_approvers(self, document):
        """Get users who could approve this step for a given document"""
        # This would depend on your organization structure
        # Example implementation:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Get users with the required role in the document's organization
        organization_memberships = OrganizationMembership.objects.filter(
            organization=document.organization,
            role=self.approver_role
        )
        return User.objects.filter(organization_memberships__in=organization_memberships)


class DocumentApprovalFlow(models.Model):
    """
    Tracks the current state of a specific Document within its assigned workflow.
    This is the active instance tracker.
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE, 
        related_name='approval_flow'
    )
    workflow_template = models.ForeignKey(
        ApprovalWorkflow, 
        on_delete=models.PROTECT, 
        help_text="The template this flow is based on."
    )
    
    # Current state
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
    
    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    current_step_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
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
        """Validate flow data"""
        if self.document.organization != self.workflow_template.organization:
            raise ValidationError("Document organization must match workflow organization")

    def save(self, *args, **kwargs):
        """Override save to handle auto-timestamps and status sync"""
        if self.is_complete and not self.completed_at:
            self.completed_at = timezone.now()
            if self.is_approved:
                self.status = 'approved'
            else:
                self.status = 'rejected'
        
        # Sync boolean fields with status
        if self.status in ['approved', 'rejected', 'cancelled']:
            self.is_complete = True
            self.is_approved = (self.status == 'approved')
        else:
            self.is_complete = False
            self.is_approved = False
        
        super().save(*args, **kwargs)

    def start_workflow(self):
        """Initialize the workflow - start with first step"""
        first_step = self.workflow_template.template_steps.filter(step_order=1).first()
        if not first_step:
            raise ValidationError("Workflow template has no steps")
        
        self.current_template_step = first_step
        self.current_step_started_at = timezone.now()
        self.status = 'in_progress'
        self.assign_approver()
        self.save()

    def assign_approver(self):
        """Assign an approver for the current step"""
        if not self.current_template_step:
            return
        
        potential_approvers = self.current_template_step.get_potential_approvers(self.document)
        if potential_approvers.exists():
            # For now, assign the first available approver
            # You might want more sophisticated logic here
            self.current_approver = potential_approvers.first()
            
            # Set deadline
            if self.current_template_step.timeout_days:
                self.current_deadline = timezone.now() + timezone.timedelta(
                    days=self.current_template_step.timeout_days
                )
        else:
            # No approver available - might want to handle this case
            self.current_approver = None

    def process_approval(self, user, decision_key='approve', comments=''):
        """Process an approval decision and move to next step"""
        if self.is_complete:
            raise ValidationError("Workflow is already complete")
        
        if user != self.current_approver:
            raise ValidationError("User is not the current approver")
        
        # Log the action
        action_type = 'approve' if decision_key == 'approve' else 'route'
        WorkflowLog.objects.create(
            document=self.document,
            template_step=self.current_template_step,
            actor=user,
            action_type=action_type,
            comments=comments
        )
        
        # Get next step
        next_step = self.current_template_step.get_next_step(decision_key)
        
        if next_step:
            # Move to next step
            self.current_template_step = next_step
            self.current_step_started_at = timezone.now()
            self.assign_approver()
        else:
            # Workflow complete
            self.complete_workflow(approved=(decision_key == 'approve'))
        
        self.save()

    def process_rejection(self, user, comments=''):
        """Process a rejection and end workflow"""
        if self.is_complete:
            raise ValidationError("Workflow is already complete")
        
        if user != self.current_approver:
            raise ValidationError("User is not the current approver")
        
        # Log the rejection
        WorkflowLog.objects.create(
            document=self.document,
            template_step=self.current_template_step,
            actor=user,
            action_type='reject',
            comments=comments
        )
        
        # End workflow with rejection
        self.complete_workflow(approved=False)
        self.save()

    def complete_workflow(self, approved=True):
        """Mark workflow as complete"""
        self.is_complete = True
        self.is_approved = approved
        self.status = 'approved' if approved else 'rejected'
        self.completed_at = timezone.now()
        self.current_template_step = None
        self.current_approver = None
        self.current_deadline = None

    def get_current_step_deadline(self):
        """Calculate deadline for current step"""
        if self.current_template_step and self.current_step_started_at:
            return self.current_step_started_at + timezone.timedelta(
                days=self.current_template_step.timeout_days
            )
        return None

    def is_overdue(self):
        """Check if current step is overdue"""
        deadline = self.get_current_step_deadline()
        return deadline and timezone.now() > deadline

    def get_progress_percentage(self):
        """Calculate workflow progress as percentage"""
        total_steps = self.workflow_template.template_steps.count()
        if not self.current_template_step or total_steps == 0:
            return 0
        
        current_step_order = self.current_template_step.step_order
        return int((current_step_order - 1) / total_steps * 100)


class WorkflowLog(models.Model):
    """
    Records every action taken (Approval, Rejection, Routing) throughout the workflow's history.
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
        Document,
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
    action_type = models.CharField(
        max_length=50, 
        choices=ACTION_CHOICES
    )
    decision_key = models.CharField(
        max_length=100,
        blank=True,
        help_text="The specific decision route taken (e.g., 'approve', 'escalate')"
    )
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Additional context
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
        """Set from_step based on template_step if not provided"""
        if not self.from_step and self.template_step:
            self.from_step = self.template_step
        super().save(*args, **kwargs)


# Signal handlers for automation
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=DocumentApprovalFlow)
def handle_workflow_creation(sender, instance, created, **kwargs):
    """Automatically start workflow when created"""
    if created and not instance.current_template_step:
        instance.start_workflow()


@receiver(post_save, sender=WorkflowTemplateStep)
def validate_step_routes(sender, instance, **kwargs):
    """Validate step routes after save"""
    try:
        instance.clean()
    except ValidationError as e:
        # Log error or handle as needed
        pass