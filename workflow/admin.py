# workflow/admin.py

from django.contrib import admin
from .models import (
    ApprovalWorkflow, 
    WorkflowTemplateStep, 
    DocumentApprovalFlow, 
    WorkflowLog 
)

# --- 1. Workflow Template Management ---

@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'is_active', 'created_at')
    list_filter = ('organization', 'is_active')
    search_fields = ('name', 'description')

@admin.register(WorkflowTemplateStep)
class WorkflowTemplateStepAdmin(admin.ModelAdmin):
    list_display = ('workflow', 'step_order', 'approver_role', 'next_steps_preview')
    list_filter = ('workflow__name', 'approver_role')
    ordering = ('workflow', 'step_order',)
    
    def next_steps_preview(self, obj):
        # Display the JSON routing for quick viewing
        return str(obj.next_step_routes)
    next_steps_preview.short_description = 'Routing'

# --- 2. Runtime Flow Tracking ---

@admin.register(DocumentApprovalFlow)
class DocumentApprovalFlowAdmin(admin.ModelAdmin):
    list_display = ('document', 'workflow_template', 'current_approver', 'is_complete', 'is_approved', 'created_at')
    list_filter = ('is_complete', 'is_approved', 'workflow_template__name')
    search_fields = ('document__title', 'current_approver__username')
    readonly_fields = ('document', 'workflow_template', 'created_at', 'completed_at')

@admin.register(WorkflowLog)
class WorkflowLogAdmin(admin.ModelAdmin):
    list_display = ('document', 'action_type', 'actor', 'created_at', 'comments_preview')
    list_filter = ('action_type', 'created_at')
    search_fields = ('document__title', 'actor__username', 'comments')
    readonly_fields = ('document', 'template_step', 'actor', 'action_type', 'created_at')

    def comments_preview(self, obj):
        if obj.comments:
            return obj.comments[:75] + '...' if len(obj.comments) > 75 else obj.comments
        return '-'
    comments_preview.short_description = 'Comments'