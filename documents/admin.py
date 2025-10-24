from django.contrib import admin
from django.utils.html import format_html
from .models import DocumentTemplate, Document, DigitalSignatureLog, DocumentPermission

# Document Permission Inline for Document
class DocumentPermissionInline(admin.TabularInline):
    model = DocumentPermission
    extra = 1
    fields = ('user', 'role', 'permission_type')
    verbose_name = "Permission"
    verbose_name_plural = "Document Permissions"

# Digital Signature Log Inline for Document
class DigitalSignatureLogInline(admin.TabularInline):
    model = DigitalSignatureLog
    extra = 0
    fields = ('signer', 'signer_role', 'signed_at', 'content_hash')
    readonly_fields = ('signed_at', 'content_hash')
    verbose_name = "Signature"
    verbose_name_plural = "Digital Signatures"

# Document Template Admin
@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'created_by', 'created_at', 'documents_count')
    list_filter = ('created_at', 'organization')
    search_fields = ('title', 'organization__name', 'created_by__email')
    readonly_fields = ('created_at', 'documents_count')
    list_per_page = 20
    
    fieldsets = (
        ('Template Information', {
            'fields': ('organization', 'title', 'created_by')
        }),
        ('Content Template', {
            'fields': ('content_template',),
            'description': 'HTML/Markdown content with placeholders (e.g., {{user.first_name}})'
        }),
        ('Metadata', {
            'fields': ('created_at', 'documents_count'),
            'classes': ('collapse',)
        }),
    )
    
    def documents_count(self, obj):
        return obj.document_set.count()
    documents_count.short_description = 'Documents Created'

# Document Admin
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'template', 'status', 'created_by', 'created_at', 'signatures_count', 'has_attachment')
    list_filter = ('status', 'created_at', 'organization')
    search_fields = ('title', 'organization__name', 'created_by__email', 'template__title')
    readonly_fields = ('created_at', 'updated_at', 'signatures_count', 'has_attachment')
    list_editable = ('status',)
    list_per_page = 25
    inlines = [DocumentPermissionInline, DigitalSignatureLogInline]
    
    fieldsets = (
        ('Document Information', {
            'fields': ('organization', 'template', 'title', 'status', 'created_by')
        }),
        ('Content & Files', {
            'fields': ('final_content', 'file_attachment'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def signatures_count(self, obj):
        return obj.signatures.count()
    signatures_count.short_description = 'Signatures'
    
    def has_attachment(self, obj):
        return bool(obj.file_attachment)
    has_attachment.boolean = True
    has_attachment.short_description = 'Has File'

# Digital Signature Log Admin
@admin.register(DigitalSignatureLog)
class DigitalSignatureLogAdmin(admin.ModelAdmin):
    list_display = ('document', 'signer', 'signer_role', 'signed_at', 'has_content_hash')
    list_filter = ('signed_at', 'signer_role')
    search_fields = ('document__title', 'signer__email', 'signer_role')
    readonly_fields = ('signed_at',)
    list_per_page = 25
    
    fieldsets = (
        ('Signature Information', {
            'fields': ('document', 'signer', 'signer_role')
        }),
        ('Security & Verification', {
            'fields': ('content_hash',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('signed_at',)
        }),
    )
    
    def has_content_hash(self, obj):
        return bool(obj.content_hash)
    has_content_hash.boolean = True
    has_content_hash.short_description = 'Content Hashed'

# Document Permission Admin
@admin.register(DocumentPermission)
class DocumentPermissionAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'role', 'permission_type', 'organization')
    list_filter = ('permission_type', 'role')
    search_fields = ('document__title', 'user__email', 'role')
    list_editable = ('permission_type',)
    list_per_page = 25
    
    def organization(self, obj):
        return obj.document.organization
    organization.short_description = 'Organization'

# Custom Admin Actions for Documents
def mark_documents_pending(modeladmin, request, queryset):
    queryset.update(status='pending')
mark_documents_pending.short_description = "Mark selected documents as pending approval"

def mark_documents_signed(modeladmin, request, queryset):
    queryset.update(status='signed')
mark_documents_signed.short_description = "Mark selected documents as signed/final"

# Add actions to DocumentAdmin
DocumentAdmin.actions = [mark_documents_pending, mark_documents_signed]