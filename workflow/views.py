from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

# --- Model/Serializer Imports ---
from .models import (
    ApprovalWorkflow, WorkflowTemplateStep, 
    DocumentApprovalFlow, WorkflowLog
)
from documents.models import Document 
from core.models import OrganizationMembership, CustomUser 
from .serializers import (
    DocumentApprovalFlowSerializer, WorkflowLogSerializer, 
    ApprovalActionSerializer, ApprovalWorkflowSerializer
)

# --- NEW: Utility Import ---
from .utils import send_approval_notification # <--- ADDED THE IMPORT

# --- NEW: Helper Function for Finding Next Approver ---
def find_approver_for_role(organization, role_name):
    """Finds the first active user with the specified role in the organization."""
    try:
        membership = OrganizationMembership.objects.get(
            organization=organization,
            role=role_name,
            is_active=True
        )
        return membership.user
    except OrganizationMembership.DoesNotExist:
        return None

# --------------------------------------------------------------------------------------
# A. Document Submission View (Phase 2)
# --------------------------------------------------------------------------------------

class DocumentSubmissionViewSet(viewsets.GenericViewSet):
    """
    Handles the submission of a new document/request, initiating the workflow.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = DocumentApprovalFlowSerializer 

    @action(detail=False, methods=['post'], url_path='submit')
    def submit_request(self, request):
        """Staff endpoint for submitting a request with file and initiating workflow."""
        user = request.user
        org = user.organizationmembership.organization 

        # 1. Validation and Workflow Setup
        workflow_name = request.data.get('workflow_name')
        initial_approver_id = request.data.get('initial_approver_id')
        file_attachment = request.FILES.get('file_attachment')
        title = request.data.get('title')

        if not all([workflow_name, initial_approver_id, file_attachment, title]):
            return Response({"detail": "Missing required fields (title, file_attachment, initial_approver_id, workflow_name)."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            workflow_template = ApprovalWorkflow.objects.get(organization=org, name=workflow_name)
            initial_approver = CustomUser.objects.get(pk=initial_approver_id)
            first_step = workflow_template.template_steps.order_by('step_order').first()
        except (ApprovalWorkflow.DoesNotExist, CustomUser.DoesNotExist, WorkflowTemplateStep.DoesNotExist) as e:
            return Response({"detail": f"Workflow or Approver not found: {e}"}, status=status.HTTP_404_NOT_FOUND)

        # 2. Check Staff Visibility Logic 
        try:
            if initial_approver.organizationmembership.role != 'manager':
                 return Response({"detail": "Initial approver must be a Manager."}, status=status.HTTP_403_FORBIDDEN)
        except OrganizationMembership.DoesNotExist:
            return Response({"detail": "Initial approver does not have a role in the organization."}, status=status.HTTP_403_FORBIDDEN)


        # 3. Transactional Creation of Document and Workflow
        with transaction.atomic():
            document = Document.objects.create(
                organization=org,
                title=title,
                created_by=user,
                status=Document.STATUS_PENDING_REVIEW,
                file_attachment=file_attachment,
                file_description=f"Initial submission file for {title}",
            )
            
            flow = DocumentApprovalFlow.objects.create(
                document=document,
                workflow_template=workflow_template,
                current_template_step=first_step,
                current_approver=initial_approver,
            )
            
            WorkflowLog.objects.create(
                document=document,
                actor=user,
                action_type='route',
                comments=f"Document submitted and routed to {initial_approver.username}.",
            )

        # 4. Success Response
        return Response(DocumentApprovalFlowSerializer(flow).data, status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------------------
# B. Workflow Action View (Phase 3 & 4)
# --------------------------------------------------------------------------------------

class WorkflowActionViewSet(viewsets.GenericViewSet):
    """
    Handles listing pending approvals, processing approval action, rejection, 
    conditional routing, and document history.
    """
    permission_classes = [IsAuthenticated]
    queryset = DocumentApprovalFlow.objects.all()
    
    def get_serializer_class(self):
        if self.action == 'take_action':
            return ApprovalActionSerializer
        elif self.action == 'history':
            return WorkflowLogSerializer
        return DocumentApprovalFlowSerializer

    # 1. My Pending Requests (The user's To-Do list)
    def list(self, request):
        """Show all documents where the current user is the designated approver."""
        pending_flows = self.get_queryset().filter(
            current_approver=request.user, 
            is_complete=False
        ).select_related('document', 'current_template_step')
        
        serializer = DocumentApprovalFlowSerializer(pending_flows, many=True)
        return Response(serializer.data)

    # 2. Conditional Routing/Action Endpoint
    @action(detail=True, methods=['post'], url_path='action')
    def take_action(self, request, pk=None):
        """Allows the current approver to Approve, Reject, or Conditionally Route the document."""
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        # --- 1. Authorization & Status Checks ---
        if flow.current_approver != request.user:
            return Response({"detail": "You are not authorized to take action on this document."}, status=status.HTTP_403_FORBIDDEN)
        if flow.is_complete:
            return Response({"detail": "This workflow is already complete."}, status=status.HTTP_400_BAD_REQUEST)
        if not flow.current_template_step:
            return Response({"detail": "Workflow is in an invalid state (no current step)."}, status=status.HTTP_400_BAD_REQUEST)

        # --- 2. Validation and Input ---
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        action_type = data['action']
        comments = data.get('comments')

        # --- 3. Transactional Action ---
        with transaction.atomic():
            
            # --- Case A: REJECT ---
            if action_type == 'reject':
                flow.is_complete = True
                flow.is_approved = False
                flow.completed_at = timezone.now()
                flow.current_approver = None
                flow.document.status = flow.document.STATUS_REJECTED
                flow.document.save()
                
                WorkflowLog.objects.create(
                    document=flow.document, actor=request.user, action_type='reject', 
                    template_step=flow.current_template_step, comments=comments
                )
                
            # --- Case B: ROUTE/APPROVE (Conditional Logic) ---
            elif action_type == 'route':
                decision = data['decision']
                current_step_def = flow.current_template_step
                
                next_step_order = current_step_def.next_step_routes.get(decision)
                
                if next_step_order is None:
                    return Response({"detail": f"Invalid decision '{decision}' for current workflow step."}, 
                                    status=status.HTTP_400_BAD_REQUEST)
                
                next_step_def = flow.workflow_template.template_steps.filter(
                    step_order=next_step_order
                ).first()
                
                # --- Subcase B1: Workflow Completion (Final Approval) ---
                if not next_step_def:
                    flow.is_complete = True
                    flow.is_approved = True
                    flow.completed_at = timezone.now()
                    flow.current_approver = None
                    flow.document.status = flow.document.STATUS_SIGNED
                    flow.document.save()
                    
                    # Call the notification function!
                    send_approval_notification(flow.document.id) # <--- RESOLVED TODO
                    
                # --- Subcase B2: Continue Routing ---
                else:
                    next_approver = find_approver_for_role(flow.document.organization, next_step_def.approver_role)
                    
                    if not next_approver:
                        return Response({"detail": f"No user found for the required role: {next_step_def.approver_role}"}, 
                                        status=status.HTTP_404_NOT_FOUND)

                    flow.current_template_step = next_step_def
                    flow.current_approver = next_approver

                # Log the route action
                WorkflowLog.objects.create(
                    document=flow.document, actor=request.user, action_type='route', 
                    template_step=current_step_def, comments=f"Decision: {decision}. {comments or ''}"
                )
                
                flow.save()
                
        # 4. Success Response
        return Response(DocumentApprovalFlowSerializer(flow).data, status=status.HTTP_200_OK)

    # 3. Document History (Phase 4)
    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        """Retrieves the chronological history of all workflow actions for a document."""
        document = get_object_or_404(Document, approval_flow__pk=pk)
        
        logs = document.workflow_logs.all().order_by('created_at')
        
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)