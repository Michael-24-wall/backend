from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.core.files.base import ContentFile
import os
import json
from datetime import datetime
from django.db import models  
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser

from .models import DocumentTemplate, Document, DigitalSignatureLog
from .serializers import (
    DocumentTemplateSerializer, 
    DocumentCreateSerializer, 
    DocumentDetailSerializer, 
    DigitalSignatureSerializer,
    DocumentUpdateSerializer,
    DocumentShareSerializer,
    DocumentCommentSerializer
)

class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Document Templates.
    Templates are organization-specific blueprints for documents.
    """
    serializer_class = DocumentTemplateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'delete']
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']

    def get_queryset(self):
        """Filter templates to only show those belonging to the user's primary organization."""
        user = self.request.user
        if not user.is_authenticated or not user.organization:
            return DocumentTemplate.objects.none() 
            
        return DocumentTemplate.objects.filter(organization=user.organization)

    @swagger_auto_schema(
        operation_description="Create a new document template for the user's organization.",
        responses={201: DocumentTemplateSerializer}
    )
    def create(self, request, *args, **kwargs):
        """Custom create to automatically link the organization and creator."""
        user = request.user
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Inject organization and created_by fields
        serializer.save(organization=user.organization, created_by=user)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # --- NEW: Template Custom Actions ---
    
    @swagger_auto_schema(
        method='post',
        operation_description="Duplicate an existing template",
        responses={201: DocumentTemplateSerializer}
    )
    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate_template(self, request, pk=None):
        """Duplicate a template with a new name"""
        template = get_object_or_404(self.get_queryset(), pk=pk)
        
        new_template = DocumentTemplate.objects.create(
            name=f"{template.name} (Copy)",
            description=template.description,
            content=template.content,
            organization=template.organization,
            created_by=request.user
        )
        
        serializer = self.get_serializer(new_template)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        method='get',
        operation_description="Get template usage statistics",
        responses={200: openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'template_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'template_name': openapi.Schema(type=openapi.TYPE_STRING),
                'documents_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                'last_used': openapi.Schema(type=openapi.TYPE_STRING),
            }
        )}
    )
    @action(detail=True, methods=['get'], url_path='usage-stats')
    def template_usage_stats(self, request, pk=None):
        """Get usage statistics for a template"""
        template = get_object_or_404(self.get_queryset(), pk=pk)
        
        documents_count = Document.objects.filter(template=template).count()
        last_used_doc = Document.objects.filter(template=template).order_by('-created_at').first()
        
        stats = {
            'template_id': template.id,
            'template_name': template.name,
            'documents_count': documents_count,
            'last_used': last_used_doc.created_at.isoformat() if last_used_doc else None,
        }
        
        return Response(stats)

# -----------------------------------------------------------------------------

class DocumentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Document Instances and their full lifecycle.
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, filters.DjangoFilterBackend]
    search_fields = ['title', 'final_content', 'status']
    ordering_fields = ['title', 'created_at', 'updated_at', 'status']
    ordering = ['-updated_at']
    filterset_fields = ['status', 'template', 'created_by']

    def get_serializer_class(self):
        """Swaps serializers based on the action for optimized payload."""
        if self.action == 'create':
            return DocumentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return DocumentUpdateSerializer
        return DocumentDetailSerializer

    def get_queryset(self):
        """Filter documents to only show those belonging to the user's primary organization."""
        user = self.request.user
        if not user.is_authenticated or not user.organization:
            return Document.objects.none()

        # Base queryset - user's organization documents
        queryset = Document.objects.filter(organization=user.organization)
        
        # Optional: Filter by additional criteria from query params
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        template_filter = self.request.query_params.get('template')
        if template_filter:
            queryset = queryset.filter(template_id=template_filter)
            
        return queryset.select_related('template', 'created_by', 'organization').prefetch_related('signatures')

    # --- Standard CRUD Operations ---

    @swagger_auto_schema(
        operation_description="Create a new document instance from a template.",
        request_body=DocumentCreateSerializer,
        responses={201: DocumentDetailSerializer}
    )
    def create(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Inject organization and created_by fields
        serializer.save(organization=user.organization, created_by=user)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_description="Update a document instance.",
        request_body=DocumentUpdateSerializer,
        responses={200: DocumentDetailSerializer}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    # --- NEW: Enhanced Custom Actions ---

    @swagger_auto_schema(
        method='post',
        operation_description="Upload a file attachment to the document",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'file': openapi.Schema(type=openapi.TYPE_FILE, description='File to upload'),
                'description': openapi.Schema(type=openapi.TYPE_STRING, description='File description')
            }
        ),
        responses={
            200: openapi.Response('File uploaded successfully'),
            400: 'No file provided or upload failed'
        }
    )
    @action(detail=True, methods=['post'], url_path='upload-attachment', parser_classes=[MultiPartParser, FormParser])
    def upload_attachment(self, request, pk=None):
        """Upload file attachment to document"""
        document = get_object_or_404(self.get_queryset(), pk=pk)
        
        if 'file' not in request.FILES:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = request.FILES['file']
        description = request.data.get('description', '')
        
        # Validate file size (e.g., 10MB limit)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response({'error': 'File size exceeds 10MB limit'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Save file to document
        document.file_attachment.save(uploaded_file.name, uploaded_file)
        document.file_description = description
        document.save()
        
        return Response({
            'detail': 'File uploaded successfully',
            'file_url': document.file_attachment.url if document.file_attachment else None,
            'file_name': uploaded_file.name
        })

    @swagger_auto_schema(
        method='get',
        operation_description="Download document file attachment",
        responses={
            200: 'File content',
            404: 'File not found'
        }
    )
    @action(detail=True, methods=['get'], url_path='download')
    def download_document(self, request, pk=None):
        """Download document file attachment"""
        document = get_object_or_404(self.get_queryset(), pk=pk)
        
        if not document.file_attachment:
            return Response({'error': 'No file attachment found'}, status=status.HTTP_404_NOT_FOUND)
        
        response = HttpResponse(document.file_attachment, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(document.file_attachment.name)}"'
        return response

    @swagger_auto_schema(
        method='post',
        operation_description="Share document with organization members",
        request_body=DocumentShareSerializer,
        responses={200: 'Document shared successfully'}
    )
    @action(detail=True, methods=['post'], url_path='share')
    def share_document(self, request, pk=None):
        """Share document with specific users or roles in organization"""
        document = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DocumentShareSerializer(data=request.data)
        
        if serializer.is_valid():
            # In a real implementation, you'd create sharing records
            # For now, return success message
            share_with = serializer.validated_data.get('share_with', [])
            permission_level = serializer.validated_data.get('permission_level', 'view')
            
            return Response({
                'detail': f'Document shared with {len(share_with)} users with {permission_level} permissions',
                'shared_with': share_with,
                'permission_level': permission_level
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        method='get',
        operation_description="Get document version history",
        responses={200: openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'version': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'content': openapi.Schema(type=openapi.TYPE_STRING),
                    'created_by': openapi.Schema(type=openapi.TYPE_STRING),
                    'created_at': openapi.Schema(type=openapi.TYPE_STRING),
                }
            )
        )}
    )
    @action(detail=True, methods=['get'], url_path='version-history')
    def version_history(self, request, pk=None):
        """Get document version history (simulated)"""
        document = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Simulate version history - in real app, you'd have a Version model
        history = [
            {
                'version': 1,
                'content': document.final_content[:100] + '...' if len(document.final_content) > 100 else document.final_content,
                'created_by': f"{document.created_by.first_name} {document.created_by.last_name}",
                'created_at': document.created_at.isoformat()
            }
        ]
        
        return Response(history)

    @swagger_auto_schema(
        method='post',
        operation_description="Add comment to document",
        request_body=DocumentCommentSerializer,
        responses={201: DocumentCommentSerializer}
    )
    @action(detail=True, methods=['post'], url_path='add-comment')
    def add_comment(self, request, pk=None):
        """Add comment to document"""
        document = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DocumentCommentSerializer(data=request.data)
        
        if serializer.is_valid():
            # In real implementation, save to Comment model
            comment_data = serializer.validated_data
            
            return Response({
                'detail': 'Comment added successfully',
                'comment': comment_data['comment'],
                'commented_by': f"{request.user.first_name} {request.user.last_name}",
                'commented_at': datetime.now().isoformat()
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        method='post',
        operation_description="Bulk update document status",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'document_ids': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    description='List of document IDs to update'
                ),
                'status': openapi.Schema(type=openapi.TYPE_STRING, description='New status')
            }
        ),
        responses={200: 'Bulk update completed'}
    )
    @action(detail=False, methods=['post'], url_path='bulk-update-status')
    def bulk_update_status(self, request):
        """Bulk update status for multiple documents"""
        document_ids = request.data.get('document_ids', [])
        new_status = request.data.get('status')
        
        if not document_ids or not new_status:
            return Response({'error': 'document_ids and status are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate status
        valid_statuses = ['draft', 'pending', 'pending_approval', 'signed', 'archived']
        if new_status not in valid_statuses:
            return Response({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update documents
        updated_count = Document.objects.filter(
            id__in=document_ids,
            organization=request.user.organization
        ).update(status=new_status)
        
        return Response({
            'detail': f'Successfully updated {updated_count} documents to {new_status} status',
            'updated_count': updated_count
        })

    @swagger_auto_schema(
        method='get',
        operation_description="Get document statistics for the organization",
        responses={200: openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'total_documents': openapi.Schema(type=openapi.TYPE_INTEGER),
                'by_status': openapi.Schema(type=openapi.TYPE_OBJECT),
                'by_template': openapi.Schema(type=openapi.TYPE_OBJECT),
                'recent_activity': openapi.Schema(type=openapi.TYPE_ARRAY),
            }
        )}
    )
    @action(detail=False, methods=['get'], url_path='statistics')
    def document_statistics(self, request):
        """Get document statistics for the organization"""
        user = request.user
        if not user.organization:
            return Response({'error': 'User has no organization'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Total documents
        total_documents = Document.objects.filter(organization=user.organization).count()
        
        # Documents by status
        by_status = dict(Document.objects.filter(organization=user.organization)
                        .values_list('status')
                        .annotate(count=models.Count('id')))
        
        # Documents by template
        by_template = list(Document.objects.filter(organization=user.organization)
                          .values('template__name')
                          .annotate(count=models.Count('id'))
                          .order_by('-count')[:5])
        
        # Recent activity (last 5 documents)
        recent_activity = Document.objects.filter(organization=user.organization)\
                                         .select_related('created_by', 'template')\
                                         .order_by('-updated_at')[:5]
        
        recent_data = []
        for doc in recent_activity:
            recent_data.append({
                'id': doc.id,
                'title': doc.title,
                'status': doc.status,
                'updated_by': f"{doc.created_by.first_name} {doc.created_by.last_name}",
                'updated_at': doc.updated_at.isoformat(),
                'template': doc.template.name if doc.template else None
            })
        
        return Response({
            'total_documents': total_documents,
            'by_status': by_status,
            'by_template': by_template,
            'recent_activity': recent_data
        })

    # --- Your Existing Actions (Enhanced) ---

    @swagger_auto_schema(
        method='post',
        operation_description="Generate the final PDF file from the document's content.",
        responses={
            200: openapi.Response('PDF generated successfully'),
            400: 'Document not in draft status or failed generation.'
        }
    )
    @action(detail=True, methods=['post'], url_path='generate-pdf')
    @transaction.atomic
    def generate_pdf(self, request, pk=None):
        """
        Endpoint to trigger PDF generation (using WeasyPrint).
        """
        document = get_object_or_404(self.get_queryset(), pk=pk)

        if document.status != 'draft':
            return Response({'error': 'Only documents in draft status can be generated.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # REAL PDF Generation Implementation
            from weasyprint import HTML
            from weasyprint.text.fonts import FontConfiguration
            
            font_config = FontConfiguration()
            html = HTML(string=document.final_content)
            
            # Generate PDF
            pdf_file = html.write_pdf(font_config=font_config)
            
            # Save to file field
            filename = f"{document.title.replace(' ', '_')}_{document.id}.pdf"
            document.file_attachment.save(filename, ContentFile(pdf_file))
            
            # Update status
            document.status = 'pending_review'
            document.save()
            
            return Response({
                'detail': f'PDF generated successfully for {document.title}',
                'file_url': document.file_attachment.url,
                'file_size': len(pdf_file)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({'error': f'PDF generation failed: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        method='post',
        operation_description="Digitally sign the document, changing its status if required by the workflow.",
        request_body=DigitalSignatureSerializer,
        responses={200: DigitalSignatureSerializer, 400: 'Signature not allowed or document finalized.'}
    )
    @action(detail=True, methods=['post'], url_path='sign')
    @transaction.atomic
    def sign_document(self, request, pk=None):
        """
        Records the current user's digital signature on the document.
        """
        document = get_object_or_404(self.get_queryset(), pk=pk)
        user = request.user
        
        # 1. Workflow Check (Placeholder: Ensure signing is allowed)
        if document.status not in ['pending', 'pending_approval']:
             return Response({'error': 'Document cannot be signed in its current status.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 2. Check if user already signed this document
        if DigitalSignatureLog.objects.filter(document=document, signer=user).exists():
            return Response({'error': 'You have already signed this document.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 3. Get the user's current primary role in the organization
        membership = get_object_or_404(
            user.organizationmembership_set.all(), 
            organization=document.organization, 
            is_active=True
        )
        signer_role = membership.role

        # 4. Create the Signature Log
        signature_data = {
            'document': document.id,
            'signer': user.id,
            'signer_role': signer_role,
            'signature_data': request.data.get('signature_data', ''),
            'signing_reason': request.data.get('signing_reason', ''),
            'ip_address': self.get_client_ip(request),
        }
        
        signature_serializer = DigitalSignatureSerializer(data=signature_data)
        
        try:
            signature_serializer.is_valid(raise_exception=True)
            signature = signature_serializer.save(
                document=document, 
                signer=user, 
                signer_role=signer_role,
                ip_address=self.get_client_ip(request)
            )
        except Exception as e:
            return Response({'error': f'Signature failed: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
            
        # 5. Update Document Status based on signature count
        signature_count = document.signatures.count()
        if signature_count >= 2:  # Example: require 2 signatures for completion
            document.status = 'signed'
        elif signature_count >= 1:
            document.status = 'pending_final_signature'
            
        document.save()
        
        return Response({
            'detail': f'Document signed successfully by {user.email} as {signer_role}.',
            'signature_id': signature.id,
            'total_signatures': signature_count,
            'document_status': document.status
        }, status=status.HTTP_200_OK)

    def get_client_ip(self, request):
        """Get client IP address for audit logging"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip