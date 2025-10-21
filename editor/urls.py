# editor/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SpreadsheetDocumentViewSet, DashboardMetricsView

# Router for the Spreadsheet Document CRUD/Data endpoints
router = DefaultRouter()
router.register(r'sheets', SpreadsheetDocumentViewSet, basename='spreadsheet-sheet')

urlpatterns = [
    # API Endpoints for Spreadsheet Documents
    # POST /api/editor/sheets/ (Create)
    # GET/PUT/PATCH /api/editor/sheets/{pk}/ (Retrieve/Update Metadata)
    # GET/PUT/PATCH /api/editor/sheets/{pk}/data/ (Retrieve/Update Spreadsheet JSON)
    path('', include(router.urls)), 
    
    # API Endpoint for Dashboard Metrics
    # GET /api/editor/metrics/
    path('metrics/', DashboardMetricsView.as_view(), name='dashboard-metrics'),
]