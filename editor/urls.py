# editor/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from . import views

# Main router for the Spreadsheet Document CRUD/Data endpoints
router = DefaultRouter()
router.register(r'sheets', views.SpreadsheetDocumentViewSet, basename='spreadsheet-sheet')
router.register(r'templates', views.SpreadsheetTemplateViewSet, basename='spreadsheet-template')
router.register(r'organizations', views.OrganizationViewSet, basename='organization')

# Nested router for sheet-specific operations
sheets_router = routers.NestedSimpleRouter(router, r'sheets', lookup='sheet')
sheets_router.register(r'versions', views.DocumentVersionViewSet, basename='sheet-versions')
sheets_router.register(r'comments', views.DocumentCommentViewSet, basename='sheet-comments')
sheets_router.register(r'collaborators', views.DocumentCollaboratorViewSet, basename='sheet-collaborators')

# Remove this line - access logs don't need a nested router since they're typically admin-only
# sheets_router.register(r'access-logs', views.DocumentAccessLogViewSet, basename='sheet-access-logs')

# Additional nested routes for templates
templates_router = routers.NestedSimpleRouter(router, r'templates', lookup='template')
templates_router.register(r'usage', views.TemplateUsageViewSet, basename='template-usage')

urlpatterns = [
    # API Endpoints for Spreadsheet Documents
    path('', include(router.urls)),
    
    # Nested routes for sheet-specific operations
    path('', include(sheets_router.urls)),
    
    # Template-specific nested routes
    path('', include(templates_router.urls)),
    
    # Dashboard & Analytics Endpoints
    path('metrics/', views.DashboardMetricsView.as_view(), name='dashboard-metrics'),
    
    # Bulk Operations Endpoints
    path('bulk/operations/', views.BulkOperationsView.as_view(), name='bulk-operations'),
    
    # Export & Import Endpoints
    path('export/<uuid:pk>/', views.SpreadsheetExportView.as_view(), name='spreadsheet-export'),
    
    # Search & Discovery Endpoints
    path('search/', views.SpreadsheetSearchView.as_view(), name='spreadsheet-search'),
    path('tags/', views.TagListView.as_view(), name='tag-list'),
    
    # System & Maintenance Endpoints
    path('system/health/', views.SystemHealthView.as_view(), name='system-health'),
]

# Remove endpoints for views that don't exist yet to avoid import errors