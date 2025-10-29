# workflow/serializers.py
from rest_framework import serializers
from django.utils import timezone
from .models import (
    ApprovalWorkflow, WorkflowTemplateStep, 
    DocumentApprovalFlow, WorkflowLog,
    ApprovalChatRoom, WorkflowMessageContext
)
from core.models import OrganizationMembership

class WorkflowTemplateStepSerializer(serializers.ModelSerializer):
    approver_role_display = serializers.CharField(source='get_approver_role_display', read_only=True)
    
    class Meta:
        model = WorkflowTemplateStep
        fields = [
            'id', 'step_order', 'approver_role', 'approver_role_display',
            'next_step_routes', 'timeout_days', 'require_all_approvers'
        ]
        read_only_fields = ['id']

    def validate_next_step_routes(self, value):
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("next_step_routes must be a JSON object")
        return value


class ApprovalWorkflowSerializer(serializers.ModelSerializer):
    template_steps = WorkflowTemplateStepSerializer(many=True, read_only=True)
    steps = WorkflowTemplateStepSerializer(many=True, write_only=True, required=False)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    steps_count = serializers.IntegerField(source='get_steps_count', read_only=True)

    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'name', 'description', 
            'is_active', 'created_at', 'steps_count', 'template_steps', 'steps',
            'organization_name'
        ]
        read_only_fields = ['id', 'created_at', 'organization_name', 'steps_count']

    def create(self, validated_data):
        # Get organization from user's organization memberships
        user = self.context['request'].user
        
        # Handle the reverse relationship properly
        try:
            # Use organizationmembership_set for reverse relationship
            membership = OrganizationMembership.objects.filter(
                user=user, 
                is_active=True
            ).first()
            
            if not membership:
                raise serializers.ValidationError("User is not a member of any active organization")
            
            organization = membership.organization
        except Exception as e:
            raise serializers.ValidationError(f"Could not determine user's organization: {str(e)}")
        
        steps_data = validated_data.pop('steps', [])
        
        # Create workflow with organization
        workflow = ApprovalWorkflow.objects.create(
            organization=organization,
            **validated_data
        )
        
        # Create steps if provided
        for step_data in steps_data:
            WorkflowTemplateStep.objects.create(workflow=workflow, **step_data)
        
        return workflow

    def update(self, instance, validated_data):
        steps_data = validated_data.pop('steps', None)
        
        # Update workflow fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update steps if provided
        if steps_data is not None:
            # Delete existing steps
            instance.template_steps.all().delete()
            # Create new steps
            for step_data in steps_data:
                WorkflowTemplateStep.objects.create(workflow=instance, **step_data)
        
        return instance


class DocumentApprovalFlowDetailSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_owner = serializers.CharField(source='document.created_by.get_full_name', read_only=True)
    current_approver_name = serializers.CharField(source='current_approver.get_full_name', read_only=True)
    current_approver_username = serializers.CharField(source='current_approver.username', read_only=True)
    current_step_role = serializers.CharField(source='current_template_step.approver_role', read_only=True)
    current_step_role_display = serializers.CharField(source='current_template_step.get_approver_role_display', read_only=True)
    current_step_routes = serializers.JSONField(source='current_template_step.next_step_routes', read_only=True)
    current_step_order = serializers.IntegerField(source='current_template_step.step_order', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    progress_percentage = serializers.IntegerField(source='get_progress_percentage', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    workflow_template_name = serializers.CharField(source='workflow_template.name', read_only=True)

    class Meta:
        model = DocumentApprovalFlow
        fields = [
            'id', 'document', 'document_title', 'document_owner',
            'workflow_template', 'workflow_template_name',
            'current_approver', 'current_approver_name', 'current_approver_username',
            'current_template_step', 'current_step_order', 'current_step_role', 
            'current_step_role_display', 'current_step_routes',
            'status', 'status_display', 'is_complete', 'is_approved',
            'progress_percentage', 'is_overdue', 'current_deadline',
            'started_at', 'current_step_started_at', 'completed_at'
        ]
        read_only_fields = fields


class DocumentApprovalFlowListSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_owner = serializers.CharField(source='document.created_by.get_full_name', read_only=True)
    current_step_role_display = serializers.CharField(source='current_template_step.get_approver_role_display', read_only=True)
    current_step_order = serializers.IntegerField(source='current_template_step.step_order', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_in_current_step = serializers.SerializerMethodField()
    workflow_template_name = serializers.CharField(source='workflow_template.name', read_only=True)

    class Meta:
        model = DocumentApprovalFlow
        fields = [
            'id', 'document', 'document_title', 'document_owner',
            'workflow_template_name',
            'current_step_order', 'current_step_role_display',
            'status', 'is_complete', 'is_approved', 'is_overdue',
            'days_in_current_step', 'current_step_started_at', 'current_deadline'
        ]
        read_only_fields = fields

    def get_days_in_current_step(self, obj):
        if obj.current_step_started_at:
            delta = timezone.now() - obj.current_step_started_at
            return delta.days
        return 0


class WorkflowLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.get_full_name', read_only=True)
    actor_username = serializers.CharField(source='actor.username', read_only=True)
    step_role = serializers.CharField(source='template_step.approver_role', read_only=True)
    step_role_display = serializers.CharField(source='template_step.get_approver_role_display', read_only=True)
    step_order = serializers.IntegerField(source='template_step.step_order', read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)

    class Meta:
        model = WorkflowLog
        fields = [
            'id', 'document', 'document_title', 'template_step', 'step_order', 
            'step_role', 'step_role_display', 'actor', 'actor_name', 
            'actor_username', 'action_type', 'action_type_display',
            'decision_key', 'comments', 'created_at'
        ]
        read_only_fields = fields


class ApprovalActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=['route', 'reject', 'delegate', 'escalate'],
        help_text="Action type: 'route' (proceed with decision), 'reject', 'delegate', or 'escalate'."
    )
    decision = serializers.CharField(required=False, allow_blank=True)
    comments = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    target_user_id = serializers.IntegerField(required=False)

    def validate(self, data):
        action = data['action']
        decision = data.get('decision')
        target_user_id = data.get('target_user_id')

        if action == 'route' and not decision:
            raise serializers.ValidationError({"decision": "This field is required when action is 'route'."})

        if action in ['delegate', 'escalate'] and not target_user_id:
            raise serializers.ValidationError({"target_user_id": f"This field is required when action is '{action}'."})

        return data


class WorkflowInitiationSerializer(serializers.Serializer):
    workflow_template_id = serializers.IntegerField(help_text="ID of the workflow template to initiate")
    
    def validate_workflow_template_id(self, value):
        try:
            workflow = ApprovalWorkflow.objects.get(id=value, is_active=True)
        except ApprovalWorkflow.DoesNotExist:
            raise serializers.ValidationError("Active workflow template with this ID does not exist.")
        return value


class ApprovalChatRoomSerializer(serializers.ModelSerializer):
    chat_room_name = serializers.CharField(source='chat_room.name', read_only=True)
    chat_room_title = serializers.CharField(source='chat_room.title', read_only=True)
    chat_room_description = serializers.CharField(source='chat_room.description', read_only=True)
    document_title = serializers.CharField(source='approval_flow.document.title', read_only=True)

    class Meta:
        model = ApprovalChatRoom
        fields = [
            'id', 'approval_flow', 'document_title', 'chat_room', 
            'chat_room_name', 'chat_room_title', 'chat_room_description', 
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class WorkflowMessageContextSerializer(serializers.ModelSerializer):
    message_content = serializers.CharField(source='message.content', read_only=True)
    message_type = serializers.CharField(source='message.message_type', read_only=True)
    step_role_display = serializers.CharField(source='related_step.get_approver_role_display', read_only=True)

    class Meta:
        model = WorkflowMessageContext
        fields = [
            'id', 'message', 'message_content', 'message_type',
            'workflow_action', 'related_step', 'step_role_display',
            'is_urgent', 'created_at'
        ]
        read_only_fields = fields