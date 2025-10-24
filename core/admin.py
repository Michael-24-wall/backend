from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import CustomUser, Organization, OrganizationMembership, Invitation

# Custom User Admin
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'organization', 'is_verified', 'is_staff', 'is_active')
    list_filter = ('is_verified', 'is_staff', 'is_superuser', 'is_active', 'organization')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    readonly_fields = ('last_login', 'date_joined')
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'organization')}),
        ('Permissions', {
            'fields': (
                'is_verified', 'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions'
            )
        }),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email', 'first_name', 'last_name', 'organization',
                'password1', 'password2', 'is_verified', 'is_staff', 'is_active'
            ),
        }),
    )

# Organization Admin
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'subdomain', 'is_active', 'created_at', 'owner_info', 'active_members_count')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'subdomain')
    readonly_fields = ('subdomain', 'created_at', 'owner_info', 'active_members_count')
    list_per_page = 20
    
    def owner_info(self, obj):
        owner = obj.owner
        if owner:
            return f"{owner.email} ({owner.get_full_name()})"
        return "No owner"
    owner_info.short_description = 'Owner'
    
    def active_members_count(self, obj):
        return obj.active_members_count
    active_members_count.short_description = 'Active Members'

# Organization Membership Admin
@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'is_active', 'created_at', 'role_weight')
    list_filter = ('role', 'is_active', 'created_at', 'organization')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'organization__name')
    readonly_fields = ('created_at', 'updated_at', 'role_weight')
    list_editable = ('role', 'is_active')
    list_per_page = 25
    
    def role_weight(self, obj):
        return obj.role_weight
    role_weight.short_description = 'Role Weight'

# Invitation Admin
@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'organization', 'role', 'invited_by', 'is_accepted', 'created_at', 'expires_at', 'is_expired')
    list_filter = ('is_accepted', 'role', 'created_at', 'organization')
    search_fields = ('email', 'organization__name', 'invited_by__email')
    readonly_fields = ('token', 'created_at', 'is_expired', 'days_until_expiry')
    list_editable = ('role',)
    list_per_page = 20
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired'
    
    def days_until_expiry(self, obj):
        days = obj.days_until_expiry
        if days is None:
            return "No expiry"
        elif days < 0:
            return f"Expired {abs(days)} days ago"
        else:
            return f"{days} days"
    days_until_expiry.short_description = 'Expiry Status'

# Optional: Custom Admin Site Header
admin.site.site_header = "Workflow Management System Admin"
admin.site.site_title = "Workflow Admin"
admin.site.index_title = "Welcome to Workflow Management System"