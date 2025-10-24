from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Organization, OrganizationMembership, Tag, SpreadsheetDocument,
    DocumentCollaborator, DocumentVersion, AuditLog, DocumentAccessLog,
    DocumentComment, DocumentStatus, DocumentType, PermissionLevel, ChangeType
)

# Inline Admin Classes
class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 1
    fields = ('user', 'role', 'joined_at')
    readonly_fields = ('joined_at',)
    verbose_name = "Member"
    verbose_name_plural = "Organization Members"

class DocumentCollaboratorInline(admin.TabularInline):
    model = DocumentCollaborator
    extra = 1
    fields = ('user', 'permission_level', 'added_by', 'expires_at')
    verbose_name = "Collaborator"
    verbose_name_plural = "Document Collaborators"

class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    fields = ('version_number', 'created_by', 'created_at', 'data_size', 'change_description')
    readonly_fields = ('version_number', 'created_by', 'created_at', 'data_size')
    verbose_name = "Version"
    verbose_name_plural = "Document Versions"
    can_delete = False

class DocumentCommentInline(admin.TabularInline):
    model = DocumentComment
    extra = 0
    fields = ('user', 'content', 'cell_reference', 'created_at', 'is_resolved')
    readonly_fields = ('user', 'created_at')
    verbose_name = "Comment"
    verbose_name_plural = "Document Comments"

class AuditLogInline(admin.TabularInline):
    model = AuditLog
    extra = 0
    fields = ('user', 'action', 'timestamp', 'ip_address')
    readonly_fields = ('user', 'action', 'timestamp', 'ip_address')
    verbose_name = "Audit Entry"
    verbose_name_plural = "Audit Logs"
    can_delete = False

# Custom Filters
class DocumentStatusFilter(admin.SimpleListFilter):
    title = 'document status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return DocumentStatus.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset

class DocumentTypeFilter(admin.SimpleListFilter):
    title = 'document type'
    parameter_name = 'document_type'

    def lookups(self, request, model_admin):
        return DocumentType.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(document_type=self.value())
        return queryset

class OrganizationFilter(admin.SimpleListFilter):
    title = 'organization'
    parameter_name = 'organization'

    def lookups(self, request, model_admin):
        organizations = Organization.objects.all()
        return [(org.id, org.name) for org in organizations]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(organization_id=self.value())
        return queryset

# Organization Admin
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'plan_type', 'storage_limit_mb', 'member_count', 'document_count', 'created_at')
    list_filter = ('plan_type', 'created_at')
    search_fields = ('name', 'slug')
    readonly_fields = ('created_at', 'updated_at', 'member_count', 'document_count', 'total_storage_used')
    list_editable = ('plan_type', 'storage_limit_mb')
    list_per_page = 25
    inlines = [OrganizationMembershipInline]
    
    fieldsets = (
        ('Organization Information', {
            'fields': ('name', 'slug', 'plan_type')
        }),
        ('Storage & Limits', {
            'fields': ('storage_limit_mb', 'total_storage_used')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('member_count', 'document_count'),
            'classes': ('collapse',)
        }),
    )
    
    def member_count(self, obj):
        return obj.editor_memberships.count()
    member_count.short_description = 'Members'
    
    def document_count(self, obj):
        return obj.spreadsheets.count()
    document_count.short_description = 'Documents'
    
    def total_storage_used(self, obj):
        total_size = obj.spreadsheets.aggregate(total=Sum('size'))['total'] or 0
        return f"{total_size / 1024 / 1024:.2f} MB"
    total_storage_used.short_description = 'Storage Used'

# Organization Membership Admin
@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'joined_at')
    list_filter = ('role', 'joined_at', 'organization')
    search_fields = ('user__email', 'user__username', 'organization__name')
    readonly_fields = ('joined_at',)
    list_editable = ('role',)
    list_per_page = 25

# Tag Admin
@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color_display', 'organization', 'created_by', 'created_at', 'document_count')
    list_filter = ('organization', 'created_at')
    search_fields = ('name', 'organization__name', 'created_by__email')
    readonly_fields = ('created_at', 'document_count')
    list_per_page = 20
    
    def color_display(self, obj):
        return format_html(
            '<span style="color: {}; font-weight: bold;">■</span> {}',
            obj.color,
            obj.color
        )
    color_display.short_description = 'Color'
    
    def document_count(self, obj):
        return obj.spreadsheets.count()
    document_count.short_description = 'Documents'

# Spreadsheet Document Admin
@admin.register(SpreadsheetDocument)
class SpreadsheetDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'owner', 'organization', 'document_type', 'status', 
        'is_archived', 'collaborator_count', 'version_count', 'view_count',
        'last_modified_by', 'updated_at'
    )
    list_filter = (DocumentStatusFilter, DocumentTypeFilter, OrganizationFilter, 'is_archived', 'is_template', 'created_at')
    search_fields = ('title', 'description', 'owner__email', 'organization__name')
    readonly_fields = (
        'uuid', 'created_at', 'updated_at', 'last_accessed_at', 'size', 
        'complexity_score', 'view_count', 'collaborator_count', 'version_count',
        'is_active', 'get_download_size'
    )
    list_editable = ('status', 'is_archived')
    list_per_page = 25
    inlines = [DocumentCollaboratorInline, DocumentVersionInline, DocumentCommentInline, AuditLogInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('uuid', 'title', 'description', 'owner', 'organization')
        }),
        ('Document Classification', {
            'fields': ('document_type', 'status', 'tags', 'is_template', 'is_public')
        }),
        ('Document Data', {
            'fields': ('editor_data', 'metadata'),
            'classes': ('collapse',)
        }),
        ('Collaboration Settings', {
            'fields': ('allow_comments',),
            'classes': ('collapse',)
        }),
        ('Performance & Analytics', {
            'fields': ('size', 'complexity_score', 'view_count', 'get_download_size'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_accessed_at'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('collaborator_count', 'version_count', 'is_active'),
            'classes': ('collapse',)
        }),
    )
    
    def collaborator_count(self, obj):
        return obj.collaborators.count()
    collaborator_count.short_description = 'Collaborators'
    
    def version_count(self, obj):
        return obj.versions.count()
    version_count.short_description = 'Versions'
    
    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
    is_active.short_description = 'Active'
    
    def get_download_size(self, obj):
        return f"{obj.get_download_size() / 1024:.2f} KB"
    get_download_size.short_description = 'Download Size'

# Document Collaborator Admin
@admin.register(DocumentCollaborator)
class DocumentCollaboratorAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'permission_level', 'added_by', 'added_at', 'expires_at', 'is_active')
    list_filter = ('permission_level', 'added_at')
    search_fields = ('document__title', 'user__email', 'added_by__email')
    readonly_fields = ('added_at', 'is_active')
    list_editable = ('permission_level', 'expires_at')
    list_per_page = 25
    
    def is_active(self, obj):
        return obj.is_active()
    is_active.boolean = True
    is_active.short_description = 'Active'

# Document Version Admin
@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ('document', 'version_number', 'created_by', 'created_at', 'data_size', 'change_description_preview')
    list_filter = ('created_at',)
    search_fields = ('document__title', 'created_by__email', 'change_description')
    readonly_fields = ('version_number', 'created_at', 'data_size', 'checksum')
    list_per_page = 25
    
    def change_description_preview(self, obj):
        if obj.change_description:
            return obj.change_description[:50] + '...' if len(obj.change_description) > 50 else obj.change_description
        return '-'
    change_description_preview.short_description = 'Change Description'

# Audit Log Admin
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'action', 'timestamp', 'ip_address')
    list_filter = ('action', 'timestamp')
    search_fields = ('document__title', 'user__email', 'ip_address')
    readonly_fields = ('timestamp', 'ip_address', 'user_agent')
    list_per_page = 50
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Audit Information', {
            'fields': ('document', 'user', 'action')
        }),
        ('Technical Details', {
            'fields': ('ip_address', 'user_agent', 'details'),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('timestamp',)
        }),
    )

# Document Access Log Admin
@admin.register(DocumentAccessLog)
class DocumentAccessLogAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'access_type', 'accessed_at', 'duration_seconds')
    list_filter = ('access_type', 'accessed_at')
    search_fields = ('document__title', 'user__email')
    readonly_fields = ('accessed_at',)
    list_per_page = 50
    date_hierarchy = 'accessed_at'

# Document Comment Admin
@admin.register(DocumentComment)
class DocumentCommentAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'content_preview', 'cell_reference', 'created_at', 'is_resolved')
    list_filter = ('is_resolved', 'created_at')
    search_fields = ('document__title', 'user__email', 'content', 'cell_reference')
    readonly_fields = ('created_at', 'updated_at')
    list_editable = ('is_resolved',)
    list_per_page = 25
    
    def content_preview(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content'

# Custom Admin Actions
def archive_documents(modeladmin, request, queryset):
    queryset.update(is_archived=True, status=DocumentStatus.ARCHIVED)
    messages.success(request, f"{queryset.count()} documents archived successfully.")
archive_documents.short_description = "Archive selected documents"

def activate_documents(modeladmin, request, queryset):
    queryset.update(is_archived=False, status=DocumentStatus.ACTIVE)
    messages.success(request, f"{queryset.count()} documents activated successfully.")
activate_documents.short_description = "Activate selected documents"

def create_template_from_documents(modeladmin, request, queryset):
    for document in queryset:
        if not document.is_template:
            document.is_template = True
            document.save()
    messages.success(request, f"{queryset.count()} documents marked as templates.")
create_template_from_documents.short_description = "Mark as templates"

# Add actions to SpreadsheetDocumentAdmin
SpreadsheetDocumentAdmin.actions = [archive_documents, activate_documents, create_template_from_documents]

# Optional: Custom admin site configuration
class EditorAdminSite(admin.AdminSite):
    site_header = "Spreadsheet Editor Administration"
    site_title = "Editor Admin"
    index_title = "Document Management System"

# If you want to use a separate admin site, you can register:
# editor_admin_site = EditorAdminSite(name='editor_admin')
# Then register models with editor_admin_site instead of admin.site