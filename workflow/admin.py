from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from .models import ApprovalStep

# Custom Filters
class ApprovalStatusFilter(admin.SimpleListFilter):
    title = 'approval status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('stuck', 'Stuck Workflows'),  # Pending for more than 7 days
        ]

    def queryset(self, request, queryset):
        if self.value() == 'pending':
            return queryset.filter(status='PENDING')
        elif self.value() == 'approved':
            return queryset.filter(status='APPROVED')
        elif self.value() == 'rejected':
            return queryset.filter(status='REJECTED')
        elif self.value() == 'stuck':
            week_ago = timezone.now() - timezone.timedelta(days=7)
            return queryset.filter(status='PENDING', created_at__lt=week_ago)
        return queryset

class DocumentFilter(admin.SimpleListFilter):
    title = 'document'
    parameter_name = 'document'

    def lookups(self, request, model_admin):
        from documents.models import Document
        documents = Document.objects.all()[:20]  # Limit to first 20 for performance
        return [(doc.id, doc.title) for doc in documents]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(document_id=self.value())
        return queryset

# Approval Step Inline for Document (to be used in documents admin)
class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 1
    fields = ('order', 'approver', 'status_display', 'notes_preview', 'created_at')
    readonly_fields = ('status_display', 'notes_preview', 'created_at')
    verbose_name = "Approval Step"
    verbose_name_plural = "Approval Workflow"
    
    def status_display(self, obj):
        status_colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'SKIPPED': 'gray'
        }
        color = status_colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def notes_preview(self, obj):
        if obj.notes:
            return obj.notes[:50] + '...' if len(obj.notes) > 50 else obj.notes
        return '-'
    notes_preview.short_description = 'Notes'

# Approval Step Admin
@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = (
        'document_link', 'order', 'approver', 'status_display', 'status',
        'notes_preview', 'days_pending', 'created_at', 'updated_at'
    )
    list_filter = (ApprovalStatusFilter, DocumentFilter, 'order', 'created_at')
    search_fields = (
        'document__title', 'approver__email', 'approver__first_name', 
        'approver__last_name', 'notes'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'days_pending', 'workflow_progress',
        'document_link', 'approver_details'
    )
    list_editable = ('status',)
    list_per_page = 30
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Workflow Information', {
            'fields': ('document_link', 'order', 'approver_details')
        }),
        ('Approval Details', {
            'fields': ('status', 'notes')
        }),
        ('Progress & Timing', {
            'fields': ('workflow_progress', 'days_pending'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def document_link(self, obj):
        url = f"/admin/documents/document/{obj.document.id}/change/"
        return format_html(
            '<a href="{}" style="font-weight: bold;">{}</a>',
            url,
            obj.document.title
        )
    document_link.short_description = 'Document'
    
    def status_display(self, obj):
        status_colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'SKIPPED': 'gray'
        }
        color = status_colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def notes_preview(self, obj):
        if obj.notes:
            return obj.notes[:50] + '...' if len(obj.notes) > 50 else obj.notes
        return '-'
    notes_preview.short_description = 'Notes'
    
    def days_pending(self, obj):
        if obj.status == 'PENDING':
            days = (timezone.now() - obj.created_at).days
            if days > 7:
                return format_html('<span style="color: red; font-weight: bold;">{} days</span>', days)
            elif days > 3:
                return format_html('<span style="color: orange;">{} days</span>', days)
            else:
                return f"{days} days"
        return '-'
    days_pending.short_description = 'Days Pending'
    
    def workflow_progress(self, obj):
        # Calculate progress for this document's workflow
        document_steps = ApprovalStep.objects.filter(document=obj.document)
        total_steps = document_steps.count()
        completed_steps = document_steps.filter(status__in=['APPROVED', 'SKIPPED']).count()
        
        if total_steps == 0:
            return "No steps defined"
        
        percentage = (completed_steps / total_steps) * 100
        current_step = obj.order
        
        return format_html(
            'Step {} of {} ({}% complete)',
            current_step, total_steps, int(percentage)
        )
    workflow_progress.short_description = 'Workflow Progress'
    
    def approver_details(self, obj):
        return format_html(
            '{}<br><small style="color: #666;">{}</small>',
            obj.approver.get_full_name() or obj.approver.email,
            obj.approver.email
        )
    approver_details.short_description = 'Approver'

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Prefetch related objects for performance
        return queryset.select_related('document', 'approver')

# Custom Admin Actions
def approve_selected_steps(modeladmin, request, queryset):
    updated = queryset.filter(status='PENDING').update(status='APPROVED')
    messages.success(request, f"{updated} approval steps approved.")
approve_selected_steps.short_description = "Approve selected pending steps"

def reject_selected_steps(modeladmin, request, queryset):
    updated = queryset.filter(status='PENDING').update(status='REJECTED')
    messages.success(request, f"{updated} approval steps rejected.")
reject_selected_steps.short_description = "Reject selected pending steps"

def reset_to_pending(modeladmin, request, queryset):
    updated = queryset.exclude(status='PENDING').update(status='PENDING')
    messages.success(request, f"{updated} approval steps reset to pending.")
reset_to_pending.short_description = "Reset selected steps to pending"

# Add actions to ApprovalStepAdmin
ApprovalStepAdmin.actions = [approve_selected_steps, reject_selected_steps, reset_to_pending]

# Workflow Dashboard View (optional)
class WorkflowDashboard:
    """Helper class for workflow statistics"""
    
    @staticmethod
    def get_workflow_statistics():
        from django.db.models import Count, Q
        from datetime import timedelta
        
        stats = {
            'total_workflows': ApprovalStep.objects.values('document').distinct().count(),
            'pending_approvals': ApprovalStep.objects.filter(status='PENDING').count(),
            'approved_today': ApprovalStep.objects.filter(
                status='APPROVED', 
                updated_at__date=timezone.now().date()
            ).count(),
            'stuck_workflows': ApprovalStep.objects.filter(
                status='PENDING', 
                created_at__lt=timezone.now() - timedelta(days=7)
            ).count(),
            'completion_rate': WorkflowDashboard.calculate_completion_rate(),
        }
        return stats
    
    @staticmethod
    def calculate_completion_rate():
        total_steps = ApprovalStep.objects.count()
        if total_steps == 0:
            return "0%"
        completed_steps = ApprovalStep.objects.filter(status__in=['APPROVED', 'SKIPPED']).count()
        rate = (completed_steps / total_steps) * 100
        return f"{rate:.1f}%"

# Add workflow statistics to admin index
def workflow_statistics(request):
    """Context processor for workflow stats (optional)"""
    return {
        'workflow_stats': WorkflowDashboard.get_workflow_statistics()
    }