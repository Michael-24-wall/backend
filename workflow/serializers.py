from rest_framework import serializers
from .models import (
    ApprovalWorkflow, WorkflowTemplateStep, 
    DocumentApprovalFlow, WorkflowLog
)


# --- 1. Blueprint Serializers (For Admin/Setup) ---

class WorkflowTemplateStepSerializer(serializers.ModelSerializer):
    """Serializer for defining the steps of a reusable workflow blueprint."""
    
    step_order = serializers.IntegerField(min_value=1)
    approver_role_display = serializers.CharField(
        source='get_approver_role_display', 
        read_only=True
    )
    
    class Meta:
        model = WorkflowTemplateStep
        fields = [
            'id', 'step_order', 'approver_role', 'approver_role_display',
            'next_step_routes', 'timeout_days', 'require_all_approvers'
        ]
        read_only_fields = ['id']

    def validate_next_step_routes(self, value):
        """Validate the JSON routing structure"""
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("next_step_routes must be a JSON object")
        return value


class ApprovalWorkflowSerializer(serializers.ModelSerializer):
    """Serializer for defining a full reusable workflow blueprint."""
    
    # For read operations - display steps
    template_steps = WorkflowTemplateStepSerializer(many=True, read_only=True)
    
    # For write operations - allow creating steps with workflow
    steps = WorkflowTemplateStepSerializer(
        many=True, 
        write_only=True, 
        required=False
    )
    
    organization_name = serializers.CharField(
        source='organization.name', 
        read_only=True
    )
    steps_count = serializers.IntegerField(
        source='get_steps_count', 
        read_only=True
    )

    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'organization', 'organization_name', 'name', 'description', 
            'is_active', 'created_at', 'steps_count', 'template_steps', 'steps'
        ]
        read_only_fields = ['id', 'created_at', 'organization_name', 'steps_count']

    def create(self, validated_data):
        """Create workflow with nested steps"""
        steps_data = validated_data.pop('steps', [])
        workflow = ApprovalWorkflow.objects.create(**validated_data)
        
        for step_data in steps_data:
            WorkflowTemplateStep.objects.create(workflow=workflow, **step_data)
        
        return workflow

    def update(self, instance, validated_data):
        """Update workflow - handle steps separately via different endpoint"""
        steps_data = validated_data.pop('steps', None)
        if steps_data is not None:
            # Typically, steps should be updated via separate endpoint
            # But you could implement step update logic here if needed
            pass
            
        return super().update(instance, validated_data)


# --- 2. Instance Tracking Serializers ---

class DocumentApprovalFlowDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for viewing the current state of a document's approval flow.
    """
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_owner = serializers.CharField(
        source='document.owner.get_full_name', 
        read_only=True
    )
    current_approver_name = serializers.CharField(
        source='current_approver.get_full_name', 
        read_only=True
    )
    current_approver_username = serializers.CharField(
        source='current_approver.username', 
        read_only=True
    )
    current_step_role = serializers.CharField(
        source='current_template_step.approver_role', 
        read_only=True
    )
    current_step_role_display = serializers.CharField(
        source='current_template_step.get_approver_role_display', 
        read_only=True
    )
    current_step_routes = serializers.JSONField(
        source='current_template_step.next_step_routes', 
        read_only=True
    )
    current_step_order = serializers.IntegerField(
        source='current_template_step.step_order', 
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', 
        read_only=True
    )
    progress_percentage = serializers.IntegerField(
        source='get_progress_percentage', 
        read_only=True
    )
    is_overdue = serializers.BooleanField(read_only=True)
    current_deadline = serializers.DateTimeField(read_only=True)

    class Meta:
        model = DocumentApprovalFlow
        fields = [
            'id', 'document', 'document_title', 'document_owner',
            'current_approver', 'current_approver_name', 'current_approver_username',
            'current_template_step', 'current_step_order', 'current_step_role', 
            'current_step_role_display', 'current_step_routes',
            'status', 'status_display', 'is_complete', 'is_approved',
            'progress_percentage', 'is_overdue', 'current_deadline',
            'started_at', 'current_step_started_at', 'completed_at'
        ]
        read_only_fields = fields


class DocumentApprovalFlowListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing approval flows (e.g., in "My Pending" view)
    """
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_owner = serializers.CharField(
        source='document.owner.get_full_name', 
        read_only=True
    )
    current_step_role_display = serializers.CharField(
        source='current_template_step.get_approver_role_display', 
        read_only=True
    )
    current_step_order = serializers.IntegerField(
        source='current_template_step.step_order', 
        read_only=True
    )
    is_overdue = serializers.BooleanField(read_only=True)
    days_in_current_step = serializers.SerializerMethodField()

    class Meta:
        model = DocumentApprovalFlow
        fields = [
            'id', 'document', 'document_title', 'document_owner',
            'current_step_order', 'current_step_role_display',
            'status', 'is_complete', 'is_approved', 'is_overdue',
            'days_in_current_step', 'current_step_started_at', 'current_deadline'
        ]
        read_only_fields = fields

    def get_days_in_current_step(self, obj):
        """Calculate days spent in current step"""
        if obj.current_step_started_at:
            delta = timezone.now() - obj.current_step_started_at
            return delta.days
        return 0


class WorkflowLogSerializer(serializers.ModelSerializer):
    """Serializer for viewing the historical log of actions taken."""
    actor_name = serializers.CharField(
        source='actor.get_full_name', 
        read_only=True
    )
    actor_username = serializers.CharField(
        source='actor.username', 
        read_only=True
    )
    step_role = serializers.CharField(
        source='template_step.approver_role', 
        read_only=True
    )
    step_role_display = serializers.CharField(
        source='template_step.get_approver_role_display', 
        read_only=True
    )
    step_order = serializers.IntegerField(
        source='template_step.step_order', 
        read_only=True
    )
    action_type_display = serializers.CharField(
        source='get_action_type_display', 
        read_only=True
    )

    class Meta:
        model = WorkflowLog
        fields = [
            'id', 'document', 'template_step', 'step_order', 
            'step_role', 'step_role_display', 'actor', 'actor_name', 
            'actor_username', 'action_type', 'action_type_display',
            'decision_key', 'comments', 'created_at'
        ]
        read_only_fields = fields


# --- 3. Action Serializers ---

class ApprovalActionSerializer(serializers.Serializer):
    """
    Serializer for taking action on a pending approval step.
    """
    action = serializers.ChoiceField(
        choices=['route', 'reject', 'delegate', 'escalate'],
        help_text="Action type: 'route' (proceed with decision), 'reject', 'delegate', or 'escalate'."
    )
    
    decision = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The specific route decision key (required if action='route')."
    )
    
    comments = serializers.CharField(
        required=False, 
        allow_blank=True,
        max_length=1000,
        help_text="Optional comments for the action taken."
    )
    
    # For delegation/escalation
    target_user_id = serializers.IntegerField(
        required=False,
        help_text="Target user ID for delegation or escalation."
    )

    def validate(self, data):
        action = data['action']
        decision = data.get('decision')
        target_user_id = data.get('target_user_id')

        # Validate decision for route actions
        if action == 'route' and not decision:
            raise serializers.ValidationError({
                "decision": "This field is required when action is 'route'."
            })

        # Validate target user for delegation/escalation
        if action in ['delegate', 'escalate'] and not target_user_id:
            raise serializers.ValidationError({
                "target_user_id": f"This field is required when action is '{action}'."
            })

        return data


class WorkflowInitiationSerializer(serializers.Serializer):
    """
    Serializer for initiating a workflow on a document.
    """
    workflow_template_id = serializers.IntegerField(
        help_text="ID of the workflow template to initiate"
    )
    
    def validate_workflow_template_id(self, value):
        """Validate that the workflow template exists and is active"""
        try:
            workflow = ApprovalWorkflow.objects.get(id=value, is_active=True)
        except ApprovalWorkflow.DoesNotExist:
            raise serializers.ValidationError(
                "Active workflow template with this ID does not exist."
            )
        return value


# --- 4. Statistics Serializers ---

class WorkflowStatsSerializer(serializers.Serializer):
    """Serializer for workflow statistics"""
    total_flows = serializers.IntegerField()
    pending_flows = serializers.IntegerField()
    completed_flows = serializers.IntegerField()
    approval_rate = serializers.FloatField()
    avg_completion_time_days = serializers.FloatField()
    
    pending_by_step = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Count of pending flows by step order"
    )


class UserWorkflowStatsSerializer(serializers.Serializer):
    """Serializer for user-specific workflow statistics"""
    pending_approvals_count = serializers.IntegerField()
    completed_approvals_count = serializers.IntegerField()
    overdue_approvals_count = serializers.IntegerField()
    avg_response_time_hours = serializers.FloatField()