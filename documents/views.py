# documents/views.py

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import DocumentTemplate, Document, DigitalSignatureLog
from .serializers import (
    DocumentTemplateSerializer, 
    DocumentCreateSerializer, 
    DocumentDetailSerializer, 
    DigitalSignatureSerializer
)



class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Document Templates.
    Templates are organization-specific blueprints for documents.
    """
    serializer_class = DocumentTemplateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'delete']

    def get_queryset(self):
        """Filter templates to only show those belonging to the user's primary organization."""
        user = self.request.user
        if not user.is_authenticated or not user.organization:
            # Should be caught by IsAuthenticated, but ensures security
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

# -----------------------------------------------------------------------------

class DocumentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Document Instances and their full lifecycle.
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'delete']

    def get_serializer_class(self):
        """Swaps serializers based on the action for optimized payload."""
        if self.action == 'create':
            return DocumentCreateSerializer
        return DocumentDetailSerializer

    def get_queryset(self):
        """Filter documents to only show those belonging to the user's primary organization."""
        user = self.request.user
        if not user.is_authenticated or not user.organization:
            return Document.objects.none()

        # Users can see documents they created OR documents they have permission to view (optional, needs full permission implementation)
        return Document.objects.filter(organization=user.organization).order_by('-updated_at')

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
        operation_description="Retrieve a specific document instance by ID.",
        responses={200: DocumentDetailSerializer}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    # --- Custom Actions ---

    @swagger_auto_schema(
        method='post',
        operation_description="Generate the final PDF file from the document's content.",
        responses={
            200: openapi.Response(
                'PDF generated successfully',
                # Define a simple response model indicating success and file path
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}
                )
            ),
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

        # --- Placeholder for PDF Generation Logic (using WeasyPrint) ---
        # 1. Substitute placeholders in document.final_content
        # 2. Use WeasyPrint to render HTML to PDF
        # 3. Save the PDF file to document.file_attachment (using Django Storages)
        # 4. Update the document status if successful (e.g., to 'pending_review')
        # ------------------------------------------------------------------
        
        # For now, simulate success:
        # document.status = 'pending_review' 
        # document.save()

        return Response({'detail': f'PDF generation simulated for Document {document.title}.'}, status=status.HTTP_200_OK)


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
        # In a real app, this checks the workflow app for the next required signer.
        if document.status not in ['pending', 'pending_approval']:
             return Response({'error': 'Document cannot be signed in its current status.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 2. Get the user's current primary role in the organization
        membership = get_object_or_404(
            user.organizationmembership_set.all(), 
            organization=document.organization, 
            is_active=True
        )
        signer_role = membership.role

        # 3. Create the Signature Log
        signature_data = {
            'document': document.id,
            'signer': user.id,
            'signer_role': signer_role,
            # content_hash logic would go here
        }
        
        signature_serializer = DigitalSignatureSerializer(data=signature_data)
        
        try:
            signature_serializer.is_valid(raise_exception=True)
            signature = signature_serializer.save(document=document, signer=user, signer_role=signer_role)
        except Exception as e:
            # Catches unique_together violation (user already signed)
            return Response({'error': f'Signature failed: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
            
        # 4. Update Document Status (Placeholder for finalization)
        # In the future, this should check if ALL required signatures are done 
        # based on the workflow before setting status to 'signed'.
        if document.signatures.count() >= 1: # Example: if 1+ signatures, set to pending workflow
            document.status = 'pending'
        # Final transition to 'signed' will be handled by the Workflow App later.
        document.save()
        
        return Response({
            'detail': f'Document signed successfully by {user.email} as {signer_role}.',
            'signature_id': signature.id,
        }, status=status.HTTP_200_OK)