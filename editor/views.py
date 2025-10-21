# editor/views.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema

from .models import SpreadsheetDocument
from .serializers import SpreadsheetDocumentSerializer, SpreadsheetDataSerializer

# NOTE: Mocking imports and aggregation logic for demonstration
# In a real app, you would import models from documents, workflow, chat, etc.

class SpreadsheetDocumentViewSet(viewsets.ModelViewSet):
    """
    A ViewSet for viewing, creating, saving (PUT/PATCH), and loading 
    the interactive spreadsheet documents.
    """
    queryset = SpreadsheetDocument.objects.all()
    serializer_class = SpreadsheetDocumentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        """Sets the owner to the current user on creation."""
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=['get', 'put', 'patch'])
    def data(self, request, pk=None):
        """
        GET: Retrieves the full JSON payload for the editor.
        PUT/PATCH: Saves the full JSON payload sent by the editor.
        """
        doc = self.get_object()

        if request.method == 'GET':
            # Load: Return the raw stored editor_data
            return Response(doc.editor_data or {})
            
        elif request.method in ['PUT', 'PATCH']:
            # Save: Validate the incoming data structure and save it
            
            # Use the data serializer for basic structure validation
            data_serializer = SpreadsheetDataSerializer(data=request.data)
            data_serializer.is_valid(raise_exception=True)
            
            # Save the validated, complex JSON blob directly to the field
            doc.editor_data = request.data
            doc.save()
            
            return Response({
                "id": doc.pk,
                "status": "Spreadsheet content updated successfully",
                "last_updated": doc.updated_at,
                "checksum": hash(str(doc.editor_data)) # Simple mock checksum
            })

class DashboardMetricsView(APIView):
    """
    API endpoint to retrieve aggregated metrics (The core dashboard view).
    """
    permission_classes = [IsAuthenticated]
    
    # Note: Swagger definition is complex, omitted here for brevity, 
    # but defined in the previous documentation response.
    
    def get(self, request, *args, **kwargs):
        user = request.user
        
        # --- MOCK AGGREGATION LOGIC ---
        # Replace these mock numbers with actual database queries (e.g., .aggregate(), .filter().count())
        
        # 1. User & Workflow Summary
        user_summary = {
            'documents_uploaded_total': 55,
            'pending_approval_steps': 7,
            'unread_chat_messages': 15,
        }

        # 2. Organization KPIs
        org_kpis = {
            'active_projects': 4,
            'total_documents_stored': 845,
            'total_budget_allocated': 150000.00,
        }

        # 3. Document Breakdown (Including new spreadsheet type)
        doc_breakdown = {
            'standard_docs': 750,
            'spreadsheet_docs': SpreadsheetDocument.objects.filter(owner=user).count(),
            'docs_uploaded_last_week': 34,
        }

        dashboard_data = {
            'timestamp': timezone.now(),
            'user_summary': user_summary,
            'organization_kpis': org_kpis,
            'document_breakdown': doc_breakdown,
        }

        return Response(dashboard_data)