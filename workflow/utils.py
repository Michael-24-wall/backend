# workflow/utils.py
import logging
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Avg, Q, F, ExpressionWrapper, DurationField
from datetime import timedelta

# DON'T import models at the top level to avoid circular imports
logger = logging.getLogger(__name__)

# Notification Utilities
def send_approval_notification(document_id):
    """Send notification when a document is fully approved"""
    try:
        # Import inside the function to avoid circular imports
        from documents.models import Document
        
        document = Document.objects.select_related(
            'created_by', 'organization', 'approval_flow'
        ).get(id=document_id)
        
        subject = f"Document Approved: {document.title}"
        
        context = {
            'document': document,
            'approval_date': timezone.now(),
            'user': document.created_by,
            'action': 'approved'
        }
        
        html_message = render_to_string('workflow/email/approval_notification.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[document.created_by.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Approval notification sent for document {document_id} to {document.created_by.email}")
        
    except Exception as e:
        logger.error(f"Failed to send approval notification for document {document_id}: {str(e)}")

def send_rejection_notification(document_id, rejection_reason="", rejected_by=None):
    """Send notification when a document is rejected"""
    try:
        # Import inside the function to avoid circular imports
        from documents.models import Document
        
        document = Document.objects.select_related(
            'created_by', 'organization', 'approval_flow'
        ).get(id=document_id)
        
        subject = f"Document Rejected: {document.title}"
        
        # Build resubmission URL for frontend
        resubmission_url = settings.FRONTEND_URL + f"/documents/{document.id}/resubmit"
        
        context = {
            'document': document,
            'rejection_date': timezone.now(),
            'rejection_reason': rejection_reason,
            'rejected_by': rejected_by,
            'user': document.created_by,
            'action': 'rejected',
            'resubmission_url': resubmission_url,
        }
        
        html_message = render_to_string('workflow/email/rejection_notification.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[document.created_by.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Rejection notification sent for document {document_id} to {document.created_by.email}")
        
    except Exception as e:
        logger.error(f"Failed to send rejection notification for document {document_id}: {str(e)}")

def send_pending_approval_notification(flow_id):
    """Send notification to the next approver"""
    try:
        # Import inside the function
        from .models import DocumentApprovalFlow
        
        flow = DocumentApprovalFlow.objects.select_related(
            'document', 'current_approver', 'current_template_step', 'document__created_by'
        ).get(id=flow_id)
        
        if not flow.current_approver:
            logger.warning(f"No current approver for flow {flow_id}")
            return
        
        subject = f"Action Required: Approval Pending for {flow.document.title}"
        
        approval_url = settings.FRONTEND_URL + f"/approvals/{flow.id}"
        
        context = {
            'document': flow.document,
            'flow': flow,
            'approver': flow.current_approver,
            'step': flow.current_template_step,
            'submitted_by': flow.document.created_by,
            'approval_url': approval_url,
            'assigned_date': timezone.now(),
        }
        
        html_message = render_to_string('workflow/email/pending_approval.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[flow.current_approver.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Pending approval notification sent to {flow.current_approver.email} for flow {flow_id}")
        
    except Exception as e:
        logger.error(f"Failed to send pending approval notification for flow {flow_id}: {str(e)}")

# Workflow Statistics - FIXED VERSION
def get_workflow_statistics(organization_id, start_date=None, end_date=None):
    """Generate workflow statistics for an organization"""
    # Import inside the function
    from .models import DocumentApprovalFlow
    
    if not end_date:
        end_date = timezone.now()
    if not start_date:
        start_date = end_date - timedelta(days=30)
    
    flows = DocumentApprovalFlow.objects.filter(
        document__organization_id=organization_id,
        started_at__range=[start_date, end_date]
    )
    
    total_flows = flows.count()
    completed_flows = flows.filter(is_complete=True).count()
    approved_flows = flows.filter(is_approved=True).count()
    rejected_flows = flows.filter(is_complete=True, is_approved=False).count()
    pending_flows = flows.filter(is_complete=False).count()
    
    # FIXED: Calculate average completion time properly
    completed_with_time = flows.filter(
        is_complete=True, 
        completed_at__isnull=False,
        started_at__isnull=False
    )
    
    # Calculate average completion time in days
    avg_completion_days = None
    if completed_with_time.exists():
        total_days = 0
        count = 0
        
        for flow in completed_with_time:
            if flow.completed_at and flow.started_at:
                duration = flow.completed_at - flow.started_at
                total_days += duration.days
                count += 1
        
        if count > 0:
            avg_completion_days = round(total_days / count, 1)
    
    # Get overdue flows
    overdue_flows = flows.filter(
        is_complete=False,
        current_deadline__lt=timezone.now()
    ).count()
    
    # Get flows by status
    flows_by_status = flows.values('status').annotate(count=Count('id'))
    status_counts = {item['status']: item['count'] for item in flows_by_status}
    
    # Get flows by template
    flows_by_template = flows.values(
        'workflow_template__name'
    ).annotate(
        count=Count('id'),
        approved_count=Count('id', filter=Q(is_approved=True))
    )
    
    template_stats = []
    for item in flows_by_template:
        template_name = item['workflow_template__name'] or 'No Template'
        count = item['count']
        approved_count = item['approved_count']
        approval_rate = round((approved_count / count * 100), 1) if count > 0 else 0
        
        template_stats.append({
            'template_name': template_name,
            'count': count,
            'approval_rate': approval_rate
        })
    
    # Calculate approval rate
    approval_rate = 0
    if completed_flows > 0:
        approval_rate = round((approved_flows / completed_flows) * 100, 1)
    
    return {
        'total_flows': total_flows,
        'pending_flows': pending_flows,
        'completed_flows': completed_flows,
        'approved_flows': approved_flows,
        'rejected_flows': rejected_flows,
        'overdue_flows': overdue_flows,
        'approval_rate': approval_rate,
        'average_completion_time_days': avg_completion_days or 0,
        'by_status': status_counts,
        'by_template': template_stats
    }

def get_overdue_flows():
    """Get all flows that are overdue in their current step"""
    # Import inside the function
    from .models import DocumentApprovalFlow
    
    now = timezone.now()
    overdue_flows = DocumentApprovalFlow.objects.filter(
        is_complete=False,
        current_deadline__lt=now
    ).select_related('document', 'current_approver', 'current_template_step')
    
    return overdue_flows

# Validation Utilities
def validate_workflow_routes(workflow_id):
    """Validate that all routes in a workflow point to valid steps"""
    try:

        from .models import ApprovalWorkflow
        
        workflow = ApprovalWorkflow.objects.prefetch_related('template_steps').get(id=workflow_id)
        steps = workflow.template_steps.all()
        valid_orders = {step.step_order for step in steps}
        
        errors = []
        
        for step in steps:
            for decision, target_order in step.next_step_routes.items():
                if target_order != 0 and target_order not in valid_orders:
                    errors.append(
                        f"Step {step.step_order}: Route '{decision}' points to invalid step {target_order}"
                    )
        
        return len(errors) == 0, errors
        
    except Exception as e:
        return False, [f"Error validating workflow: {str(e)}"]

def can_user_approve_step(user, flow):
    """Check if a user can approve the current step of a flow"""
    if not hasattr(user, 'organizationmembership'):
        return False
    
    # Check if user is in the same organization
    try:
        user_org = user.organizationmembership.organization
        if user_org != flow.document.organization:
            return False
    except Exception:
        return False
    
    # User can approve if they are the current approver
    if flow.current_approver == user:
        return True
    
    # User can approve if they are an owner (owners can approve any step)
    user_role = user.organizationmembership.role.lower()
    if user_role == 'owner':
        return True
    
    # Check if user has the required role for this step
    required_role = flow.current_template_step.approver_role.lower()
    
    role_hierarchy = {
        'owner': 5,
        'admin': 4,
        'manager': 3,
        'staff': 2,
        'contributor': 1,
        'viewer': 0,
    }
    
    user_level = role_hierarchy.get(user_role, 0)
    required_level = role_hierarchy.get(required_role, 0)
    
    return user_level >= required_level

# Template Utilities
def create_default_workflow_templates(organization):
    """Create default workflow templates for a new organization"""
    from .models import ApprovalWorkflow, WorkflowTemplateStep
    
    # Simple 2-step approval
    simple_workflow = ApprovalWorkflow.objects.create(
        organization=organization,
        name="Standard Document Approval",
        description="Two-step approval process for general documents",
        is_active=True
    )
    
    WorkflowTemplateStep.objects.create(
        workflow=simple_workflow,
        approver_role="manager",
        step_order=1,
        next_step_routes={"approve": 2, "reject": 0},
        timeout_days=3
    )
    
    WorkflowTemplateStep.objects.create(
        workflow=simple_workflow,
        approver_role="admin",
        step_order=2,
        next_step_routes={"approve": 0, "reject": 0},
        timeout_days=2
    )
    
    # Complex 3-step approval for high-value items
    complex_workflow = ApprovalWorkflow.objects.create(
        organization=organization,
        name="High-Value Approval",
        description="Three-step approval for contracts over $10,000",
        is_active=True
    )
    
    WorkflowTemplateStep.objects.create(
        workflow=complex_workflow,
        approver_role="manager",
        step_order=1,
        next_step_routes={"approve": 2, "reject": 0},
        timeout_days=5
    )
    
    WorkflowTemplateStep.objects.create(
        workflow=complex_workflow,
        approver_role="admin",
        step_order=2,
        next_step_routes={"approve": 3, "reject": 0},
        timeout_days=3
    )
    
    WorkflowTemplateStep.objects.create(
        workflow=complex_workflow,
        approver_role="owner",
        step_order=3,
        next_step_routes={"approve": 0, "reject": 0},
        timeout_days=2
    )
    
    return [simple_workflow, complex_workflow]

# Deadline Management
def update_flow_deadlines():
    """Update deadlines for all active flows"""
    from .models import DocumentApprovalFlow
    
    active_flows = DocumentApprovalFlow.objects.filter(
        is_complete=False,
        current_template_step__isnull=False
    ).select_related('current_template_step')
    
    updated_count = 0
    
    for flow in active_flows:
        if not flow.current_deadline and flow.current_step_started_at:
            # Set deadline based on step timeout
            deadline = flow.current_step_started_at + timedelta(
                days=flow.current_template_step.timeout_days
            )
            flow.current_deadline = deadline
            flow.save()
            updated_count += 1
    
    return updated_count

def get_flows_near_deadline(days_threshold=1):
    """Get flows that are approaching their deadline"""
    from .models import DocumentApprovalFlow
    
    warning_date = timezone.now() + timedelta(days=days_threshold)
    
    near_deadline_flows = DocumentApprovalFlow.objects.filter(
        is_complete=False,
        current_deadline__lte=warning_date,
        current_deadline__gt=timezone.now()
    ).select_related('document', 'current_approver')
    
    return near_deadline_flows