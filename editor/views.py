# editor/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from django.core.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, Max, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

import logging
import hashlib
import json
import csv
from datetime import timedelta
from typing import Dict, Any, List

# Import your models
from .models import (
    SpreadsheetDocument, DocumentVersion, AuditLog, 
    DocumentCollaborator, DocumentComment, Tag, Organization
)

# Import serializers - UPDATED IMPORTS
from .serializers import (
    SpreadsheetDocumentSerializer, 
    SpreadsheetDataSerializer,
    DocumentVersionSerializer,
    DocumentCollaboratorSerializer,
    DocumentCommentSerializer,
    DashboardMetricsSerializer,
    BulkOperationSerializer,
    TagSerializer,
    OrganizationDetailSerializer,
    OrganizationBasicSerializer,
)

# Import permissions
from .permissions import (
    IsOwnerOrReadOnly, 
    IsInOrganization, 
    CanEditSpreadsheet,
    HasDashboardAccess
)

# Import utility functions
from .utils import (
    validate_spreadsheet_data, 
    calculate_spreadsheet_stats,
    export_to_excel,
    backup_document_data,
    validate_spreadsheet_structure,
    sanitize_sheet_data,
    calculate_data_complexity
)

logger = logging.getLogger(__name__)

# =============================================================================
# PAGINATION CLASSES
# =============================================================================

class StandardResultsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

class LargeResultsPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'

# =============================================================================
# THROTTLING CLASSES
# =============================================================================

class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'
    rate = '100/hour'

class SustainedRateThrottle(UserRateThrottle):
    scope = 'sustained'
    rate = '1000/day'

# =============================================================================
# MAIN VIEWSETS
# =============================================================================

class SpreadsheetDocumentViewSet(viewsets.ModelViewSet):
    """
    Advanced ViewSet for comprehensive spreadsheet document management
    with versioning, collaboration, and real-time features.
    """
    queryset = SpreadsheetDocument.objects.select_related(
        'owner', 'organization'
    ).prefetch_related(
        'collaborators', 'versions', 'audit_logs', 'tags'
    ).all()
    serializer_class = SpreadsheetDocumentSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly, IsInOrganization]
    pagination_class = StandardResultsPagination
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    filterset_fields = {
        'created_at': ['gte', 'lte', 'exact'],
        'updated_at': ['gte', 'lte', 'exact'],
        'document_type': ['exact'],
        'is_template': ['exact'],
        'is_archived': ['exact'],
    }
    search_fields = ['title', 'description', 'tags__name']
    ordering_fields = ['created_at', 'updated_at', 'title', 'size', 'view_count']
    ordering = ['-updated_at']

    def get_queryset(self):
        """Advanced queryset filtering with performance optimizations"""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by organization if user belongs to one
        if hasattr(user, 'organization') and user.organization:
            queryset = queryset.filter(organization=user.organization)
        
        # Filter by collaboration status
        collaborator_filter = self.request.query_params.get('collaborator', None)
        if collaborator_filter == 'shared_with_me':
            queryset = queryset.filter(collaborators=user)
        elif collaborator_filter == 'owned_by_me':
            queryset = queryset.filter(owner=user)
        
        # Filter by template status
        template_filter = self.request.query_params.get('template', None)
        if template_filter is not None:
            queryset = queryset.filter(is_template=template_filter.lower() == 'true')
        
        # Filter by archive status
        archive_filter = self.request.query_params.get('archived', None)
        if archive_filter is not None:
            queryset = queryset.filter(is_archived=archive_filter.lower() == 'true')
        
        # Filter by document type
        doc_type = self.request.query_params.get('type', None)
        if doc_type:
            queryset = queryset.filter(document_type=doc_type)
        
        return queryset.distinct()

    def perform_create(self, serializer):
        """Enhanced creation with template support and audit logging"""
        with transaction.atomic():
            # Handle template-based creation
            template_id = self.request.data.get('template_id')
            if template_id:
                try:
                    template = SpreadsheetDocument.objects.get(
                        id=template_id, 
                        is_template=True,
                        organization=self.request.user.organization
                    )
                    # Copy template data
                    serializer.validated_data['editor_data'] = template.editor_data.copy()
                except SpreadsheetDocument.DoesNotExist:
                    pass
            
            instance = serializer.save(owner=self.request.user)
            
            # Create initial audit log
            AuditLog.objects.create(
                document=instance,
                user=self.request.user,
                action='CREATED',
                details={'title': instance.title}
            )
            
            logger.info(f"Spreadsheet document created: {instance.id} by {self.request.user}")

    def perform_update(self, serializer):
        """Enhanced update with versioning and audit logging"""
        old_instance = self.get_object()
        
        with transaction.atomic():
            instance = serializer.save()
            
            # Create version snapshot if data changed significantly
            if 'editor_data' in serializer.validated_data:
                self._create_version_snapshot(instance, self.request.user)
            
            # Audit log
            changes = self._get_changes(old_instance, instance)
            if changes:
                AuditLog.objects.create(
                    document=instance,
                    user=self.request.user,
                    action='UPDATED',
                    details={'changes': changes}
                )

    def _create_version_snapshot(self, document, user):
        """Create a version snapshot of the document"""
        DocumentVersion.objects.create(
            document=document,
            version_data=document.editor_data.copy() if document.editor_data else {},
            created_by=user,
            version_number=document.versions.count() + 1,
            checksum=self._calculate_checksum(document.editor_data)
        )

    def _get_changes(self, old_instance, new_instance):
        """Detect and return changes between instances"""
        changes = {}
        for field in ['title', 'description', 'document_type', 'status']:
            old_val = getattr(old_instance, field)
            new_val = getattr(new_instance, field)
            if old_val != new_val:
                changes[field] = {'from': old_val, 'to': new_val}
        return changes

    def _calculate_checksum(self, data):
        """Calculate checksum for data integrity"""
        if not data:
            return ""
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode('utf-8')
        ).hexdigest()

    @action(detail=True, methods=['get', 'put', 'patch'], 
            permission_classes=[IsAuthenticated, CanEditSpreadsheet],
            throttle_classes=[UserRateThrottle])
    def data(self, request, pk=None):
        """
        Enhanced data endpoint with validation, versioning, and real-time features
        """
        document = self.get_object()
        
        if request.method == 'GET':
            # Record access
            document.record_access(request.user)
            
            # Load with caching
            cache_key = f"spreadsheet_data_{document.id}_{document.updated_at.timestamp()}"
            cached_data = cache.get(cache_key)
            
            if cached_data:
                return Response(cached_data)
            
            response_data = document.editor_data or {}
            cache.set(cache_key, response_data, timeout=300)  # 5 minutes
            
            return Response(response_data)
            
        elif request.method in ['PUT', 'PATCH']:
            return self._handle_data_save(request, document)

    def _handle_data_save(self, request, document):
        """Handle data saving with advanced validation and processing"""
        # Validate data structure
        data_serializer = SpreadsheetDataSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        
        # Advanced validation
        validation_errors = validate_spreadsheet_data(request.data)
        if validation_errors:
            return Response(
                {"errors": validation_errors}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Store old data for comparison
            old_data = document.editor_data
            
            # Sanitize and update document data
            sanitized_data = sanitize_sheet_data(request.data)
            document.editor_data = sanitized_data
            document.size = len(json.dumps(sanitized_data))
            document.last_modified_by = request.user
            document.save()
            
            # Create version if significant changes
            if self._is_significant_change(old_data, sanitized_data):
                self._create_version_snapshot(document, request.user)
            
            # Calculate statistics
            stats = calculate_spreadsheet_stats(sanitized_data)
            
            # Create audit log
            AuditLog.objects.create(
                document=document,
                user=request.user,
                action='DATA_UPDATED',
                details={
                    'size_change': len(json.dumps(sanitized_data)) - len(json.dumps(old_data or {})),
                    'stats': stats
                }
            )
            
            # Trigger async processing (if available)
            try:
                from .tasks import process_spreadsheet_webhook
                process_spreadsheet_webhook.delay(document.id, 'data_updated')
            except ImportError:
                logger.debug("Celery tasks not available, skipping webhook processing")
            
            # Clear cache
            cache.delete_pattern(f"spreadsheet_data_{document.id}_*")
            
            logger.info(f"Spreadsheet data updated: {document.id} by {request.user}")
            
            return Response({
                "id": document.pk,
                "status": "Spreadsheet content updated successfully",
                "last_updated": document.updated_at,
                "checksum": self._calculate_checksum(document.editor_data),
                "statistics": stats,
                "version_count": document.versions.count()
            })

    def _is_significant_change(self, old_data, new_data):
        """Determine if changes are significant enough for versioning"""
        if not old_data:
            return True
        
        try:
            old_str = json.dumps(old_data, sort_keys=True)
            new_str = json.dumps(new_data, sort_keys=True)
            
            # Consider it significant if more than 10% changed
            size_change = abs(len(new_str) - len(old_str)) / max(len(old_str), 1)
            return size_change > 0.1
        except (TypeError, ValueError):
            return True

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplicate a spreadsheet document"""
        original = self.get_object()
        
        with transaction.atomic():
            duplicate = SpreadsheetDocument.objects.create(
                title=f"{original.title} (Copy)",
                description=original.description,
                editor_data=original.editor_data.copy() if original.editor_data else {},
                document_type=original.document_type,
                owner=request.user,
                organization=original.organization,
                is_template=False,
                status='draft'
            )
            
            # Copy collaborators
            duplicate.collaborators.set(original.collaborators.all())
            
            # Copy tags
            duplicate.tags.set(original.tags.all())
            
            # Create audit log
            AuditLog.objects.create(
                document=duplicate,
                user=request.user,
                action='CREATED',
                details={'source': f'Duplicated from {original.title}', 'original_id': original.id}
            )
            
            serializer = self.get_serializer(duplicate)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive/unarchive a document"""
        document = self.get_object()
        document.is_archived = not document.is_archived
        document.save()
        
        action = 'ARCHIVED' if document.is_archived else 'RESTORED'
        AuditLog.objects.create(
            document=document,
            user=request.user,
            action=action,
            details={}
        )
        
        return Response({
            "status": f"Document {action.lower()} successfully",
            "is_archived": document.is_archived
        })

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Get version history"""
        document = self.get_object()
        versions = document.versions.all().order_by('-created_at')
        page = self.paginate_queryset(versions)
        
        if page is not None:
            serializer = DocumentVersionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = DocumentVersionSerializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore_version(self, request, pk=None):
        """Restore a specific version"""
        document = self.get_object()
        version_id = request.data.get('version_id')
        
        try:
            version = DocumentVersion.objects.get(
                id=version_id, 
                document=document
            )
            
            with transaction.atomic():
                # Create backup of current version
                self._create_version_snapshot(document, request.user)
                
                # Restore old version
                document.editor_data = version.version_data
                document.size = len(json.dumps(version.version_data)) if version.version_data else 0
                document.last_modified_by = request.user
                document.save()
                
                AuditLog.objects.create(
                    document=document,
                    user=request.user,
                    action='VERSION_RESTORED',
                    details={'version_id': version_id, 'version_number': version.version_number}
                )
        
            return Response({"status": "Version restored successfully"})
            
        except DocumentVersion.DoesNotExist:
            return Response(
                {"error": "Version not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        """Export spreadsheet to various formats"""
        document = self.get_object()
        format_type = request.query_params.get('format', 'json')
        
        try:
            if format_type == 'json':
                response_data = document.editor_data or {}
                return Response(response_data)
                
            elif format_type == 'excel':
                file_path = export_to_excel(document.editor_data, document.title)
                # In a real implementation, you'd return the file for download
                return Response({
                    "file_path": file_path,
                    "status": "Export completed",
                    "download_url": f"/api/editor/download/{document.uuid}/"
                })
            else:
                return Response(
                    {"error": "Unsupported format"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            logger.error(f"Export failed: {str(e)}")
            return Response(
                {"error": "Export failed"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def bulk_operations(self, request):
        """Perform bulk operations on multiple documents"""
        serializer = BulkOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        operation = serializer.validated_data['operation']
        document_ids = serializer.validated_data['document_ids']
        
        documents = self.get_queryset().filter(id__in=document_ids)
        
        if operation == 'archive':
            documents.update(is_archived=True)
            message = f"{documents.count()} documents archived"
        elif operation == 'unarchive':
            documents.update(is_archived=False)
            message = f"{documents.count()} documents unarchived"
        elif operation == 'delete':
            count = documents.count()
            documents.delete()
            message = f"{count} documents deleted"
        elif operation == 'change_owner':
            new_owner_id = serializer.validated_data['new_owner_id']
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                new_owner = User.objects.get(id=new_owner_id)
                documents.update(owner=new_owner)
                message = f"Ownership transferred for {documents.count()} documents"
            except User.DoesNotExist:
                return Response(
                    {"error": "New owner not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {"error": "Unsupported operation"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({"status": message})

    @action(detail=False, methods=['get'])
    def templates(self, request):
        """Get available templates"""
        templates = self.get_queryset().filter(
            is_template=True,
            organization=request.user.organization
        )
        page = self.paginate_queryset(templates)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(templates, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recently accessed documents"""
        recent_docs = self.get_queryset().filter(
            last_accessed_at__isnull=False
        ).order_by('-last_accessed_at')[:10]
        
        serializer = self.get_serializer(recent_docs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Share document with collaborators"""
        document = self.get_object()
        collaborator_ids = request.data.get('collaborators', [])
        permission_level = request.data.get('permission_level', 'view')
        
        if not document.can_share(request.user):
            return Response(
                {"error": "You don't have permission to share this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        collaborators_added = 0
        for user_id in collaborator_ids:
            try:
                collaborator = User.objects.get(id=user_id)
                DocumentCollaborator.objects.get_or_create(
                    document=document,
                    user=collaborator,
                    defaults={
                        'permission_level': permission_level,
                        'added_by': request.user
                    }
                )
                collaborators_added += 1
            except User.DoesNotExist:
                continue
        
        AuditLog.objects.create(
            document=document,
            user=request.user,
            action='SHARED',
            details={'collaborators_added': collaborators_added, 'permission_level': permission_level}
        )
        
        return Response({
            "status": f"Document shared with {collaborators_added} collaborators",
            "collaborators_added": collaborators_added
        })

# =============================================================================
# DOCUMENT VERSION VIEWSET
# =============================================================================

class DocumentVersionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing document versions.
    """
    serializer_class = DocumentVersionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    
    def get_queryset(self):
        document_id = self.kwargs.get('document_pk')
        return DocumentVersion.objects.filter(document_id=document_id).select_related('created_by')
    
    @action(detail=True, methods=['post'])
    def restore(self, request, document_pk=None, pk=None):
        """Restore this version"""
        version = self.get_object()
        document = version.document
        
        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to edit this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            # Create backup of current version
            DocumentVersion.objects.create(
                document=document,
                version_data=document.editor_data.copy() if document.editor_data else {},
                created_by=request.user,
                version_number=document.versions.count() + 1,
                checksum=hashlib.md5(
                    json.dumps(document.editor_data, sort_keys=True).encode('utf-8')
                ).hexdigest() if document.editor_data else ""
            )
            
            # Restore the selected version
            document.editor_data = version.version_data
            document.size = len(json.dumps(version.version_data)) if version.version_data else 0
            document.last_modified_by = request.user
            document.save()
            
            AuditLog.objects.create(
                document=document,
                user=request.user,
                action='VERSION_RESTORED',
                details={'version_id': version.id, 'version_number': version.version_number}
            )
        
        return Response({"status": "Version restored successfully"})

# =============================================================================
# COLLABORATOR VIEWSET
# =============================================================================

class DocumentCollaboratorViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing document collaborators.
    """
    serializer_class = DocumentCollaboratorSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    
    def get_queryset(self):
        document_id = self.kwargs.get('document_pk')
        return DocumentCollaborator.objects.filter(document_id=document_id).select_related('user', 'added_by')
    
    def perform_create(self, serializer):
        document_id = self.kwargs.get('document_pk')
        document = get_object_or_404(SpreadsheetDocument, id=document_id)
        
        if not document.can_share(self.request.user):
            raise PermissionDenied("You don't have permission to share this document")
        
        serializer.save(document_id=document_id, added_by=self.request.user)

# =============================================================================
# COMMENT VIEWSET
# =============================================================================

class DocumentCommentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing document comments.
    """
    serializer_class = DocumentCommentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    
    def get_queryset(self):
        document_id = self.kwargs.get('document_pk')
        return DocumentComment.objects.filter(document_id=document_id).select_related('user')
    
    def perform_create(self, serializer):
        document_id = self.kwargs.get('document_pk')
        document = get_object_or_404(SpreadsheetDocument, id=document_id)
        
        if not document.can_view(self.request.user):
            raise PermissionDenied("You don't have permission to comment on this document")
        
        serializer.save(document_id=document_id, user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, document_pk=None, pk=None):
        """Mark comment as resolved"""
        comment = self.get_object()
        comment.is_resolved = True
        comment.save()
        
        return Response({"status": "Comment resolved"})

# =============================================================================
# DASHBOARD & ANALYTICS VIEWS
# =============================================================================

class DashboardMetricsView(APIView):
    """
    Advanced dashboard metrics with real-time analytics, caching, and comprehensive reporting
    """
    permission_classes = [IsAuthenticated, HasDashboardAccess]
    throttle_classes = [UserRateThrottle]

    def get(self, request, *args, **kwargs):
        user = request.user
        time_range = request.query_params.get('time_range', '7d')  # 7d, 30d, 90d, 1y
        
        # Cache key based on user and time range
        cache_key = f"dashboard_metrics_{user.id}_{time_range}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return Response(cached_data)
        
        try:
            dashboard_data = self._calculate_metrics(user, time_range)
            
            # Validate and serialize response
            serializer = DashboardMetricsSerializer(data=dashboard_data)
            serializer.is_valid(raise_exception=True)
            
            # Cache for 5 minutes
            cache.set(cache_key, serializer.data, timeout=300)
            
            # Trigger async report generation (if available)
            try:
                from .tasks import generate_dashboard_report
                generate_dashboard_report.delay(user.id, time_range)
            except ImportError:
                logger.debug("Celery tasks not available, skipping report generation")
            
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Dashboard metrics error: {str(e)}")
            return Response(
                {"error": "Failed to generate dashboard metrics"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _calculate_metrics(self, user, time_range):
        """Calculate comprehensive dashboard metrics"""
        date_filter = self._get_date_filter(time_range)
        
        # 1. User & Workflow Summary (Enhanced)
        user_summary = self._get_user_summary(user, date_filter)
        
        # 2. Organization KPIs (Advanced)
        org_kpis = self._get_organization_kpis(user, date_filter)
        
        # 3. Document Analytics
        document_analytics = self._get_document_analytics(user, date_filter)
        
        # 4. Performance Metrics
        performance_metrics = self._get_performance_metrics(user, date_filter)
        
        # 5. Real-time Activity Feed
        recent_activity = self._get_recent_activity(user, date_filter)
        
        # 6. Predictive Insights
        predictive_insights = self._get_predictive_insights(user)

        return {
            'timestamp': timezone.now().isoformat(),
            'time_range': time_range,
            'user_summary': user_summary,
            'organization_kpis': org_kpis,
            'document_analytics': document_analytics,
            'performance_metrics': performance_metrics,
            'recent_activity': recent_activity,
            'predictive_insights': predictive_insights,
            'data_freshness': 'real_time'
        }

    def _get_date_filter(self, time_range):
        """Get date filter based on time range"""
        now = timezone.now()
        if time_range == '24h':
            return now - timedelta(hours=24)
        elif time_range == '7d':
            return now - timedelta(days=7)
        elif time_range == '30d':
            return now - timedelta(days=30)
        elif time_range == '90d':
            return now - timedelta(days=90)
        elif time_range == '1y':
            return now - timedelta(days=365)
        else:
            return now - timedelta(days=7)  # Default

    def _get_user_summary(self, user, date_filter):
        """Enhanced user summary with trend analysis"""
        user_docs = SpreadsheetDocument.objects.filter(owner=user)
        recent_docs = user_docs.filter(created_at__gte=date_filter)
        
        # Calculate trends
        previous_period = self._get_previous_period(date_filter)
        previous_docs = user_docs.filter(
            created_at__gte=previous_period['start'],
            created_at__lt=previous_period['end']
        )
        
        doc_growth = self._calculate_growth(recent_docs.count(), previous_docs.count())
        
        # Calculate storage usage
        storage_usage = user_docs.aggregate(
            total_size=Coalesce(Sum('size'), Value(0))
        )['total_size']
        
        return {
            'documents_uploaded_total': user_docs.count(),
            'documents_uploaded_recent': recent_docs.count(),
            'upload_growth_percentage': doc_growth,
            'active_collaborations': user_docs.filter(collaborators__isnull=False).count(),
            'storage_used_mb': round(storage_usage / (1024 * 1024), 2),
            'templates_created': user_docs.filter(is_template=True).count(),
            'recent_activity_score': self._calculate_activity_score(user, date_filter),
        }

    def _get_organization_kpis(self, user, date_filter):
        """Advanced organization KPIs"""
        if not hasattr(user, 'organization') or not user.organization:
            return {}
            
        org_docs = SpreadsheetDocument.objects.filter(organization=user.organization)
        recent_org_docs = org_docs.filter(created_at__gte=date_filter)
        
        # Calculate organization metrics
        total_size = org_docs.aggregate(total_size=Coalesce(Sum('size'), Value(0)))['total_size']
        active_users = DocumentCollaborator.objects.filter(
            document__organization=user.organization
        ).values('user').distinct().count()
        
        return {
            'active_projects': org_docs.filter(status='active').count(),
            'total_documents_stored': org_docs.count(),
            'documents_created_recent': recent_org_docs.count(),
            'active_users': active_users,
            'storage_used_gb': round(total_size / (1024 * 1024 * 1024), 2),
            'collaboration_rate': self._calculate_collaboration_rate(user.organization),
        }

    def _get_document_analytics(self, user, date_filter):
        """Comprehensive document analytics"""
        user_docs = SpreadsheetDocument.objects.filter(owner=user)
        
        # Type breakdown with percentages
        doc_types = user_docs.values('document_type').annotate(
            count=Count('id'),
            total_size=Sum('size')
        ).order_by('-count')
        
        total_docs = user_docs.count()
        type_breakdown = {
            item['document_type']: {
                'count': item['count'],
                'percentage': round((item['count'] / total_docs) * 100, 1) if total_docs > 0 else 0,
                'total_size_mb': round(item['total_size'] / (1024 * 1024), 2) if item['total_size'] else 0
            }
            for item in doc_types
        }
        
        # Size analytics
        size_stats = user_docs.aggregate(
            avg_size=Avg('size'),
            max_size=Coalesce(Max('size'), Value(0)),
            total_size=Coalesce(Sum('size'), Value(0))
        )
        
        return {
            'type_breakdown': type_breakdown,
            'size_analytics': {
                'average_size_kb': round((size_stats['avg_size'] or 0) / 1024, 2),
                'largest_document_mb': round(size_stats['max_size'] / (1024 * 1024), 2),
                'total_storage_mb': round(size_stats['total_size'] / (1024 * 1024), 2),
            },
            'documents_by_status': dict(user_docs.values('status').annotate(count=Count('id')).values_list('status', 'count')),
            'recent_activity_trend': self._get_activity_trend(user, date_filter),
        }

    def _get_performance_metrics(self, user, date_filter):
        """System and user performance metrics"""
        # These would typically come from monitoring systems
        recent_audits = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        )
        
        return {
            'response_time_ms': 45,
            'api_success_rate': 99.8,
            'user_engagement_score': self._calculate_engagement_score(user, date_filter),
            'recent_actions': recent_audits.count(),
            'most_used_features': self._get_most_used_features(user, date_filter),
        }

    def _get_recent_activity(self, user, date_filter):
        """Recent user and system activity"""
        recent_audits = AuditLog.objects.filter(
            Q(document__owner=user) | Q(user=user),
            timestamp__gte=date_filter
        ).select_related('document', 'user').order_by('-timestamp')[:10]
        
        return [
            {
                'action': audit.action,
                'document_title': audit.document.title if audit.document else 'System',
                'user': audit.user.username,
                'timestamp': audit.timestamp.isoformat(),
                'details': audit.details
            }
            for audit in recent_audits
        ]

    def _get_predictive_insights(self, user):
        """Predictive analytics and insights"""
        user_docs = SpreadsheetDocument.objects.filter(owner=user)
        total_size = user_docs.aggregate(total_size=Coalesce(Sum('size'), Value(0)))['total_size']
        storage_used_gb = total_size / (1024 * 1024 * 1024)
        
        insights = {
            'predicted_storage_growth_mb': 250,
            'storage_health': 'good' if storage_used_gb < 1 else 'warning' if storage_used_gb < 5 else 'critical',
            'recommended_actions': []
        }
        
        if storage_used_gb > 1:
            insights['recommended_actions'].append("Consider archiving old documents to free up space")
        
        if user_docs.filter(is_archived=True).count() > 10:
            insights['recommended_actions'].append("You have many archived documents that could be permanently deleted")
        
        collaboration_rate = user_docs.filter(collaborators__isnull=False).count() / max(user_docs.count(), 1)
        if collaboration_rate < 0.3:
            insights['recommended_actions'].append("Consider sharing more documents to improve collaboration")
        
        return insights

    def _get_previous_period(self, date_filter):
        """Get previous period for comparison"""
        period_days = (timezone.now() - date_filter).days
        return {
            'start': date_filter - timedelta(days=period_days),
            'end': date_filter
        }

    def _calculate_growth(self, current, previous):
        """Calculate growth percentage"""
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 1)

    def _get_activity_trend(self, user, date_filter):
        """Get document activity trend over time"""
        # Simplified trend calculation
        recent_count = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        ).count()
        
        previous_period = self._get_previous_period(date_filter)
        previous_count = AuditLog.objects.filter(
            user=user,
            timestamp__gte=previous_period['start'],
            timestamp__lt=previous_period['end']
        ).count()
        
        growth = self._calculate_growth(recent_count, previous_count)
        
        return {
            'trend': 'increasing' if growth > 0 else 'decreasing' if growth < 0 else 'stable',
            'velocity': growth,
            'momentum': 'accelerating' if growth > 10 else 'decelerating' if growth < -10 else 'stable'
        }

    def _calculate_activity_score(self, user, date_filter):
        """Calculate user activity score"""
        actions = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        ).count()
        
        documents_created = SpreadsheetDocument.objects.filter(
            owner=user,
            created_at__gte=date_filter
        ).count()
        
        return min(100, (actions * 0.5) + (documents_created * 10))

    def _calculate_collaboration_rate(self, organization):
        """Calculate organization collaboration rate"""
        total_docs = SpreadsheetDocument.objects.filter(organization=organization).count()
        if total_docs == 0:
            return 0.0
        
        collaborative_docs = SpreadsheetDocument.objects.filter(
            organization=organization,
            collaborators__isnull=False
        ).distinct().count()
        
        return round((collaborative_docs / total_docs) * 100, 1)

    def _calculate_engagement_score(self, user, date_filter):
        """Calculate user engagement score"""
        actions = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        ).count()
        
        days_active = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        ).dates('timestamp', 'day').distinct().count()
        
        total_days = (timezone.now() - date_filter).days
        
        if total_days == 0:
            return 0.0
        
        activity_score = min(100, (actions / max(total_days, 1)) * 10)
        consistency_score = (days_active / total_days) * 100
        
        return round((activity_score + consistency_score) / 2, 1)

    def _get_most_used_features(self, user, date_filter):
        """Get most used features by the user"""
        feature_usage = AuditLog.objects.filter(
            user=user,
            timestamp__gte=date_filter
        ).values('action').annotate(count=Count('id')).order_by('-count')[:5]
        
        return {item['action']: item['count'] for item in feature_usage}

# =============================================================================
# ADDITIONAL VIEWS
# =============================================================================

class TagListView(APIView):
    """List all available tags"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        tags = Tag.objects.filter(
            Q(organization=request.user.organization) | 
            Q(organization__isnull=True)
        ).distinct()
        serializer = TagSerializer(tags, many=True)
        return Response(serializer.data)

class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for organization information"""
    serializer_class = OrganizationBasicSerializer  # CHANGED FROM OrganizationSerializer
    permission_classes = [IsAuthenticated, IsInOrganization]
    
    def get_queryset(self):
        if hasattr(self.request.user, 'organization') and self.request.user.organization:
            return Organization.objects.filter(id=self.request.user.organization.id)
        return Organization.objects.none()

class SystemHealthView(APIView):
    """System health check endpoint"""
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        health_status = {
            'database': self._check_database(),
            'cache': self._check_cache(),
            'celery': self._check_celery(),
            'storage': self._check_storage(),
            'timestamp': timezone.now().isoformat()
        }
        
        overall_status = 'healthy' if all(health_status.values()) else 'degraded'
        health_status['status'] = overall_status
        
        return Response(health_status)
    
    def _check_database(self):
        try:
            SpreadsheetDocument.objects.count()
            return True
        except Exception:
            return False
    
    def _check_cache(self):
        try:
            cache.set('health_check', 'ok', 1)
            return cache.get('health_check') == 'ok'
        except Exception:
            return False
    
    def _check_celery(self):
        # This would typically check Celery worker status
        return True
    
    def _check_storage(self):
        # This would check available disk space
        return True

# =============================================================================
# FILE EXPORT VIEW
# =============================================================================

class SpreadsheetExportView(APIView):
    """Export spreadsheet to downloadable files"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        try:
            document = SpreadsheetDocument.objects.get(pk=pk)
            
            if not document.can_view(request.user):
                return Response(
                    {"error": "You don't have permission to access this document"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            format_type = request.query_params.get('format', 'json')
            
            if format_type == 'json':
                response = JsonResponse(document.editor_data or {}, json_dumps_params={'indent': 2})
                response['Content-Disposition'] = f'attachment; filename="{document.title}.json"'
                return response
                
            elif format_type == 'csv':
                # Simple CSV export implementation
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="{document.title}.csv"'
                
                writer = csv.writer(response)
                if document.editor_data and 'sheets' in document.editor_data:
                    for sheet in document.editor_data['sheets']:
                        writer.writerow([f"Sheet: {sheet.get('name', 'Unnamed')}"])
                        if 'cells' in sheet:
                            for cell_ref, cell_data in sheet['cells'].items():
                                value = cell_data.get('value', '')
                                writer.writerow([cell_ref, str(value)])
                        writer.writerow([])  # Empty row between sheets
                
                return response
                
            else:
                return Response(
                    {"error": "Unsupported export format"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except SpreadsheetDocument.DoesNotExist:
            return Response(
                {"error": "Document not found"},
                status=status.HTTP_404_NOT_FOUND
            )

# =============================================================================
# SEARCH VIEW
# =============================================================================

class SpreadsheetSearchView(APIView):
    """Advanced search across spreadsheets"""
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    
    def get(self, request):
        query = request.query_params.get('q', '')
        if not query or len(query.strip()) < 2:
            return Response(
                {"error": "Search query must be at least 2 characters long"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get user's accessible documents
        documents = SpreadsheetDocument.get_user_documents(request.user)
        
        # Search across multiple fields
        search_results = documents.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()
        
        # Apply pagination
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(search_results, request, view=self)
        
        if page is not None:
            serializer = SpreadsheetDocumentSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = SpreadsheetDocumentSerializer(search_results, many=True)
        return Response(serializer.data)
    

    # =============================================================================
# MISSING VIEW CLASSES FOR URLS
# =============================================================================

class SpreadsheetTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet specifically for template management."""
    serializer_class = SpreadsheetDocumentSerializer
    permission_classes = [IsAuthenticated, IsInOrganization]
    pagination_class = StandardResultsPagination
    
    def get_queryset(self):
        return SpreadsheetDocument.objects.filter(
            is_template=True,
            organization=self.request.user.organization
        ).select_related('owner', 'organization')

class TemplateUsageViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for template usage statistics."""
    permission_classes = [IsAuthenticated, IsInOrganization]
    
    def get_queryset(self):
        template_id = self.kwargs.get('template_pk')
        return SpreadsheetDocument.objects.filter(
            template_source_id=template_id,
            organization=self.request.user.organization
        )
    
    def list(self, request, template_pk=None):
        """Get template usage statistics"""
        template = get_object_or_404(SpreadsheetDocument, pk=template_pk, is_template=True)
        
        if not template.can_view(request.user):
            return Response(
                {"error": "You don't have permission to access this template"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        usage_stats = {
            'total_usage': self.get_queryset().count(),
            'recent_usage': self.get_queryset().filter(
                created_at__gte=timezone.now() - timedelta(days=30)
            ).count(),
        }
        
        return Response(usage_stats)

class UsageAnalyticsView(APIView):
    """Detailed usage analytics"""
    permission_classes = [IsAuthenticated, HasDashboardAccess]
    
    def get(self, request):
        return Response({"message": "Usage analytics endpoint"})

class PerformanceMetricsView(APIView):
    """Performance metrics"""
    permission_classes = [IsAuthenticated, HasDashboardAccess]
    
    def get(self, request):
        return Response({"message": "Performance metrics endpoint"})

class BulkExportView(APIView):
    """Bulk export documents"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({"message": "Bulk export endpoint"})

class CollaborationInvitationViewSet(viewsets.ModelViewSet):
    """Manage collaboration invitations"""
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return DocumentCollaborator.objects.filter(added_by=self.request.user)

class SpreadsheetImportView(APIView):
    """Import spreadsheet data"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({"message": "Import endpoint"})

class SystemStatisticsView(APIView):
    """System statistics"""
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        return Response({"message": "System statistics endpoint"})

class AuditLogView(APIView):
    """Audit logs view"""
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        logs = AuditLog.objects.all().order_by('-timestamp')[:100]
        # You would create an AuditLogSerializer for this
        return Response({"logs": "Audit logs data"})

class ActivityReportView(APIView):
    """Activity reports"""
    permission_classes = [IsAuthenticated, HasDashboardAccess]
    
    def get(self, request):
        return Response({"message": "Activity report endpoint"})

class SpreadsheetWebhookView(APIView):
    """Webhook for real-time updates"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({"message": "Webhook processed"})

class BulkOperationsView(APIView):
    """
    Handle bulk operations on multiple documents.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BulkOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        operation = serializer.validated_data['operation']
        document_ids = serializer.validated_data['document_ids']
        
        documents = SpreadsheetDocument.get_user_documents(request.user).filter(
            id__in=document_ids
        )
        
        if operation == 'archive':
            documents.update(is_archived=True)
            message = f"{documents.count()} documents archived"
        elif operation == 'unarchive':
            documents.update(is_archived=False)
            message = f"{documents.count()} documents unarchived"
        elif operation == 'delete':
            count = documents.count()
            documents.delete()
            message = f"{count} documents deleted"
        elif operation == 'change_owner':
            new_owner_id = serializer.validated_data.get('new_owner_id')
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                new_owner = User.objects.get(id=new_owner_id)
                documents.update(owner=new_owner)
                message = f"Ownership transferred for {documents.count()} documents"
            except User.DoesNotExist:
                return Response(
                    {"error": "New owner not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {"error": "Unsupported operation"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({"status": message})