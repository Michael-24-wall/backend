from django.contrib import admin
from .models import (
    ApprovalWorkflow, WorkflowTemplateStep, 
    DocumentApprovalFlow, WorkflowLog,
    ApprovalChatRoom
)

@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'is_active', 'created_at', 'steps_count']
    list_filter = ['is_active', 'organization', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'steps_count']
    list_per_page = 20
    
    def steps_count(self, obj):
        return obj.template_steps.count()
    steps_count.short_description = 'Steps'

@admin.register(WorkflowTemplateStep)
class WorkflowTemplateStepAdmin(admin.ModelAdmin):
    list_display = ['workflow', 'step_order', 'approver_role', 'timeout_days', 'has_routes']
    list_filter = ['workflow', 'approver_role', 'timeout_days']
    ordering = ['workflow', 'step_order']
    list_per_page = 25
    
    def has_routes(self, obj):
        return bool(obj.next_step_routes)
    has_routes.boolean = True
    has_routes.short_description = 'Has Routes'

@admin.register(DocumentApprovalFlow)
class DocumentApprovalFlowAdmin(admin.ModelAdmin):
    list_display = ['document', 'workflow_template', 'current_approver', 'status', 'is_complete', 'is_approved', 'started_at']
    list_filter = ['status', 'is_complete', 'is_approved', 'workflow_template', 'started_at']
    search_fields = ['document__title', 'current_approver__username', 'current_approver__email']
    readonly_fields = ['started_at', 'completed_at', 'current_step_started_at']
    list_per_page = 25
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'document', 'workflow_template', 'current_approver'
        )

@admin.register(WorkflowLog)
class WorkflowLogAdmin(admin.ModelAdmin):
    list_display = ['document', 'template_step', 'actor', 'action_type', 'created_at', 'has_comments']
    list_filter = ['action_type', 'created_at', 'template_step']
    search_fields = ['document__title', 'actor__username', 'actor__email', 'comments']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'created_at'
    
    def has_comments(self, obj):
        return bool(obj.comments)
    has_comments.boolean = True
    has_comments.short_description = 'Has Comments'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'document', 'template_step', 'actor'
        )

@admin.register(ApprovalChatRoom)
class ApprovalChatRoomAdmin(admin.ModelAdmin):
    list_display = ['approval_flow', 'chat_room', 'created_at']
    list_filter = ['created_at']
    search_fields = ['approval_flow__document__title', 'chat_room__name']
    readonly_fields = ['created_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'approval_flow', 'approval_flow__document', 'chat_room'
        )