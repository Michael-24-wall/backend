from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from .models import Project, Task

# Inline Admin Classes
class TaskInline(admin.TabularInline):
    model = Task
    extra = 1
    fields = ('title', 'assigned_to', 'status', 'priority', 'due_date', 'is_overdue_display')
    readonly_fields = ('is_overdue_display',)
    verbose_name = "Task"
    verbose_name_plural = "Tasks"
    
    def is_overdue_display(self, obj):
        if obj.is_overdue():
            return format_html('<span style="color: red;">⚠ Overdue</span>')
        return "On Time"
    is_overdue_display.short_description = 'Status'

# Custom Filters
class ProjectStatusFilter(admin.SimpleListFilter):
    title = 'project status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('active', 'Active Projects'),
            ('overdue', 'Overdue Projects'),
            ('completed', 'Completed Projects'),
            ('planning', 'Planning Phase'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(status='active')
        elif self.value() == 'overdue':
            return queryset.filter(end_date__lt=timezone.now().date()).exclude(status__in=['completed', 'cancelled'])
        elif self.value() == 'completed':
            return queryset.filter(status='completed')
        elif self.value() == 'planning':
            return queryset.filter(status='planning')
        return queryset

class TaskStatusFilter(admin.SimpleListFilter):
    title = 'task status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('overdue', 'Overdue Tasks'),
            ('completed', 'Completed Tasks'),
            ('in_progress', 'In Progress'),
            ('todo', 'To Do'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'overdue':
            return queryset.filter(due_date__lt=timezone.now().date()).exclude(status='completed')
        elif self.value() == 'completed':
            return queryset.filter(status='completed')
        elif self.value() == 'in_progress':
            return queryset.filter(status='in_progress')
        elif self.value() == 'todo':
            return queryset.filter(status='todo')
        return queryset

class PriorityFilter(admin.SimpleListFilter):
    title = 'priority'
    parameter_name = 'priority'

    def lookups(self, request, model_admin):
        return [
            ('high', 'High Priority'),
            ('medium', 'Medium Priority'),
            ('low', 'Low Priority'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(priority=self.value())
        return queryset

# Project Admin
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'status', 'manager', 'start_date',  # FIXED: Added 'status'
        'end_date', 'is_overdue_display', 'task_count', 'completed_task_count',
        'created_at'
    )
    list_filter = (ProjectStatusFilter, 'organization', 'status', 'start_date', 'created_at')
    search_fields = ('name', 'description', 'organization__name', 'manager__email')
    readonly_fields = (
        'created_at', 'updated_at', 'is_overdue_display', 'task_count', 
        'completed_task_count', 'completion_rate', 'duration_days'
    )
    list_editable = ('status',)  # Now 'status' is in list_display
    list_per_page = 25
    inlines = [TaskInline]
    
    fieldsets = (
        ('Project Information', {
            'fields': ('organization', 'name', 'description', 'manager')
        }),
        ('Status & Timeline', {
            'fields': ('status', 'start_date', 'end_date', 'is_overdue_display', 'duration_days')
        }),
        ('Statistics', {
            'fields': ('task_count', 'completed_task_count', 'completion_rate'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_overdue_display(self, obj):
        if obj.is_overdue():
            return format_html('<span style="color: red; font-weight: bold;">⚠ OVERDUE</span>')
        return format_html('<span style="color: green;">✓ On Track</span>')
    is_overdue_display.short_description = 'Timeline Status'
    
    def task_count(self, obj):
        return obj.tasks.count()
    task_count.short_description = 'Total Tasks'
    
    def completed_task_count(self, obj):
        return obj.tasks.filter(status='completed').count()
    completed_task_count.short_description = 'Completed Tasks'
    
    def completion_rate(self, obj):
        total = obj.tasks.count()
        if total == 0:
            return "0%"
        completed = obj.tasks.filter(status='completed').count()
        rate = (completed / total) * 100
        return f"{rate:.1f}%"
    completion_rate.short_description = 'Completion Rate'
    
    def duration_days(self, obj):
        if obj.start_date and obj.end_date:
            duration = obj.end_date - obj.start_date
            return f"{duration.days} days"
        elif obj.start_date:
            days_passed = (timezone.now().date() - obj.start_date).days
            return f"{days_passed} days (ongoing)"
        return "Not started"
    duration_days.short_description = 'Duration'

# Task Admin
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'project', 'assigned_to', 'status', 'priority',  # FIXED: Added 'status' and 'priority'
        'due_date', 'is_overdue_display', 'completed_at', 'created_at'
    )
    list_filter = (TaskStatusFilter, PriorityFilter, 'status', 'project__organization', 'due_date', 'created_at')
    search_fields = ('title', 'description', 'project__name', 'assigned_to__email')
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'is_overdue_display')
    list_editable = ('status', 'priority', 'due_date')  # Now 'status' and 'priority' are in list_display
    list_per_page = 30
    
    fieldsets = (
        ('Task Information', {
            'fields': ('project', 'title', 'description', 'assigned_to')
        }),
        ('Status & Priority', {
            'fields': ('status', 'priority', 'is_overdue_display')
        }),
        ('Timeline', {
            'fields': ('due_date', 'completed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_overdue_display(self, obj):
        if obj.is_overdue():
            return format_html('<span style="color: red; font-weight: bold;">⚠ OVERDUE</span>')
        elif obj.status == 'completed':
            return format_html('<span style="color: green;">✓ Completed</span>')
        else:
            return format_html('<span style="color: green;">✓ On Track</span>')
    is_overdue_display.short_description = 'Timeline Status'

# Custom Admin Actions
def mark_projects_completed(modeladmin, request, queryset):
    updated = queryset.update(status='completed')
    messages.success(request, f"{updated} projects marked as completed.")
mark_projects_completed.short_description = "Mark selected projects as completed"

def mark_projects_active(modeladmin, request, queryset):
    updated = queryset.update(status='active')
    messages.success(request, f"{updated} projects marked as active.")
mark_projects_active.short_description = "Mark selected projects as active"

def mark_tasks_completed(modeladmin, request, queryset):
    updated = queryset.update(status='completed')
    messages.success(request, f"{updated} tasks marked as completed.")
mark_tasks_completed.short_description = "Mark selected tasks as completed"

def mark_tasks_in_progress(modeladmin, request, queryset):
    updated = queryset.update(status='in_progress')
    messages.success(request, f"{updated} tasks marked as in progress.")
mark_tasks_in_progress.short_description = "Mark selected tasks as in progress"

def set_high_priority(modeladmin, request, queryset):
    updated = queryset.update(priority='high')
    messages.success(request, f"{updated} tasks set to high priority.")
set_high_priority.short_description = "Set selected tasks to high priority"

# Add actions to admins
ProjectAdmin.actions = [mark_projects_completed, mark_projects_active]
TaskAdmin.actions = [mark_tasks_completed, mark_tasks_in_progress, set_high_priority]