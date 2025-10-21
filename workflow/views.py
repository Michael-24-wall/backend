# workflow/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_yasg.utils import swagger_auto_schema, no_body
from drf_yasg import openapi

from .models import ApprovalStep
from .serializers import ApprovalStepSerializer, ApprovalActionSerializer

# --- Response Schemas for Swagger ---
approval_action_response = openapi.Response(
    'Step successfully updated', 
    ApprovalStepSerializer
)

class ApprovalStepViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A read-only viewset for listing and retrieving workflow approval steps.
    
    Custom actions allow the approver to submit approval or rejection.
    """
    queryset = ApprovalStep.objects.all()
    serializer_class = ApprovalStepSerializer
    permission_classes = [IsAuthenticated]

    # --- Custom Action for Approval/Rejection ---
    @swagger_auto_schema(
        method='post',
        request_body=ApprovalActionSerializer,
        responses={
            200: approval_action_response,
            400: 'Invalid action or request body.',
            403: 'User is not the designated approver for this step.',
            404: 'Step not found.'
        },
        operation_summary="Approve or Reject a Workflow Step",
        operation_description="Allows the designated approver to change the status of a pending step to APPROVED or REJECTED."
    )
    @action(detail=True, methods=['post'], url_path='action')
    def approval_action(self, request, pk=None):
        step = self.get_object()
        
        # 1. Permission Check: Ensure the current user is the designated approver
        if step.approver != request.user:
            return Response(
                {"detail": "You are not authorized to take action on this step."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # 2. Status Check: Ensure the step is currently pending
        if step.status != 'PENDING':
            return Response(
                {"detail": f"Step is already {step.status}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Validate Input Data
        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action_type = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes')

        # 4. Perform Action
        if action_type == 'approve':
            step.status = 'APPROVED'
        elif action_type == 'reject':
            step.status = 'REJECTED'
        
        step.notes = notes
        step.save()
        
        # NOTE: In a real app, you would add logic here to move the document
        # to the next step, or finalize the document if this was the last step.
        
        return Response(ApprovalStepSerializer(step).data, status=status.HTTP_200_OK)